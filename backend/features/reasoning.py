"""Reasoning depth modes (Quick / Standard / Deep / Max).

A user-facing mode is friendlier than raw effort levels and lets one control drive several knobs at
once: provider reasoning effort, file-generation retry budget, and how insistent validation is. The
mode is stored as the conversation's existing `effort` value (no new column), so all the effort
plumbing keeps working unchanged. This module is the single source of truth for the mapping.

    Quick    -> low effort,  fewest retries   (fast, simple Q&A)
    Standard -> auto effort, normal retries    (default; provider's own default depth)
    Deep     -> high effort, more retries       (code / files / data / complex work)
    Max      -> xhigh effort, most retries      (critical work; may cost more)
"""

from __future__ import annotations

# shallow -> deep
MODES = ("quick", "standard", "deep", "max")
DEFAULT_MODE = "standard"

# Standard maps to "" (auto) so the default keeps the provider's own chosen depth (unchanged behaviour).
_MODE_TO_EFFORT = {"quick": "low", "standard": "", "deep": "high", "max": "xhigh"}
# legacy "medium" folds into Standard for display
_EFFORT_TO_MODE = {"": "standard", "low": "quick", "medium": "standard", "high": "deep", "xhigh": "max", "max": "max"}
_LABELS = {"quick": "Quick", "standard": "Standard", "deep": "Deep", "max": "Max"}
_FILE_RETRIES = {"quick": 2, "standard": 3, "deep": 3, "max": 4}


def _normalize(value: str | None) -> str:
    """Accept either a mode name or an effort value and return the canonical mode."""
    val = (value or "").strip().lower()
    if val in MODES:
        return val
    return _EFFORT_TO_MODE.get(val, DEFAULT_MODE)


def mode_to_effort(mode: str | None) -> str:
    """Mode name -> the effort value to store/send. Unknown -> '' (auto)."""
    return _MODE_TO_EFFORT.get((mode or "").strip().lower(), "")


def effort_to_mode(effort: str | None) -> str:
    """Stored effort value -> the mode name to display."""
    return _normalize(effort)


def label(value: str | None) -> str:
    """Human label ('Deep') from a mode name or an effort value."""
    return _LABELS.get(_normalize(value), "Standard")


def file_retries(value: str | None) -> int:
    """How many file-generation repair attempts this depth allows (from a mode or effort value)."""
    return _FILE_RETRIES.get(_normalize(value), 2)
