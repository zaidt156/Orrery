"""Admin feature flags: admins can control Orrery capabilities.

The admin sets a token (kept in the OS keychain, never in the DB/logs). Once set, changing the flags
requires that token in solo mode; team mode authorizes by the current user's admin role. Workspace
defaults and per-team-user overrides live in app config. Features check feature_enabled() to gate
themselves, and the UI hides/disables unavailable features. Defaults are all-on so nothing changes
until an admin starts toggling.
"""

from __future__ import annotations

from backend.core import appconfig
from backend.security import secrets

_ADMIN_TOKEN_KEY = "admin_token"   # keychain
_FLAGS_KEY = "feature_flags"       # appconfig
_USER_FLAGS_KEY = "team_user_feature_flags"  # appconfig: {team_user_id: {feature_name: bool}}

# Toggleable features: name -> (label, default-on)
FEATURES: dict[str, tuple[str, bool]] = {
    "chat_code":    ("Code interpreter (run Python in chat)", True),
    "web_search":   ("Web search", True),
    "deep_research": ("Deep Research", True),
    "ontology":     ("Ontologies as chat context", True),
    "file_gen":     ("File generation", True),
    "dashboards":   ("Dashboards", True),
    "media":        ("Media Hub", True),
    "automations":  ("Automations", True),
    "agents":       ("Agents", True),
    "mcp":          ("MCP servers", True),
    "capability_agent": ("Model-guided tool planner", False),
    "crabbox":      ("Crabbox remote executor", False),
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


def _clean_flags(flags: dict | None) -> dict[str, bool]:
    """Keep only known feature names and normalize values to booleans."""
    raw = flags or {}
    return {name: bool(raw[name]) for name in FEATURES if name in raw}


async def get_user_feature_flags(user_id: str) -> dict[str, bool]:
    try:
        stored = await appconfig.get_setting(_USER_FLAGS_KEY, {}) or {}
    except Exception:  # noqa: BLE001
        stored = {}
    return _clean_flags(stored.get(str(user_id), {}))


async def set_user_feature_flags(user_id: str, flags: dict | None) -> dict[str, bool]:
    """Replace a user's explicit feature overrides. Empty dict resets them to workspace defaults."""
    current = await appconfig.get_setting(_USER_FLAGS_KEY, {}) or {}
    cleaned = _clean_flags(flags)
    uid = str(user_id)
    if cleaned:
        current[uid] = cleaned
    else:
        current.pop(uid, None)
    await appconfig.set_setting(_USER_FLAGS_KEY, current)
    return cleaned


async def clear_user_feature_flags(user_id: str) -> None:
    await set_user_feature_flags(user_id, {})


async def apply_user_feature_flags(users: list[dict]) -> list[dict]:
    """Attach stored per-user feature overrides to user dictionaries returned by team.py."""
    try:
        stored = await appconfig.get_setting(_USER_FLAGS_KEY, {}) or {}
    except Exception:  # noqa: BLE001
        stored = {}
    out: list[dict] = []
    for user in users:
        item = dict(user)
        item["feature_flags"] = _clean_flags(stored.get(str(user.get("id")), {}))
        out.append(item)
    return out


async def effective_flags() -> dict[str, bool]:
    """Feature flags for the current caller.

    Solo mode uses workspace defaults. Team admins also use workspace defaults so they cannot be
    locked out of administration by a member-level override. Team members receive their explicit
    override when present, otherwise the workspace default.
    """
    flags = await get_flags()
    try:
        from backend.features import team

        if not await team.team_mode():
            return flags
        user = await team.current_user()
        if not user:
            return {name: False for name in FEATURES}
        if user.get("role") == "admin":
            return flags
        overrides = await get_user_feature_flags(user["id"])
        return {name: bool(overrides.get(name, flags.get(name, True))) for name in FEATURES}
    except Exception:  # noqa: BLE001 - do not break solo/local chat if the admin layer is unavailable
        return flags


async def feature_enabled(name: str) -> bool:
    """Best-effort gate using the current caller's effective feature flags."""
    try:
        return (await effective_flags()).get(name, True)
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
    effective = await effective_flags()
    return {
        "admin_set": admin_is_set(),
        "features": [
            {
                "name": n,
                "label": label,
                "enabled": flags.get(n, True),
                "effective": effective.get(n, flags.get(n, True)),
            }
            for n, (label, _d) in FEATURES.items()
        ],
    }
