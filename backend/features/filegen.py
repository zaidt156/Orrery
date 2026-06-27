"""file.generate — produce any file by having the model WRITE CODE that we run in the sandbox.

The loop: select skills → ask the model for one Python program (guided by the skill) → run it in
the locked-down sandbox → validate the generated files in the backend → if it errors, produces no
file, or fails quality checks, feed the failure reason back and retry (bounded) → return approved
files from ./out.

This is the open-source "code interpreter" mechanism; no model code ever runs in the backend
(see backend/features/sandbox.py and docs/FILE_GENERATION_ARCHITECTURE.md).
"""

from __future__ import annotations

import ast
import asyncio
import csv
import io
import re
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from backend.features import sandbox, skills
from backend.features.prompting import build_system_prompt
from backend.features.reasoning_trace import ReasoningCondenser, reasoning_event
from backend.providers import ai

MAX_ATTEMPTS = 3
QUALITY_FILE_EFFORT = "high"
QUALITY_CLAUDE_PLAN_EFFORT = "xhigh"
_CODE_FENCE = re.compile(r"```(?:python|py)?\s*\n([\s\S]*?)```", re.IGNORECASE)

# strong, precise file intent: a creation verb is not required — naming a concrete artifact is enough
_FILE_INTENT = re.compile(
    r"\b(pdf|docx|word\s+doc(?:ument)?|excel|xlsx|spreadsheet|workbook|powerpoint|pptx|"
    r"presentation|slide\s*deck|slides?|deck|csv|chart|graph|plot|diagram|infographic|"
    r"invoice|resume|cv|brochure|flyer|certificate|\.(?:pdf|docx?|xlsx?|pptx?|csv|png|jpe?g|gif|svg|zip))\b",
    re.IGNORECASE,
)
_CREATE_VERB = re.compile(
    r"\b(create|make|generate|build|give\s+me|need|want|produce|export|draft|design|prepare|"
    r"put\s+together|write\s+me|turn\s+.*\binto|as\s+an?)\b",
    re.IGNORECASE,
)

# File requests that benefit from the richer code-execution path. PRESENTATIONS go here too:
# the model designs the deck freely (varied layouts, visuals) instead of the fixed docgen template —
# docgen remains the fast fallback. Plain Word/Excel/PDF docs still route to docgen first.
_NEEDS_CODE = re.compile(
    r"\b(powerpoint|pptx|presentation|slide\s*deck|slides?|deck|"
    r"chart|graph|plot|diagram|figure|visuali[sz]|infographic|image|picture|photo|logo|icon|"
    r"calculat|comput|analy[sz]|statistic|regression|simulat|forecast|matplotlib|seaborn|"
    r"\.(png|jpe?g|gif|svg|zip|tar))\b",
    re.IGNORECASE,
)

_FORMAT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pdf", re.compile(r"\bpdf\b|\.pdf\b", re.I)),
    ("docx", re.compile(r"\b(word\s+doc(?:ument)?|docx?)\b|\.docx?\b", re.I)),
    ("xlsx", re.compile(r"\b(excel|xlsx?|spreadsheet|workbook|sheet)\b|\.xlsx?\b", re.I)),
    ("pptx", re.compile(r"\b(powerpoint|pptx?|presentation|slide\s*deck|slides?|deck)\b|\.pptx?\b", re.I)),
    ("csv", re.compile(r"\bcsv\b|\.csv\b", re.I)),
    ("png", re.compile(r"\bpng\b|\.png\b", re.I)),
    ("jpg", re.compile(r"\bjpe?g\b|\.jpe?g\b", re.I)),
    ("gif", re.compile(r"\bgif\b|\.gif\b", re.I)),
    ("svg", re.compile(r"\bsvg\b|\.svg\b", re.I)),
    ("zip", re.compile(r"\bzip\b|\.zip\b", re.I)),
)

_EXTENSION_TO_FORMAT = {
    "pdf": "pdf",
    "doc": "docx",
    "docx": "docx",
    "xls": "xlsx",
    "xlsx": "xlsx",
    "xlsm": "xlsx",
    "ppt": "pptx",
    "pptx": "pptx",
    "csv": "csv",
    "png": "png",
    "jpg": "jpg",
    "jpeg": "jpg",
    "gif": "gif",
    "svg": "svg",
    "zip": "zip",
    "md": "md",
    "txt": "txt",
    "html": "html",
    "json": "json",
}

_PLACEHOLDER_RE = re.compile(
    r"\b(todo|lorem ipsum|placeholder|insert text here|sample text|tbd|your name|company name|"
    r"\[title\]|\[date\]|\[name\]|\[company\])\b",
    re.IGNORECASE,
)

_SMALL_ARTIFACT_OK = re.compile(
    r"\b(one\s+page|1\s+page|one\s+slide|1\s+slide|single\s+slide|thumbnail|icon|logo|"
    r"template|blank|sample|example|draft|short|simple)\b",
    re.IGNORECASE,
)

_OFFICIAL_DOCUMENT_RE = re.compile(
    r"\b(medical certificate|doctor'?s?\s+note|sick note|health certificate|degree certificate|"
    r"diploma|transcript|residence permit|visa|passport|identity card|id card|driver'?s?\s+license|"
    r"bank statement|payslip|pay slip|tax document|government form|immigration document|"
    r"employment contract|signed letter|stamped letter)\b",
    re.IGNORECASE,
)
_DECEPTIVE_DOCUMENT_RE = re.compile(
    r"\b(fake|forge|forgery|counterfeit|backdate|change|replace|edit|modify|copy|clone|"
    r"exactly\s+same|look\s+same|make\s+it\s+look|signature|signed|stamp|stamped|official|submit|use\s+it)\b",
    re.IGNORECASE,
)
_SAFE_SAMPLE_RE = re.compile(
    r"\b(blank template|template|sample|fictional|mock|training|example|clearly marked|not for use|"
    r"watermark|draft)\b",
    re.IGNORECASE,
)

_SYSTEM = (
    "You generate FILES by writing ONE Python program that runs in a locked-down, OFFLINE sandbox.\n"
    "Reply with a single ```python code block and NOTHING else - no prose before or after.\n"
    "Quality bar:\n"
    "- Think like a senior document designer and production engineer before writing code. The file must be complete, polished, useful, and directly tailored to the user's request.\n"
    "- Never create placeholder, stub, filler, lorem ipsum, TODO, empty, single-slide, or generic template files unless the user explicitly requested a template.\n"
    "- Use the strongest suitable library for the format: python-pptx for PPTX, reportlab/fpdf2 for PDF, python-docx for Word, openpyxl/XlsxWriter for Excel, pandas only when it helps.\n"
    "- For PowerPoint: use a real 16:9 widescreen deck with a designed cover, and VARY the layouts across slides (section dividers, two-column comparisons, a metric/stat callout, an image or shape-based visual slide) — do NOT make every slide an identical title+bullets list. Use a consistent color theme, concise titles, a relevant drawn/generated visual or accent on most content slides, speaker notes where useful, generous spacing, and no overcrowded bullet dumps.\n"
    "- For PDF/Word: use headings, sections, tables where useful, page numbers or document metadata when appropriate, readable margins, and professional typography.\n"
    "- For Excel/CSV: create clean headers, typed rows, formatting, widths, freeze panes, filters, formulas only when useful, and neutralize formula-like user text when it should remain text.\n"
    "Safety requirements:\n"
    "- Do not create, alter, imitate, backdate, or forge official, medical, academic, legal, banking, employment, immigration, or identity documents in a way that could deceive.\n"
    "- If the user asks for an official-document template or sample, make it clearly fictional/sample/watermarked and not usable as a real document.\n"
    "Technical requirements:\n"
    "- Save every deliverable into the ./out directory (it already exists), with clear filenames and correct extensions.\n"
    "- Build real, complete, polished files that fully satisfy the request - never placeholders, stubs, or 'TODO' content.\n"
    "- Reopen or validate each generated file in code before finishing when the library supports it. If validation fails, fix the file before printing success.\n"
    "- Available libraries: python-docx, openpyxl, XlsxWriter, python-pptx, reportlab, fpdf2, pandas, numpy, matplotlib (use matplotlib.use('Agg')), Pillow, markdown, beautifulsoup4, lxml, odfpy, plus the Python standard library.\n"
    "- No network access of any kind; everything must work fully offline.\n"
    "- Images/visuals: the sandbox is OFFLINE — NEVER download images or fetch URLs (it will fail and "
    "waste the attempt). Create visuals in code instead: matplotlib charts, Pillow-drawn graphics/"
    "diagrams/icons, or python-pptx shapes and color blocks. If the user asks for photos you cannot "
    "draw, use tasteful shape/gradient graphics or clearly labeled placeholders and PROCEED — never let "
    "missing images block the file.\n"
    "- Do not read or write outside ./out. print() the name of each file you create.\n"
    "- Create only the file types the user asked for, unless they explicitly request companion exports."
)


@dataclass
class FileCheck:
    name: str
    format: str
    size: int
    ok: bool
    checks: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class Approval:
    ok: bool
    files: list[sandbox.SandboxFile]
    manifest: list[dict]
    reason: str = ""


def wants_file(text: str) -> bool:
    """True when the user is asking for a downloadable file (vs. an in-chat answer)."""
    if not text:
        return False
    return bool(_FILE_INTENT.search(text) and (_CREATE_VERB.search(text) or "." in text))


def needs_code(text: str) -> bool:
    return bool(text and _NEEDS_CODE.search(text))


def requested_formats(text: str) -> list[str]:
    """Return explicit output formats requested by the user, preserving priority order."""
    found: list[str] = []
    for fmt, pattern in _FORMAT_PATTERNS:
        if pattern.search(text or "") and fmt not in found:
            found.append(fmt)
    return found


def quality_effort(model: str, effort: str | None) -> str:
    """File jobs should not inherit low/auto chat effort; they need deliberate planning."""
    if effort in {"high", "xhigh", "max"}:
        return effort
    if (model or "").startswith("claude_plan/"):
        return QUALITY_CLAUDE_PLAN_EFFORT
    return QUALITY_FILE_EFFORT


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _format_for_name(name: str) -> str:
    return _EXTENSION_TO_FORMAT.get(_extension(name), "unknown")


def _valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _extract_code(text: str) -> str:
    match = _CODE_FENCE.search(text or "")
    if match:
        return match.group(1).strip()

    # Only accept unfenced output if the entire response is valid Python.
    # This avoids accidentally running prose that merely contains "import" or "def".
    stripped = (text or "").strip()
    return stripped if stripped and _valid_python(stripped) else ""


def _guard(code: str) -> str:
    return "import os as _os\n_os.makedirs('out', exist_ok=True)\n" + code


def _summary(files: list[sandbox.SandboxFile]) -> str:
    if len(files) == 1:
        return f"Here is your file: **{files[0].name}**."
    names = ", ".join(f"**{f.name}**" for f in files)
    return f"Done — created {len(files)} files: {names}."


def _official_document_error(request: str) -> str | None:
    text = request or ""
    official = bool(_OFFICIAL_DOCUMENT_RE.search(text))
    deceptive = bool(_DECEPTIVE_DOCUMENT_RE.search(text))
    safe_sample = bool(_SAFE_SAMPLE_RE.search(text))

    if official and deceptive and not safe_sample:
        return (
            "I can't generate or modify official, medical, academic, legal, banking, employment, "
            "immigration, or identity documents in a way that could deceive. I can help create a "
            "clearly marked sample/template, a checklist, or an explanation of what a legitimate "
            "document should contain."
        )
    return None


def _requested_file_filter(files: list[sandbox.SandboxFile], request: str) -> tuple[list[sandbox.SandboxFile], str | None]:
    wanted = requested_formats(request)
    if not wanted:
        return files, None

    kept = [f for f in files if _format_for_name(f.name) in wanted]
    if kept:
        return kept, None

    actual = sorted({_format_for_name(f.name) for f in files})
    return [], (
        "Generated files did not match the requested format. "
        f"Requested: {', '.join(wanted)}. Generated: {', '.join(actual) or 'none'}."
    )


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _extract_docx_text(data: bytes) -> tuple[str, list[str]]:
    from docx import Document

    document = Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells if cell.text.strip())
    checks = ["opens_as_docx"]
    if parts:
        checks.append("contains_text")
    if document.tables:
        checks.append("contains_tables")
    return "\n".join(parts), checks


def _extract_pptx_text(data: bytes) -> tuple[str, list[str], int]:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    parts: list[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if text:
                    parts.append(text)
    checks = ["opens_as_pptx", f"slide_count:{len(prs.slides)}"]
    if parts:
        checks.append("contains_text")
    return "\n".join(parts), checks, len(prs.slides)


def _extract_xlsx_text(data: bytes) -> tuple[str, list[str], int, int]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    try:
        parts: list[str] = []
        row_count = 0
        non_empty_cells = 0
        for sheet in workbook.worksheets:
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if row_index > 500:
                    break
                values = ["" if v is None else str(v) for v in row]
                if any(v.strip() for v in values):
                    row_count += 1
                    non_empty_cells += sum(1 for v in values if v.strip())
                    parts.append("\t".join(values))
        checks = ["opens_as_xlsx", f"sheet_count:{len(workbook.worksheets)}"]
        if row_count:
            checks.append(f"non_empty_rows:{row_count}")
        return "\n".join(parts), checks, row_count, non_empty_cells
    finally:
        workbook.close()


def _extract_pdf_text(data: bytes) -> tuple[str, list[str], int]:
    checks = ["has_pdf_header"] if data.startswith(b"%PDF") else []
    if not data.startswith(b"%PDF"):
        raise ValueError("PDF does not start with a valid %PDF header.")

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
        text = "\n".join((page.extract_text() or "").strip() for page in reader.pages)
        checks.append(f"page_count:{page_count}")
        if text.strip():
            checks.append("contains_extractable_text")
        return text, checks, page_count
    except Exception:  # noqa: BLE001
        # Header is valid, but extraction failed. Treat as weakly valid so image-based PDFs can pass.
        checks.append("pdf_text_extraction_unavailable")
        return "", checks, 0


def _extract_csv_text(data: bytes) -> tuple[str, list[str], int, int]:
    text = _decode_text(data)
    rows = list(csv.reader(io.StringIO(text)))
    row_count = len(rows)
    width = max((len(row) for row in rows), default=0)
    checks = ["parses_as_csv", f"row_count:{row_count}", f"max_columns:{width}"]
    return text, checks, row_count, width


def _validate_image(data: bytes, fmt: str) -> tuple[str, list[str]]:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        image.verify()
    return "", [f"opens_as_image:{fmt}", f"dimensions:{width}x{height}"]


def _validate_svg(data: bytes) -> tuple[str, list[str]]:
    import xml.etree.ElementTree as ET

    text = _decode_text(data)
    root = ET.fromstring(text)
    tag = str(root.tag).rsplit("}", 1)[-1]
    if tag != "svg":
        raise ValueError("SVG root element is not <svg>.")
    return text, ["parses_as_svg"]


def _validate_zip(data: bytes) -> tuple[str, list[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("ZIP contains an unsafe path traversal entry.")
        bad = zf.testzip()
        if bad:
            raise ValueError(f"ZIP contains a corrupt member: {bad}")
    return "\n".join(names), ["opens_as_zip", f"member_count:{len(names)}"]


def _extract_and_validate(file: sandbox.SandboxFile, request: str) -> FileCheck:
    fmt = _format_for_name(file.name)
    check = FileCheck(name=file.name, format=fmt, size=len(file.data), ok=True)

    try:
        if fmt == "docx":
            text, checks = _extract_docx_text(file.data)
            check.checks.extend(checks)
            _check_text_quality(check, text, request, minimum_chars=120)
        elif fmt == "pptx":
            text, checks, slide_count = _extract_pptx_text(file.data)
            check.checks.extend(checks)
            _check_text_quality(check, text, request, minimum_chars=80)
            if slide_count < 4 and not _SMALL_ARTIFACT_OK.search(request or ""):
                check.issues.append("PowerPoint has fewer than 4 slides for a non-trivial deck request.")
        elif fmt == "xlsx":
            text, checks, row_count, non_empty_cells = _extract_xlsx_text(file.data)
            check.checks.extend(checks)
            if row_count < 1 or non_empty_cells < 1:
                check.issues.append("Spreadsheet has no non-empty rows/cells.")
            _check_text_quality(check, text, request, minimum_chars=20, require_text=False)
        elif fmt == "pdf":
            text, checks, page_count = _extract_pdf_text(file.data)
            check.checks.extend(checks)
            if page_count == 0:
                check.checks.append("page_count_unknown")
            _check_text_quality(check, text, request, minimum_chars=120, require_text=False)
        elif fmt == "csv":
            text, checks, row_count, width = _extract_csv_text(file.data)
            check.checks.extend(checks)
            if row_count < 1 or width < 1:
                check.issues.append("CSV has no usable rows/columns.")
            _check_text_quality(check, text, request, minimum_chars=20, require_text=False)
        elif fmt in {"png", "jpg", "gif"}:
            _text, checks = _validate_image(file.data, fmt)
            check.checks.extend(checks)
        elif fmt == "svg":
            text, checks = _validate_svg(file.data)
            check.checks.extend(checks)
            _check_text_quality(check, text, request, minimum_chars=20, require_text=False)
        elif fmt == "zip":
            text, checks = _validate_zip(file.data)
            check.checks.extend(checks)
            if not text.strip():
                check.issues.append("ZIP archive is empty.")
        elif fmt in {"md", "txt", "html", "json"}:
            text = _decode_text(file.data)
            check.checks.append(f"decodes_as_{fmt}")
            _check_text_quality(check, text, request, minimum_chars=80)
        else:
            check.issues.append(f"Unsupported or unknown output format: {file.name}")
    except Exception as exc:  # noqa: BLE001
        check.issues.append(f"Could not validate {file.name}: {str(exc)[:180]}")

    check.ok = not check.issues
    return check


def _check_text_quality(
    check: FileCheck,
    text: str,
    request: str,
    *,
    minimum_chars: int,
    require_text: bool = True,
) -> None:
    clean = " ".join((text or "").split())
    if require_text and not clean:
        check.issues.append("Generated file contains no readable text.")
        return

    if clean:
        check.checks.append(f"text_chars:{len(clean)}")

    if clean and _PLACEHOLDER_RE.search(clean):
        check.issues.append("Generated file contains placeholder/TODO/sample text.")

    if (
        clean
        and len(clean) < minimum_chars
        and not _SMALL_ARTIFACT_OK.search(request or "")
        and len((request or "").split()) > 6
    ):
        check.issues.append("Generated content is too thin for the user's request.")


def _approve_files(files: list[sandbox.SandboxFile], request: str) -> Approval:
    filtered, filter_error = _requested_file_filter(files, request)
    if filter_error:
        return Approval(ok=False, files=[], manifest=[], reason=filter_error)

    if not filtered:
        return Approval(ok=False, files=[], manifest=[], reason="The sandbox produced no files to approve.")

    checks = [_extract_and_validate(file, request) for file in filtered]
    manifest = [
        {
            "name": c.name,
            "format": c.format,
            "size": c.size,
            "ok": c.ok,
            "checks": c.checks,
            "issues": c.issues,
        }
        for c in checks
    ]

    failed = [c for c in checks if not c.ok]
    if failed:
        reasons = []
        for c in failed:
            reasons.append(f"{c.name}: " + "; ".join(c.issues))
        return Approval(ok=False, files=[], manifest=manifest, reason="\n".join(reasons)[:3000])

    return Approval(ok=True, files=filtered, manifest=manifest)


async def run(
    model: str,
    request: str,
    system_prompt: str | None,
    effort: str | None,
    untrusted_context: str | None = None,
) -> AsyncIterator[dict]:
    """Yield progress events and a final {'result': {...}} with approved files or an error."""
    safety_error = _official_document_error(request)
    if safety_error:
        yield {"result": {"ok": False, "error": safety_error}}
        return

    file_effort = quality_effort(model, effort)
    instructions = build_system_prompt(
        app_rules=_SYSTEM,
        skills_block=skills.skills_prompt(request),
        user_preferences=system_prompt,
        untrusted_context=untrusted_context,
    )
    convo: list[dict] = [{"role": "user", "content": request}]
    last_error = ""

    for attempt in range(MAX_ATTEMPTS):
        yield {
            "status": (
                "Designing the document…"
                if attempt == 0
                else f"Fixing the generated file ({attempt + 1}/{MAX_ATTEMPTS})…"
            )
        }
        yield reasoning_event(
            "Preparing generation" if attempt == 0 else "Repairing generation",
            (
                "Choosing the file-building approach and generating Python for the sandbox."
                if attempt == 0
                else "Using the previous validation/runtime failure to improve the generated file."
            ),
        )

        parts: list[str] = []
        condenser = ReasoningCondenser()
        try:
            async for delta in ai.stream_chat(model, convo, instructions, file_effort):
                if isinstance(delta, ai.ReasoningDelta):
                    for ev in condenser.feed(str(delta)):  # condensed thinking, not raw CoT
                        yield ev
                    continue
                parts.append(str(delta))
            for ev in condenser.finish():
                yield ev
        except ai.MissingKeyError as exc:
            yield {"result": {"ok": False, "error": f"No API key for {exc.provider}. Add it in Settings."}}
            return
        except Exception as exc:  # noqa: BLE001 — provider errors already sanitized upstream
            yield {"result": {"ok": False, "error": str(exc)}}
            return

        reply = "".join(parts)
        code = _extract_code(reply)
        if not code:
            last_error = "The model did not return a valid Python program."
            convo += [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": (
                        "Reply with ONLY one fenced ```python code block that writes the requested "
                        "file(s) into ./out. No prose before or after."
                    ),
                },
            ]
            continue

        yield {"status": "Building the file…"}
        yield reasoning_event(
            "Running sandbox",
            "Executing the code in the locked-down offline sandbox and collecting output files.",
        )

        outcome = await asyncio.to_thread(sandbox.run_code, _guard(code))
        if outcome.ok and outcome.files:
            yield {"status": "Checking the output…"}
            yield reasoning_event(
                "Validating output",
                "Opening the generated files, checking requested formats, scanning for placeholders, and enforcing basic quality gates.",
            )
            # validation parses real Office/PDF/image files — do it off the event loop
            approval = await asyncio.to_thread(_approve_files, outcome.files, request)
            if approval.ok:
                yield {
                    "result": {
                        "ok": True,
                        "files": approval.files,
                        "code": code,
                        "summary": _summary(approval.files),
                        "manifest": approval.manifest,
                    }
                }
                return

            last_error = approval.reason
            convo += [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": (
                        "The code ran and produced file(s), but the backend rejected the output during "
                        "validation/quality checks. Fix the code and regenerate the file(s).\n\n"
                        f"Validation failure:\n{last_error}\n\n"
                        "Reply with ONLY the corrected Python code block."
                    ),
                },
            ]
            continue

        last_error = (
            outcome.stderr
            or outcome.stdout
            or "The code ran but wrote no files to ./out."
        ).strip()[:3000]
        convo += [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": (
                    "That failed or produced no files in ./out. Fix it and reply with ONLY the corrected Python.\n\n"
                    f"Error / output:\n{last_error}"
                ),
            },
        ]

    yield {
        "result": {
            "ok": False,
            "error": "I couldn't build a production-quality file after several attempts.",
            "logs": last_error,
        }
    }
