"""Automatic capability routing for Orrery chat turns.

The router is deliberately conservative: it decides which Orrery capability should
handle a request, but it does not grant new powers by itself. Sandbox execution,
file validation, SVG sanitization, provider auth, and persistence still live in
their dedicated feature modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.features import filegen


_CREATE = re.compile(
    r"\b(create|make|generate|build|draw|design|render|produce|compose|export|"
    r"prepare|draft|read|speak|say|narrate|give\s+me|i\s+(?:want|need|would\s+like)|show\s+me)\b",
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
            route="audio",
            label="Audio or voice",
            detail=(
                "Route sound-file creation through the sandbox when a downloadable audio file is requested; "
                "voice playback/transcription settings are a separate provider feature."
            ),
            confidence=0.78,
            skills=("audio", "sandbox"),
            output_mode="audio",
            sandbox_preferred=True,
            unavailable_reason=(
                "Voice playback and transcription providers are not connected yet. "
                "Downloadable WAV sound files are supported through file generation."
            ),
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
