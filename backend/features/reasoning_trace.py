"""Safe two-layer reasoning / work-trace events for Orrery.

The UI shows two layers, like a high-end AI workspace:
1. An outer/collapsed reasoning card ("Architected the document path …").
2. An inner/expanded step timeline (route → context → tool → validation → done).

This module NEVER exposes raw model chain-of-thought, provider reasoning deltas, hidden prompts, or
inline <think>…</think> content. Every visible line is backend-authored public narration of what
Orrery actually did: route choice, context loading, tool actions, sandbox runs, validation, status.
That is what makes the trace identical across every model and connection — API, CLI, or local — since
it describes Orrery's work, not the model's private deliberation.

Compatibility:
- reasoning_event(...) still exists for older call sites and now emits BOTH the legacy
  `reasoning_event` key and the new `type: reasoning_step` / `reasoning_step` payload.
- ThinkStream strips inline <think>…</think> and counts hidden reasoning for diagnostics only; it
  returns no visible events (the old condenser behaviour is intentionally gone — see the safety rule).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
_MAX_TAG = max(len(_THINK_OPEN), len(_THINK_CLOSE))

MAX_TITLE = 160
MAX_DETAIL = 900
MAX_METADATA_VALUE = 300
MAX_SUMMARY_ITEMS = 8

_ALLOWED_STATUS = {"queued", "running", "done", "warning", "error"}
_ALLOWED_LEVEL = {"info", "success", "warning", "error"}


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _clip(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split()).strip()
    if len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _safe_status(value: str | None, default: str = "running") -> str:
    value = (value or default).strip().lower()
    return value if value in _ALLOWED_STATUS else default


def _safe_level(value: str | None, default: str = "info") -> str:
    value = (value or default).strip().lower()
    return value if value in _ALLOWED_LEVEL else default


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Keep metadata small, simple, and UI-safe.

    Only non-sensitive operational data belongs here: route, confidence, output mode, selected
    skills, sandbox policy, validation status, generated file count. Never prompts, document text,
    generated code, raw provider errors, or secrets.
    """
    if not metadata:
        return {}
    safe: dict[str, Any] = {}
    for raw_key, raw_value in metadata.items():
        key = _clip(raw_key, 80)
        if not key or raw_value is None:
            continue
        if isinstance(raw_value, bool | int | float):
            safe[key] = raw_value
        elif isinstance(raw_value, str):
            safe[key] = _clip(raw_value, MAX_METADATA_VALUE)
        elif isinstance(raw_value, tuple | list):
            safe[key] = [_clip(item, 120) for item in raw_value[:12]]
        else:
            safe[key] = _clip(repr(raw_value), MAX_METADATA_VALUE)
    return safe


def reasoning_outer(
    title: str,
    summary: str = "",
    *,
    status: str = "running",
    phase: str = "plan",
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Outer collapsed reasoning card shown around the answer."""
    return {
        "type": "reasoning_outer",
        "reasoning_outer": {
            "id": _id(),
            "title": _clip(title, MAX_TITLE),
            "summary": _clip(summary, MAX_DETAIL),
            "status": _safe_status(status),
            "phase": _clip(phase, 40) or "plan",
            "ts": time.time(),
            "metadata": _safe_metadata(metadata),
        },
    }


def reasoning_step(
    stage: str,
    detail: str = "",
    *,
    kind: str = "work",
    status: str = "running",
    phase: str = "work",
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Inner expanded timeline row. kind: work|tool|file|script|validation|result|safety|route|context."""
    return {
        "type": "reasoning_step",
        "reasoning_step": {
            "id": _id(),
            "stage": _clip(stage, MAX_TITLE),
            "detail": _clip(detail, MAX_DETAIL),
            "kind": _clip(kind, 40) or "work",
            "status": _safe_status(status),
            "phase": _clip(phase, 40) or "work",
            "level": _safe_level(level),
            "ts": time.time(),
            "metadata": _safe_metadata(metadata),
        },
    }


def reasoning_event(
    stage: str,
    detail: str = "",
    *,
    kind: str = "work",
    status: str = "running",
    phase: str = "work",
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Backward-compatible public work-trace event (emits both the legacy and new payloads)."""
    event = reasoning_step(stage, detail, kind=kind, status=status, phase=phase, level=level, metadata=metadata)
    step = event["reasoning_step"]
    event["reasoning_event"] = {"stage": step["stage"], "detail": step["detail"]}
    return event


def reasoning_summary(title: str, items: list[str]) -> dict:
    """Final compact summary for the reasoning panel (max 8 items)."""
    return {
        "type": "reasoning_summary",
        "reasoning_summary": {
            "title": _clip(title or "How this was produced", MAX_TITLE),
            "items": [_clip(item, 500) for item in items if item and item.strip()][:MAX_SUMMARY_ITEMS],
        },
    }


@dataclass
class TraceItem:
    stage: str
    detail: str = ""
    kind: str = "work"
    status: str = "running"
    phase: str = "work"
    level: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)


class ReasoningTrace:
    """Collects a safe public timeline for one request.

    - outer(...) creates the collapsed top-level activity card;
    - step(...) creates the expanded timeline rows;
    - done(...) adds the final checkmark row;
    - summary() returns a compact closing summary.

    Never add raw model reasoning to this trace.
    """

    def __init__(self, *, max_steps: int = 30):
        self.max_steps = max_steps
        self.outer_events: list[tuple[str, str, str]] = []
        self.steps: list[TraceItem] = []

    def outer(
        self,
        title: str,
        summary: str = "",
        *,
        status: str = "running",
        phase: str = "plan",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        self.outer_events.append((_clip(title, MAX_TITLE), _clip(summary, MAX_DETAIL), _safe_status(status)))
        return reasoning_outer(title, summary, status=status, phase=phase, metadata=metadata)

    def step(
        self,
        stage: str,
        detail: str = "",
        *,
        kind: str = "work",
        status: str = "running",
        phase: str = "work",
        level: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        item = TraceItem(
            stage=_clip(stage, MAX_TITLE),
            detail=_clip(detail, MAX_DETAIL),
            kind=_clip(kind, 40) or "work",
            status=_safe_status(status),
            phase=_clip(phase, 40) or "work",
            level=_safe_level(level),
            metadata=_safe_metadata(metadata),
        )
        if len(self.steps) < self.max_steps:
            self.steps.append(item)
        return reasoning_step(
            item.stage, item.detail, kind=item.kind, status=item.status,
            phase=item.phase, level=item.level, metadata=item.metadata,
        )

    def done(self, detail: str = "Completed the request.") -> dict:
        return self.step("Done", detail, kind="result", status="done", phase="final", level="success")

    def warning(self, stage: str, detail: str = "", **metadata: Any) -> dict:
        return self.step(stage, detail, kind="warning", status="warning", phase="warning", level="warning", metadata=metadata)

    def error(self, stage: str, detail: str = "", **metadata: Any) -> dict:
        return self.step(stage, detail, kind="error", status="error", phase="error", level="error", metadata=metadata)

    def summary(self, title: str = "How this was produced") -> dict:
        items: list[str] = []
        for outer_title, outer_summary, _status in self.outer_events[:3]:
            items.append(f"{outer_title}: {outer_summary}" if outer_summary else outer_title)
        if not items:
            for step in self.steps[:MAX_SUMMARY_ITEMS]:
                items.append(f"{step.stage}: {step.detail}" if step.detail else step.stage)
        return reasoning_summary(title, items)


@dataclass
class HiddenReasoningStats:
    """Operational stats only. Never store or display raw reasoning text."""

    chunks: int = 0
    chars: int = 0
    inline_think_blocks: int = 0

    @property
    def seen(self) -> bool:
        return self.chunks > 0 or self.inline_think_blocks > 0


class ThinkStream:
    """Remove inline <think>…</think> from a streaming answer; count hidden reasoning for diagnostics.

    Provider reasoning deltas and inline thinking are counted only — never condensed, emitted,
    displayed, or stored. Visible reasoning is produced by ReasoningTrace / reasoning_event(...) from
    backend-authored route/tool/validation steps. (`max_steps` is accepted for back-compat and ignored.)
    """

    def __init__(self, max_steps: int | None = None):
        self._buf = ""
        self._in_think = False
        self.stats = HiddenReasoningStats()

    @staticmethod
    def _find_tag(buffer: str, tag: str) -> int:
        return buffer.lower().find(tag)

    def feed_reasoning(self, text: str) -> list[dict]:
        """Stream the model's raw reasoning from a separate provider channel (reasoning_content/thinking)."""
        if not text:
            return []
        self.stats.chunks += 1
        self.stats.chars += len(text)
        return [{"reasoning_delta": text}]

    def feed(self, delta: str) -> tuple[str, list[dict]]:
        """Return (answer_text_to_emit, reasoning_events). Inline <think> content is streamed as raw reasoning."""
        self._buf += delta or ""
        answer: list[str] = []
        reasoning: list[str] = []
        while self._buf:
            if self._in_think:
                end = self._find_tag(self._buf, _THINK_CLOSE)
                if end == -1:
                    cut = len(self._buf) - (_MAX_TAG - 1)
                    if cut > 0:
                        reasoning.append(self._buf[:cut])
                        self.stats.chunks += 1
                        self.stats.chars += cut
                        self._buf = self._buf[cut:]
                    break
                hidden = self._buf[:end]
                if hidden:
                    reasoning.append(hidden)
                    self.stats.chunks += 1
                    self.stats.chars += len(hidden)
                self._buf = self._buf[end + len(_THINK_CLOSE):]
                self._in_think = False
                self.stats.inline_think_blocks += 1
                continue
            start = self._find_tag(self._buf, _THINK_OPEN)
            if start == -1:
                cut = len(self._buf) - (_MAX_TAG - 1)
                if cut > 0:
                    answer.append(self._buf[:cut])
                    self._buf = self._buf[cut:]
                break
            if start > 0:
                answer.append(self._buf[:start])
            self._buf = self._buf[start + len(_THINK_OPEN):]
            self._in_think = True
        revents = [{"reasoning_delta": "".join(reasoning)}] if reasoning else []
        return "".join(answer), revents

    def finish(self) -> tuple[str, list[dict]]:
        """Flush remaining answer text, or the tail of an unterminated reasoning block."""
        answer = ""
        reasoning: list[str] = []
        if self._in_think:
            if self._buf:
                reasoning.append(self._buf)
                self.stats.chunks += 1
                self.stats.chars += len(self._buf)
            self.stats.inline_think_blocks += 1
        else:
            answer = self._buf
        self._buf = ""
        self._in_think = False
        revents = [{"reasoning_delta": "".join(reasoning)}] if reasoning else []
        return answer, revents


def hidden_reasoning_notice(stats: HiddenReasoningStats) -> dict | None:
    """Optional safe UI notice that hidden reasoning was removed (no raw text)."""
    if not stats.seen:
        return None
    return reasoning_step(
        "Protected private reasoning",
        "Removed hidden model reasoning from the visible answer stream.",
        kind="safety", status="done", phase="safety", level="info",
        metadata={"chunks": stats.chunks, "chars": stats.chars, "inline_think_blocks": stats.inline_think_blocks},
    )
