"""Team identity & access control: access keys, roles, and the founding-admin bootstrap.

Orrery is single-user by default. When several people share one database (the shared-DB team model),
this layer identifies who is driving each client and what they're allowed to do:

  - The founding admin enables team access from the Admin tab; they become the first admin and get an
    access key (shown once).
  - That admin issues a key per teammate, each carrying a role (admin | member).
  - A client unlocks by entering its key once; the key is kept in the OS keychain so it isn't retyped.
  - With team mode on, a client with no valid stored key is "locked".

Security (security.md §1): the access key is a high-entropy secret; only its sha256 hash is stored in
the DB — never the plaintext, never logged. The *role* lives in the DB row, not in the key, so a key
cannot be forged into admin. The unlock key for this machine lives in the OS keychain.
"""
from __future__ import annotations

import contextvars
import hashlib
import secrets as pysecrets
import uuid

from sqlalchemy import func, select, update

from backend.core.database import get_sessionmaker
from backend.core.models import Conversation, Project, TeamUser
from backend.security import secrets

_UNLOCK_KEY = "team_access_key"  # keychain entry: this client's own access key

# Synthetic identity used when team mode is OFF (plain single-user Orrery): full local privileges.
SOLO_USER = {"id": "solo", "name": "You", "role": "admin", "team_mode": False}


def _hash_key(key: str) -> str:
    return hashlib.sha256((key or "").strip().encode("utf-8")).hexdigest()


def generate_key() -> str:
    """A fresh high-entropy access key (shown once to its recipient)."""
    return pysecrets.token_urlsafe(24)


def _dict(u: TeamUser) -> dict:
    return {
        "id": str(u.id), "name": u.name, "role": u.role, "disabled": bool(u.disabled),
        "created_at": u.created_at.isoformat() if u.created_at else None, "team_mode": True,
    }


# Per-REQUEST memo for team_mode/current_user (they're called 4–6× per turn, each a query or a
# keychain read). A fresh dict is set by the API auth dependency, so it can never go stale across
# requests — and code with NO cache set (queue jobs, boot) always queries fresh. This is the safe
# version of the memo Step 117 deliberately deferred (a timed cache could mask a just-enabled
# team mode and fail open).
_request_cache: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "orrery_team_request_cache", default=None
)


def begin_request_cache() -> None:
    """Called by the API auth dependency at the start of every authenticated request."""
    _request_cache.set({})


def _invalidate_request_cache() -> None:
    """Team-state mutators call this so THEIR OWN request re-reads fresh state afterwards."""
    cache = _request_cache.get()
    if cache is not None:
        cache.clear()


async def team_mode() -> bool:
    """True once a team has been set up (at least one user row exists)."""
    cache = _request_cache.get()
    if cache is not None and "team_mode" in cache:
        return cache["team_mode"]
    try:
        async with get_sessionmaker()() as s:
            result = bool((await s.execute(select(func.count(TeamUser.id)))).scalar_one())
    except Exception:  # noqa: BLE001 — no DB / not migrated yet → treat as solo (single-user)
        result = False
    if cache is not None:
        cache["team_mode"] = result
    return result


async def _active_admins(session) -> int:
    return (await session.execute(
        select(func.count(TeamUser.id)).where(TeamUser.role == "admin", TeamUser.disabled.is_(False))
    )).scalar_one()


async def _authenticate(key: str) -> dict | None:
    if not (key or "").strip():
        return None
    async with get_sessionmaker()() as s:
        row = (await s.execute(
            select(TeamUser).where(TeamUser.key_hash == _hash_key(key), TeamUser.disabled.is_(False))
        )).scalar_one_or_none()
        return _dict(row) if row else None


async def current_user() -> dict | None:
    """Who this client is acting as: SOLO_USER when team mode is off; None when locked."""
    cache = _request_cache.get()
    if cache is not None and "user" in cache:
        return cache["user"]
    if not await team_mode():
        user = SOLO_USER
    else:
        user = await _authenticate(secrets.get_secret(_UNLOCK_KEY) or "")
    if cache is not None:
        cache["user"] = user
    return user


async def is_admin() -> bool:
    user = await current_user()
    return bool(user and user["role"] == "admin")


async def current_owner_id() -> str | None:
    """Owner id to stamp/filter private data.

    Solo mode returns None because there is no per-user owner filter. Team mode must return a real
    TeamUser id; a locked/revoked client is not equivalent to solo mode and must fail closed.
    """
    if not await team_mode():
        return None
    user = await current_user()
    if not user:
        raise PermissionError("Team access key required.")
    return user["id"]


async def owner_scope() -> tuple[bool, str | None]:
    """Non-raising owner scope for callers that need to distinguish solo/team/locked.

    - (False, None) = single-user mode, no filtering (show all).
    - (True, "<id>") = team mode, show only this user's rows.
    - (True, None)  = team mode but the client is unidentified (locked / revoked key).
    """
    if not await team_mode():
        return (False, None)
    user = await current_user()
    return (True, user["id"] if user else None)


async def creation_status() -> str:
    """New member-authored skills/MCP need admin approval in team mode; admins (and solo) auto-approve."""
    if not await team_mode():
        return "approved"
    return "approved" if await is_admin() else "pending"


async def status() -> dict:
    """What the UI needs to decide: locked screen, member view, or admin view."""
    if not await team_mode():
        return {"team_mode": False, "locked": False, "user": SOLO_USER}
    user = await current_user()
    return {"team_mode": True, "locked": user is None, "user": user}


async def setup_team(admin_name: str) -> dict:
    """Found the team: create the first admin, unlock this client, return the key once. No-op if set up."""
    if await team_mode():
        return {"ok": False, "error": "Team access is already set up."}
    key = generate_key()
    async with get_sessionmaker()() as s:
        row = TeamUser(name=(admin_name.strip() or "Admin")[:120], role="admin", key_hash=_hash_key(key))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        # The founder's existing single-user chats/projects become theirs (so new members don't see them).
        admin_id = str(row.id)
        await s.execute(update(Conversation).where(Conversation.owner_id.is_(None)).values(owner_id=admin_id))
        await s.execute(update(Project).where(Project.owner_id.is_(None)).values(owner_id=admin_id))
        await s.commit()
    secrets.set_secret(_UNLOCK_KEY, key)  # the founder's client is now unlocked
    _invalidate_request_cache()
    return {"ok": True, "key": key}


async def unlock(key: str) -> dict:
    """Validate a key and remember it locally so this client stays unlocked."""
    user = await _authenticate(key)
    if not user:
        return {"ok": False, "error": "That key is not valid, or it has been revoked."}
    secrets.set_secret(_UNLOCK_KEY, (key or "").strip())
    _invalidate_request_cache()
    return {"ok": True, "user": user}


def sign_out() -> None:
    secrets.delete_secret(_UNLOCK_KEY)
    _invalidate_request_cache()


async def list_users() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(TeamUser).order_by(TeamUser.created_at))).scalars().all()
        return [_dict(r) for r in rows]


async def create_user(name: str, role: str = "member") -> dict:
    """Admin issues a key for a teammate; the key is returned once and never stored in plaintext."""
    role = "admin" if role == "admin" else "member"
    key = generate_key()
    async with get_sessionmaker()() as s:
        row = TeamUser(name=(name.strip() or "Teammate")[:120], role=role, key_hash=_hash_key(key))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        out = _dict(row)
    out["key"] = key
    return out


async def set_user(user_id: str, *, role: str | None = None, disabled: bool | None = None) -> dict:
    """Change a user's role or revoke/restore them. Refuses to remove the last active admin."""
    async with get_sessionmaker()() as s:
        row = await s.get(TeamUser, uuid.UUID(user_id))
        if row is None:
            return {"ok": False, "error": "User not found"}
        demoting = role == "member" and row.role == "admin"
        disabling = disabled is True and not row.disabled
        if (demoting or disabling) and row.role == "admin" and await _active_admins(s) <= 1:
            return {"ok": False, "error": "This is the last admin — promote or add another admin first."}
        if role in ("admin", "member"):
            row.role = role
        if disabled is not None:
            row.disabled = bool(disabled)
        await s.commit()
        _invalidate_request_cache()
        return {"ok": True}


async def delete_user(user_id: str) -> dict:
    async with get_sessionmaker()() as s:
        row = await s.get(TeamUser, uuid.UUID(user_id))
        if row is None:
            return {"ok": False, "error": "User not found"}
        if row.role == "admin" and not row.disabled and await _active_admins(s) <= 1:
            return {"ok": False, "error": "This is the last admin — promote or add another admin first."}
        await s.delete(row)
        await s.commit()
        _invalidate_request_cache()
        return {"ok": True}
