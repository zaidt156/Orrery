"""Automatic capability routing for Orrery chat turns.

The router is deliberately conservative: it decides which Orrery capability should
handle a request, but it does not grant new powers by itself. Sandbox execution,
file validation, SVG sanitization, provider auth, and persistence still live in
their dedicated feature modules.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from backend.features import filegen

log = logging.getLogger("orrery.taskrouter")


_CREATE = re.compile(
    r"\b(create|make|generate|build|draw|design|render|produce|compose|export|"
    r"prepare|draft|write|read|speak|say|narrate|give\s+me|i\s+(?:want|need|would\s+like)|show\s+me)\b",
    re.IGNORECASE,
)
_VISUAL_NOUN = re.compile(
    r"\b(image|illustration|diagram|poster|icon|logo|visual|infographic|"
    r"graphic|vector|svg|banner|thumbnail|cover art)\b",
    re.IGNORECASE,
)
_FILE_ONLY_VISUAL = re.compile(r"\b(pdf|docx?|word|xlsx?|excel|pptx?|powerpoint|csv|zip)\b", re.IGNORECASE)
_AUDIO_NOUN = re.compile(
    r"\b(audio|sound|soundtrack|sound effect|sfx|voice|voiceover|voice-over|"
    r"narration|text[-\s]?to[-\s]?speech|tts|speech|out loud|aloud|wav|mp3)\b",
    re.IGNORECASE,
)
_PROJECT_NOUN = re.compile(r"\b(project|workspace|client space|case file|folder)\b", re.IGNORECASE)
_PROJECT_ACTION = re.compile(
    r"\b(start|create|make|set up|organize|open|switch|save this as|add this to|"
    r"move this to|project context)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskPlan:
    route: str
    label: str
    detail: str
    confidence: float
    skills: tuple[str, ...] = field(default_factory=tuple)
    output_mode: str = "chat"
    sandbox_required: bool = False
    sandbox_preferred: bool = False
    unavailable_reason: str | None = None

    @property
    def uses_sandbox(self) -> bool:
        return self.sandbox_required or self.sandbox_preferred


def _looks_like_standalone_image_request(text: str) -> bool:
    """Image requests that should produce an SVG artifact, not a PDF/deck/etc."""
    if not text:
        return False
    if filegen.wants_file(text) and _FILE_ONLY_VISUAL.search(text):
        return False
    return bool(_CREATE.search(text) and _VISUAL_NOUN.search(text))


def _looks_like_project_request(text: str) -> bool:
    return bool(_PROJECT_NOUN.search(text or "") and _PROJECT_ACTION.search(text or ""))


def _looks_like_audio_request(text: str) -> bool:
    return bool(_CREATE.search(text or "") and _AUDIO_NOUN.search(text or ""))


def plan(user_text: str, *, has_attachments: bool = False) -> TaskPlan:
    """Return the first-pass capability plan for a user turn.

    Ordering matters: file requests outrank standalone image/audio requests when
    the user asks for a concrete downloadable format, because the file generator
    has the validation and preview contract for those artifacts.
    """
    text = (user_text or "").strip()

    if filegen.wants_file(text):
        needs_sandbox = filegen.needs_code(text)
        return TaskPlan(
            route="file",
            label="File generation",
            detail=(
                "Create a requested artifact, validate the output, and return only the requested files."
                if needs_sandbox
                else "Create the requested document through the deterministic document builder."
            ),
            confidence=0.92,
            skills=("document", "spreadsheet", "powerpoint", "sandbox"),
            output_mode="file",
            sandbox_preferred=needs_sandbox,
        )

    if _looks_like_standalone_image_request(text):
        return TaskPlan(
            route="image",
            label="Code-rendered image",
            detail="Generate a sanitized SVG artifact from the visual brief.",
            confidence=0.86,
            skills=("image",),
            output_mode="artifact",
        )

    if _looks_like_audio_request(text):
        return TaskPlan(
            route="file",
            label="Audio artifact",
            detail="Create a downloadable audio artifact through the sandbox and validate the output.",
            confidence=0.78,
            skills=("audio", "sandbox"),
            output_mode="file",
            sandbox_preferred=True,
        )

    if _looks_like_project_request(text):
        return TaskPlan(
            route="project",
            label="Project workspace",
            detail="Use or create a durable project context for related chats, files, and instructions.",
            confidence=0.72,
            skills=("project",),
            output_mode="chat",
        )

    return _chat_plan(has_attachments)


def _chat_plan(has_attachments: bool = False) -> TaskPlan:
    return TaskPlan(
        route="chat",
        label="Chat",
        detail=(
            "Answer in the chat stream using loaded skills, attachments, and conversation context."
            + (" Attachments are included in the context." if has_attachments else "")
        ),
        confidence=0.55,
        skills=("core",),
        output_mode="chat",
    )


# ── model-backed decider ───────────────────────────────────────────────────────
# The regex heuristic above is fast but blind to context — it mis-fired a WAV for a calculation
# typed after a song turn. Before an EXPENSIVE/IRREVERSIBLE generative action, we ask the model to
# confirm the route by reading the ACTUAL current message. Plain chat (the safe default) never
# calls the model; any failure falls back to the heuristic, so a turn is never blocked or broken.

# Heuristic routes worth confirming: audio maps to route="file" already, so "file" covers it.
_GENERATIVE_ROUTES = {"file", "image", "project"}
_DECIDER_ROUTES = {"chat", "file", "image", "audio", "project"}

_DECIDER_PROMPT = """You are the intent router for a local AI workspace. Decide how to handle the \
user's CURRENT message. Earlier turns are BACKGROUND ONLY — classify what the user is asking for \
RIGHT NOW, not what an earlier message asked for.

Reply with STRICT JSON only, no prose:
{{"route": "chat|file|image|audio|project", "format": "pdf|docx|pptx|xlsx|csv|html|wav|mp3|svg|null", "reason": "<=8 words"}}

Rules:
- "chat": answer directly in text. Questions, CALCULATIONS, math, explanations, code shown in the
  reply, conversation, opinions, "what/why/how" — anything NOT explicitly asking to PRODUCE a
  downloadable file, picture, or audio in THIS message. A calculation or a new question after an
  earlier file/song request is ALWAYS "chat".
- "file": the user explicitly wants a downloadable document/spreadsheet/deck/data file this turn.
- "image": the user explicitly wants a generated picture/diagram/logo/illustration this turn.
- "audio": the user explicitly wants generated audio/speech/a song/voice file this turn.
- "project": the user explicitly wants to create or organize a project workspace.
When unsure, choose "chat".

{context}Current user message:
\"\"\"{message}\"\"\"
"""


def _recent_context(recent_messages: list[dict] | None) -> str:
    if not recent_messages:
        return ""
    lines = []
    for m in recent_messages[-4:]:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        text = content.strip().replace("\n", " ")
        if text:
            lines.append(f"{role}: {text[:200]}")
    return ("Recent turns (background only):\n" + "\n".join(lines) + "\n\n") if lines else ""


def _parse_decision(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    route = str(data.get("route") or "").strip().lower()
    if route not in _DECIDER_ROUTES:
        return None
    fmt = data.get("format")
    return {"route": route, "format": str(fmt).lower() if fmt and fmt != "null" else None}


def _plan_for_decision(route: str, fmt: str | None, heuristic: TaskPlan, has_attachments: bool) -> TaskPlan:
    if route == "chat":
        return _chat_plan(has_attachments)
    if route == "audio":
        return TaskPlan(
            route="file", label="Audio artifact",
            detail="Create a downloadable audio artifact through the sandbox and validate the output.",
            confidence=0.9, skills=("audio", "sandbox"), output_mode="file", sandbox_preferred=True,
        )
    if route == "image":
        return TaskPlan(
            route="image", label="Code-rendered image",
            detail="Generate a sanitized SVG artifact from the visual brief.",
            confidence=0.9, skills=("image",), output_mode="artifact",
        )
    if route == "project":
        return TaskPlan(
            route="project", label="Project workspace",
            detail="Use or create a durable project context for related chats, files, and instructions.",
            confidence=0.85, skills=("project",), output_mode="chat",
        )
    # route == "file": keep the heuristic's file plan if it had one (carries sandbox_preferred), else
    # build one; a computed/charted format wants the sandbox.
    if heuristic.route == "file":
        return heuristic
    needs_sandbox = bool(fmt and fmt in {"html", "wav", "mp3", "svg"})
    return TaskPlan(
        route="file", label="File generation",
        detail="Create the requested artifact, validate the output, and return only the requested files.",
        confidence=0.9, skills=("document", "spreadsheet", "powerpoint", "sandbox"),
        output_mode="file", sandbox_preferred=needs_sandbox,
    )


async def _model_decision(user_text: str, model: str, recent_messages: list[dict] | None) -> dict | None:
    """Ask the model to classify the CURRENT turn. Returns None on any failure (→ heuristic)."""
    from backend.providers import ai

    prompt = _DECIDER_PROMPT.format(
        context=_recent_context(recent_messages), message=(user_text or "").strip()[:2000]
    )
    chunks: list[str] = []
    try:
        async for delta in ai.stream_chat(
            model, [{"role": "user", "content": prompt}],
            "You are a precise intent classifier. Output only the requested JSON.", effort="",
        ):
            if isinstance(delta, ai.ReasoningDelta):
                continue
            chunks.append(str(delta))
            if sum(len(c) for c in chunks) > 600:  # a decision is tiny; stop early
                break
    except Exception:  # noqa: BLE001 — limit/offline/malformed → trust the heuristic, never break
        log.debug("intent decider model call failed", exc_info=True)
        return None
    return _parse_decision("".join(chunks))


async def decide(
    heuristic_text: str,
    *,
    current_message: str | None = None,
    model: str,
    recent_messages: list[dict] | None = None,
    has_attachments: bool = False,
) -> TaskPlan:
    """Heuristic first (instant, on heuristic_text which may inherit a prior 'do it' intent); before
    a generative action, confirm with the model judging the TRUE current message against context.
    Falls back to the heuristic on any model failure, so a turn is never blocked."""
    heuristic = plan(heuristic_text, has_attachments=has_attachments)
    from backend.core.config import settings

    if heuristic.route not in _GENERATIVE_ROUTES or not settings.model_intent_decider or not model:
        return heuristic
    judged = current_message if current_message is not None else heuristic_text
    decision = await _model_decision(judged, model, recent_messages)
    if decision is None:
        return heuristic
    return _plan_for_decision(decision["route"], decision.get("format"), heuristic, has_attachments)
