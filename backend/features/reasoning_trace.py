"""Safe reasoning panel events.

The UI has a clickable "How this was produced" panel. We deliberately DO NOT send raw
model reasoning to it (it can contain unfinished assumptions, rejected paths, hidden prompt
fragments, and provider-specific internals). Instead the backend emits its own safe, factual
trace of the steps it actually took, plus a short summary. See architecture plan P0 #12.
"""

from __future__ import annotations


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
