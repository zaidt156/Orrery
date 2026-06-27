"""Safe reasoning panel events.

The UI has a clickable "How this was produced" panel. Rather than dumping the model's verbatim
chain-of-thought (unfinished assumptions, rejected paths, hidden prompt fragments), we CONDENSE the
model's actual reasoning into short, per-step summary lines via ReasoningCondenser — so the steps
reflect the real thinking for THIS request, not predefined topic-agnostic text. Factual trace events
(context loaded, generation path, sandbox run) are emitted alongside. See architecture plan P0 #12.
"""

from __future__ import annotations

import re

_SEG_BREAK = re.compile(r"\n\s*\n+")
_SENT_END = re.compile(r"[.!?](?:\s|$)")
_LEAD_NOISE = re.compile(r"^[\s\-*#>•\d.)]+")


def _clean_line(segment: str) -> str:
    """Condense one chunk of raw reasoning into a single short, readable step line."""
    text = re.sub(r"\s+", " ", segment or "").strip()
    text = _LEAD_NOISE.sub("", text)
    text = re.sub(r"[*_`#]+", "", text)  # drop markdown emphasis
    text = text.strip().rstrip(".")
    if len(text) > 110:
        text = text[:107].rstrip() + "…"
    if text:
        text = text[0].upper() + text[1:]
    return text


class ReasoningCondenser:
    """Streaming condenser: feed raw reasoning deltas, get back short reasoning_event steps that
    summarize the ACTUAL thinking (one line per sentence/paragraph), capped so it stays scannable."""

    def __init__(self, max_steps: int = 8, min_segment_chars: int = 40):
        self._buf = ""
        self._count = 0
        self._max = max_steps
        self._min = min_segment_chars

    def _take(self) -> tuple[str, bool]:
        para = _SEG_BREAK.search(self._buf)
        if para:
            seg, self._buf = self._buf[: para.start()], self._buf[para.end():]
            return seg, True
        # earliest sentence end where the segment is long enough — short lead-in sentences
        # ("Let me think.") merge into the next one instead of blocking emission.
        for sent in _SENT_END.finditer(self._buf):
            if sent.start() + 1 >= self._min:
                seg, self._buf = self._buf[: sent.start() + 1], self._buf[sent.end():]
                return seg, True
        return "", False

    def feed(self, delta: str) -> list[dict]:
        self._buf += delta or ""
        out: list[dict] = []
        while self._count < self._max:
            seg, found = self._take()
            if not found:
                break
            line = _clean_line(seg)
            if len(line) >= 12:
                self._count += 1
                out.append(reasoning_event(line))
        return out

    def finish(self) -> list[dict]:
        """Flush a substantial trailing fragment (the model's last thought) if there's room."""
        if self._count < self._max and len(self._buf.strip()) >= self._min:
            line = _clean_line(self._buf)
            self._buf = ""
            if len(line) >= 12:
                self._count += 1
                return [reasoning_event(line)]
        return []


def reasoning_event(stage: str, detail: str = "") -> dict:
    """One live work-trace step, e.g. ('Preparing context', 'Loaded your documents')."""
    return {
        "reasoning_event": {
            "stage": (stage or "").strip()[:120],
            "detail": (detail or "").strip()[:500],
        }
    }


def reasoning_summary(title: str, items: list[str]) -> dict:
    """A short closing summary of how the answer was produced (max 8 items)."""
    return {
        "reasoning_summary": {
            "title": (title or "").strip()[:120],
            "items": [i.strip()[:500] for i in items if i and i.strip()][:8],
        }
    }
