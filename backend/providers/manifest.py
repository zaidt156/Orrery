"""Provider model manifest loader (architecture plan #12).

Pinned model IDs, plan-variant labels, and recommended CLI versions change often. They live in
`model_manifest.json` so they can be updated without editing provider logic. A missing or corrupt
file falls back to the baked-in DEFAULT_MANIFEST below, so the app always has a working catalog.
"""

from __future__ import annotations

import json
import logging

from backend.core.paths import resource_path

log = logging.getLogger("orrery.manifest")

_MANIFEST_PATH = resource_path("backend", "providers", "model_manifest.json")

DEFAULT_MANIFEST: dict = {
    "claude_plan": {
        "recommended_cli_version": [2, 1, 185],
        "variants": [
            ["claude_plan/default", "Claude plan - adaptive thinking", None],
            ["claude_plan/fable", "Claude plan - Fable 5 - adaptive thinking", "claude-fable-5"],
            ["claude_plan/opus", "Claude plan - Opus - adaptive thinking", "claude-opus-4-8"],
            ["claude_plan/sonnet", "Claude plan - Sonnet 5 - adaptive thinking", "claude-sonnet-5"],
            ["claude_plan/haiku", "Claude plan - Haiku - fast", "claude-haiku-4-5"],
        ],
    },
    "chatgpt_plan": {
        "recommended_cli_version": [0, 141, 0],
        "codex_latest_pinned_model": "gpt-5.5",
        "codex_old_fast_model": "gpt-5.4-mini",
        "variants": [
            ["chatgpt_plan/default", "ChatGPT plan - best available (auto) - reasoning", None],
            ["chatgpt_plan/gpt-5.5", "ChatGPT plan - GPT-5.5 - reasoning", "gpt-5.5"],
            ["chatgpt_plan/gpt-5.5-mini", "ChatGPT plan - GPT-5.4 mini - fast reasoning", "gpt-5.4-mini"],
        ],
    },
    "gemini_plan": {
        "variants": [["gemini_plan/default", "Google CLI · default", None]],
    },
}


def load_manifest() -> dict:
    """Baked-in defaults, shallow-merged with model_manifest.json when it loads cleanly."""
    data = {k: dict(v) for k, v in DEFAULT_MANIFEST.items()}
    try:
        if _MANIFEST_PATH.exists():
            loaded = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for key, value in loaded.items():
                    if isinstance(value, dict):
                        data[key] = {**data.get(key, {}), **value}
    except Exception as exc:  # noqa: BLE001 — a bad manifest must not break startup
        log.error("model manifest load failed; using defaults: %s", exc)
    return data


MANIFEST = load_manifest()


def variants(plan: str) -> list[tuple]:
    """Plan variants as (id, label, flag) tuples — flag is None for the auto/default route."""
    return [tuple(v) for v in MANIFEST.get(plan, {}).get("variants", [])]


def recommended_version(plan: str) -> tuple[int, int, int] | None:
    raw = MANIFEST.get(plan, {}).get("recommended_cli_version")
    return tuple(raw) if raw else None


def value(plan: str, key: str, default=None):
    return MANIFEST.get(plan, {}).get(key, default)
