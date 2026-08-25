"""Attaching, remembering and resolving the folder Orrery Work operates in.

This module owns the *identity* of a root — which folder, whose, and which one is current.
`workspace.py` owns the *boundary* — what may be reached once a root is known. Keeping them apart
matters: the boundary is security-critical and has no business talking to a database, and this file
should never be tempted to do path arithmetic of its own (ADR-007).

Two decisions are recorded here rather than left implicit:

**Roots persist.** Attaching a folder is deliberate, and making the user redo it every launch is how
people end up attaching something broader than they meant, just to stop being asked.

**A root is private to its owner.** In team mode one member's project folder is not another's to
read, and the ownership check is a filter on every query rather than a check at the edge.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, update

from backend.core.database import get_sessionmaker
from backend.core.models import WorkspaceRoot
from backend.features import team, workspace

MAX_LABEL = 200


class UnknownRoot(LookupError):
    """No such root, or it belongs to someone else — deliberately the same answer either way."""


def _row(root: WorkspaceRoot) -> dict:
    return {
        "id": str(root.id),
        "path": root.path,
        "label": root.label or _default_label(root.path),
        "active": bool(root.active),
        "created_at": root.created_at.isoformat() if root.created_at else None,
    }


def _default_label(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or path


async def attach(path: str, label: str = "") -> dict:
    """Attach a folder and make it the current root. Re-attaching a known folder just reactivates it.

    The folder is vetted by `workspace.check_attachable` first, so `UnattachableRoot` — the whole
    disk, a home directory, a system path — surfaces before anything is written down.
    """
    resolved = str(workspace.check_attachable(path))
    owner = await team.current_owner_id()
    clean_label = " ".join((label or "").split())[:MAX_LABEL] or _default_label(resolved)

    async with get_sessionmaker()() as s:
        existing = (await s.execute(
            select(WorkspaceRoot).where(
                WorkspaceRoot.path == resolved,
                *((WorkspaceRoot.owner_id == owner,) if owner is not None else ()),
            )
        )).scalar_one_or_none()

        await _deactivate_others(s, owner)
        if existing is not None:
            existing.active = True
            existing.label = clean_label
            root = existing
        else:
            root = WorkspaceRoot(path=resolved, label=clean_label, owner_id=owner, active=True)
            s.add(root)
        await s.commit()
        await s.refresh(root)
        return _row(root)


async def detach(root_id: str) -> dict:
    """Forget a root. The folder itself is untouched — this is Orrery letting go of it, nothing more."""
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        root = await _owned(s, root_id, owner)
        await s.delete(root)
        await s.commit()
    return {"id": str(root_id), "detached": True}


async def activate(root_id: str) -> dict:
    """Switch which remembered folder is the current one."""
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        root = await _owned(s, root_id, owner)
        await _deactivate_others(s, owner)
        root.active = True
        await s.commit()
        await s.refresh(root)
        return _row(root)


async def list_roots() -> list[dict]:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        query = select(WorkspaceRoot).order_by(WorkspaceRoot.last_used_at.desc())
        if owner is not None:
            query = query.where(WorkspaceRoot.owner_id == owner)
        return [_row(r) for r in (await s.execute(query)).scalars().all()]


async def active_root() -> dict | None:
    """The folder Orrery Work is currently pointed at, or None when nothing is attached."""
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        query = select(WorkspaceRoot).where(WorkspaceRoot.active.is_(True))
        if owner is not None:
            query = query.where(WorkspaceRoot.owner_id == owner)
        root = (await s.execute(query.limit(1))).scalar_one_or_none()
        return _row(root) if root else None


async def root_path(root_id: str | None = None) -> str:
    """The folder a tool should work in: the one named, or the active one.

    Every workspace tool starts here, so a tool can never be handed a path that skipped ownership.
    """
    if root_id:
        owner = await team.current_owner_id()
        async with get_sessionmaker()() as s:
            return (await _owned(s, root_id, owner)).path
    current = await active_root()
    if current is None:
        raise UnknownRoot(
            "No folder is attached yet. Attach the folder you want worked on in Orrery Work."
        )
    return current["path"]


async def _owned(s, root_id: str, owner: str | None) -> WorkspaceRoot:
    """Fetch a root the caller actually owns.

    A root belonging to someone else raises the *same* error as one that doesn't exist. Telling the
    two apart would let a member confirm which folders their colleagues have attached.
    """
    try:
        key = uuid.UUID(str(root_id))
    except (ValueError, AttributeError, TypeError):
        raise UnknownRoot("That folder is not attached.") from None
    root = await s.get(WorkspaceRoot, key)
    if root is None or (owner is not None and root.owner_id != owner):
        raise UnknownRoot("That folder is not attached.")
    return root


async def _deactivate_others(s, owner: str | None) -> None:
    stmt = update(WorkspaceRoot).where(WorkspaceRoot.active.is_(True)).values(active=False)
    if owner is not None:
        stmt = stmt.where(WorkspaceRoot.owner_id == owner)
    await s.execute(stmt)
