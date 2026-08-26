"""The durable record of everything Orrery Work changed in an attached folder.

ADR-007 gave up diff-then-apply — the user chose direct writes. What Orrery owes back is an account
of what actually changed that does not depend on the model's description of its own work. This
module is that account.

**The row is opened before the bytes move.** That ordering is the entire guarantee, and it is the
same one ADR-005 already applies to tool dispatch. A mutation with no row is invisible forever:
nothing knows to look for it. A row with no mutation is self-evident — it still reads `started`, and
`digest_before` shows the file was never touched. Given a choice between those two failures, only
one of them is recoverable.

Ownership is enforced by resolving the root through `workspace_roots`, which already answers
"someone else's" and "no such thing" identically. Nothing here re-implements that check.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import WorkspaceWrite
from backend.features import team, workspace_roots

DEFAULT_HISTORY = 50
MAX_HISTORY = 500
MAX_ERROR_CHARS = 500


def _row(entry: WorkspaceWrite) -> dict:
    return {
        "id": str(entry.id),
        "root_id": str(entry.root_id),
        "path": entry.path,
        "action": entry.action,
        "status": entry.status,
        "digest_before": entry.digest_before,
        "digest_after": entry.digest_after,
        "bytes_after": entry.bytes_after,
        "error": entry.error,
        "at": entry.created_at.isoformat() if entry.created_at else None,
    }


async def begin(root_id: str, change: dict) -> str:
    """Open the record for a change that is about to be attempted. Returns its id.

    Called before the file is touched. `root_path` is what enforces ownership — a root the caller
    does not own raises `UnknownRoot` here, before anything has happened.
    """
    await workspace_roots.root_path(root_id)
    async with get_sessionmaker()() as s:
        entry = WorkspaceWrite(
            root_id=uuid.UUID(str(root_id)),
            path=str(change.get("path") or ""),
            action=str(change.get("action") or "modified"),
            status="started",
            digest_before=change.get("digest_before"),
        )
        s.add(entry)
        await s.commit()
        return str(entry.id)


async def finish(entry_id: str, change: dict) -> None:
    """Complete the record for a change that landed."""
    await _close(entry_id, status="done", digest_after=change.get("digest_after"),
                 bytes_after=int(change.get("bytes_after") or 0))


async def fail(entry_id: str, reason: str) -> None:
    """Complete the record for a change that did not land.

    The row is kept rather than deleted: an attempt that failed is not the same as one that never
    happened, and an attempt to overwrite a file is worth knowing about either way.

    The reason is scrubbed on the way in. An error string is arbitrary text from wherever it came
    from, and security.md §9 is explicit that a log must not become the place a secret persists.
    """
    from backend.security.secrets import redact_secrets

    await _close(entry_id, status="failed", error=redact_secrets(str(reason))[:MAX_ERROR_CHARS])


async def history(root_id: str, limit: int = DEFAULT_HISTORY) -> list[dict]:
    """What changed in this folder, newest first."""
    await workspace_roots.root_path(root_id)
    capped = max(1, min(int(limit), MAX_HISTORY))
    async with get_sessionmaker()() as s:
        rows = (await s.execute(
            select(WorkspaceWrite)
            .where(WorkspaceWrite.root_id == uuid.UUID(str(root_id)))
            .order_by(WorkspaceWrite.created_at.desc(), WorkspaceWrite.id.desc())
            .limit(capped)
        )).scalars().all()
        return [_row(r) for r in rows]


async def _close(entry_id: str, *, status: str, digest_after: str | None = None,
                 bytes_after: int = 0, error: str | None = None) -> None:
    async with get_sessionmaker()() as s:
        entry = await s.get(WorkspaceWrite, uuid.UUID(str(entry_id)))
        if entry is None:
            return  # the root was detached mid-write; there is nothing left to complete
        entry.status = status
        entry.digest_after = digest_after
        entry.bytes_after = bytes_after
        entry.error = error
        entry.completed_at = datetime.datetime.now(datetime.timezone.utc)
        await s.commit()


__all__ = ["begin", "fail", "finish", "history", "team"]
