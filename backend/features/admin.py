"""Admin feature flags: an admin can turn Orrery capabilities on/off globally.

The admin sets a token (kept in the OS keychain, never in the DB/logs). Once set, changing the flags
requires that token. Flags live in app config (a single JSON setting). Features check feature_enabled()
to gate themselves, and the UI hides/disables turned-off features. Defaults are all-on so nothing
changes until an admin starts toggling.
"""

from __future__ import annotations

from backend.core import appconfig
from backend.security import secrets

_ADMIN_TOKEN_KEY = "admin_token"   # keychain
_FLAGS_KEY = "feature_flags"       # appconfig

# Toggleable features: name -> (label, default-on)
FEATURES: dict[str, tuple[str, bool]] = {
    "chat_code":    ("Code interpreter (run Python in chat)", True),
    "web_search":   ("Web search", True),
    "deep_research": ("Deep Research", True),
    "ontology":     ("Ontologies as chat context", True),
    "file_gen":     ("File generation", True),
    "media":        ("Media Hub", True),
    "automations":  ("Automations", True),
    "agents":       ("Agents", True),
    "mcp":          ("MCP servers", True),
}


def admin_is_set() -> bool:
    return bool(secrets.get_secret(_ADMIN_TOKEN_KEY))


def verify_admin(token: str) -> bool:
    saved = secrets.get_secret(_ADMIN_TOKEN_KEY)
    return bool(saved) and (token or "") == saved


def set_admin_token(new_token: str, current: str = "") -> bool:
    """Set the admin token (first time), or change it when the current token is supplied."""
    if admin_is_set() and not verify_admin(current):
        return False
    if not (new_token or "").strip():
        return False
    secrets.set_secret(_ADMIN_TOKEN_KEY, new_token.strip())
    return True


async def get_flags() -> dict[str, bool]:
    try:
        stored = await appconfig.get_setting(_FLAGS_KEY, {}) or {}
    except Exception:  # noqa: BLE001 — a flags read failure must never break chat; default all-on
        stored = {}
    return {name: bool(stored.get(name, default)) for name, (_label, default) in FEATURES.items()}


async def feature_enabled(name: str) -> bool:
    """Best-effort gate: if anything goes wrong reading flags, default to enabled (fail-open)."""
    try:
        return (await get_flags()).get(name, True)
    except Exception:  # noqa: BLE001
        return True


async def apply_flags(flags: dict) -> None:
    """Merge + persist flag changes. Caller is responsible for authorization."""
    current = await appconfig.get_setting(_FLAGS_KEY, {}) or {}
    for name in FEATURES:
        if name in flags:
            current[name] = bool(flags[name])
    await appconfig.set_setting(_FLAGS_KEY, current)


async def set_flags(flags: dict, token: str) -> bool:
    if admin_is_set() and not verify_admin(token):
        return False
    await apply_flags(flags)
    return True


async def status() -> dict:
    flags = await get_flags()
    return {
        "admin_set": admin_is_set(),
        "features": [{"name": n, "label": label, "enabled": flags.get(n, True)} for n, (label, _d) in FEATURES.items()],
    }
