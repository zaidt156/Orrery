"""file.generate — produce any file by having the model WRITE CODE that we run in the sandbox.

The loop: select skills → ask the model for one Python program (guided by the skill) → run it in
the locked-down sandbox → if it errors or makes no file, feed the traceback back and retry (bounded)
→ return the files it wrote to ./out. This is the open-source "code interpreter" mechanism; no model
code ever runs in the backend (see backend/features/sandbox.py and docs/FILE_GENERATION_ARCHITECTURE.md).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from backend.features import sandbox, skills
from backend.providers import ai

MAX_ATTEMPTS = 3
QUALITY_FILE_EFFORT = "high"
QUALITY_CLAUDE_PLAN_EFFORT = "xhigh"
_CODE_FENCE = re.compile(r"```(?:python|py)?\s*\n([\s\S]*?)```", re.IGNORECASE)

# strong, precise file intent: a creation verb is not required — naming a concrete artifact is enough
_FILE_INTENT = re.compile(
    r"\b(pdf|docx|word\s+doc(?:ument)?|excel|xlsx|spreadsheet|workbook|powerpoint|pptx|"
    r"presentation|slide\s*deck|slides?|deck|csv|chart|graph|plot|diagram|infographic|"
    r"invoice|resume|cv|brochure|flyer|certificate|\.(?:pdf|docx?|xlsx?|pptx?|csv|png|jpe?g|gif))\b",
    re.IGNORECASE,
)
_CREATE_VERB = re.compile(
    r"\b(create|make|generate|build|give\s+me|need|want|produce|export|draft|design|prepare|"
    r"put\s+together|write\s+me|turn\s+.*\binto|as\s+an?)\b",
    re.IGNORECASE,
)

_SYSTEM = (
    'You generate FILES by writing ONE Python program that runs in a locked-down, OFFLINE sandbox.\n'
    'Reply with a single ```python code block and NOTHING else - no prose before or after.\n'
    'Quality bar:\n'
    "- Think like a senior document designer and production engineer before writing code. The file must be complete, polished, useful, and directly tailored to the user's request.\n"
    '- Never create placeholder, stub, filler, lorem ipsum, TODO, empty, single-slide, or generic template files unless the user explicitly requested a template.\n'
    '- Use the strongest suitable library for the format: python-pptx for PPTX, reportlab/fpdf2 for PDF, python-docx for Word, openpyxl/XlsxWriter for Excel, pandas only when it helps.\n'
    '- For PowerPoint: use a real widescreen deck, a designed cover slide, clear slide hierarchy, concise slide titles, useful speaker notes when appropriate, balanced spacing, readable type sizes, restrained colors, and no overcrowded bullet dumps.\n'
    '- For PDF/Word: use headings, sections, tables where useful, page numbers or document metadata when appropriate, readable margins, and professional typography.\n'
    '- For Excel/CSV: create clean headers, typed rows, formatting, widths, freeze panes, filters, formulas only when useful, and neutralize formula-like user text when it should remain text.\n'
    'Requirements:\n'
    '- Save every deliverable into the ./out directory (it already exists), with clear filenames and correct extensions.\n'
    "- Build real, complete, polished files that fully satisfy the request - never placeholders, stubs, or 'TODO' content.\n"
    '- Reopen or validate each generated file in code before finishing when the library supports it. If validation fails, fix the file before printing success.\n'
    "- Available libraries: python-docx, openpyxl, XlsxWriter, python-pptx, reportlab, fpdf2, pandas, numpy, matplotlib (use matplotlib.use('Agg')), Pillow, markdown, beautifulsoup4, lxml, odfpy, plus the Python standard library.\n"
    '- No network access of any kind; everything must work fully offline.\n'
    '- Do not read or write outside ./out. print() the name of each file you create.\n'
    '- Create only the file types the user asked for, unless they explicitly request companion exports.'
)


def wants_file(text: str) -> bool:
    """True when the user is asking for a downloadable file (vs. an in-chat answer)."""
    if not text:
        return False
    return bool(_FILE_INTENT.search(text) and (_CREATE_VERB.search(text) or "." in text))


# File requests that genuinely need code execution (charts, images, computation). Plain
# documents/decks/spreadsheets go through the much faster structured builder instead of
# the spin-up-a-container, write-code, run, maybe-retry loop.
_NEEDS_CODE = re.compile(
    r"\b(chart|graph|plot|diagram|figure|visuali[sz]|infographic|image|picture|photo|logo|icon|"
    r"calculat|comput|analy[sz]|statistic|regression|simulat|forecast|matplotlib|seaborn|"
    r"\.(png|jpe?g|gif|svg|zip|tar))\b",
    re.IGNORECASE,
)


def needs_code(text: str) -> bool:
    return bool(text and _NEEDS_CODE.search(text))


def quality_effort(model: str, effort: str | None) -> str:
    """File jobs should not inherit low/auto chat effort; they need deliberate planning."""
    if effort in {"high", "xhigh", "max"}:
        return effort
    if (model or "").startswith("claude_plan/"):
        return QUALITY_CLAUDE_PLAN_EFFORT
    return QUALITY_FILE_EFFORT


def _extract_code(text: str) -> str:
    match = _CODE_FENCE.search(text or "")
    if match:
        return match.group(1).strip()
    stripped = (text or "").strip()
    looks_like_code = any(token in stripped for token in ("import ", "os.makedirs", "def ", "with open("))
    return stripped if looks_like_code else ""


def _guard(code: str) -> str:
    return "import os as _os\n_os.makedirs('out', exist_ok=True)\n" + code


def _summary(files: list[sandbox.SandboxFile]) -> str:
    if len(files) == 1:
        return f"Here is your file: **{files[0].name}**."
    names = ", ".join(f"**{f.name}**" for f in files)
    return f"Done — created {len(files)} files: {names}."


async def run(model: str, request: str, system_prompt: str | None, effort: str | None) -> AsyncIterator[dict]:
    """Yield {'status': ...} progress and a final {'result': {...}} with files or an error."""
    file_effort = quality_effort(model, effort)
    skill_block = skills.skills_prompt(request)
    instructions = _SYSTEM + (f"\n\n{skill_block}" if skill_block else "")
    if system_prompt:
        instructions += f"\n\nUser's standing instructions:\n{system_prompt.strip()[:2000]}"
    convo: list[dict] = [{"role": "user", "content": request}]
    last_error = ""

    for attempt in range(MAX_ATTEMPTS):
        yield {"status": "Designing a polished file with high reasoning..." if attempt == 0 else f"Fixing errors and retrying ({attempt + 1}/{MAX_ATTEMPTS})…"}
        parts: list[str] = []
        try:
            async for delta in ai.stream_chat(model, convo, instructions, file_effort):
                if isinstance(delta, ai.ReasoningDelta):
                    yield {"reasoning": str(delta)}  # show the model's thinking live
                else:
                    parts.append(str(delta))
        except ai.MissingKeyError as exc:
            yield {"result": {"ok": False, "error": f"No API key for {exc.provider}. Add it in Settings."}}
            return
        except Exception as exc:  # noqa: BLE001 — provider errors already sanitized upstream
            yield {"result": {"ok": False, "error": str(exc)}}
            return

        reply = "".join(parts)
        code = _extract_code(reply)
        if not code:
            convo += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "Reply with ONLY one ```python code block that writes the file(s) into ./out."},
            ]
            continue

        yield {"status": "Running the code in a secure sandbox…"}
        outcome = await asyncio.to_thread(sandbox.run_code, _guard(code))
        if outcome.ok and outcome.files:
            yield {"result": {"ok": True, "files": outcome.files, "code": code, "summary": _summary(outcome.files)}}
            return

        last_error = (outcome.stderr or outcome.stdout or "The code ran but wrote no files to ./out.").strip()[:3000]
        convo += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"That failed or produced no files in ./out. Fix it and reply with ONLY the corrected Python.\n\nError / output:\n{last_error}"},
        ]

    yield {"result": {"ok": False, "error": "I couldn't build the file after several attempts.", "logs": last_error}}
