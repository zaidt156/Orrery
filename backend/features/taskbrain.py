"""Task Brain — one observable ledger for all background work (OpenClaw-style).

Detached chat generations, queued jobs, and automations each get a row here so the UI can show
what's running, resume it, or cancel it — instead of background work being invisible. The live
run machinery still lives in chat.py; this module is the durable, queryable record of it.

Rows are Postgres-backed (Orrery's primary store). On boot, any 'running' row is orphaned (its
in-process task died with the previous run), so reconcile_orphans() marks those 'interrupted'.
"""

from __future__ import annotations

import datetime
import logging
import uuid

from sqlalchemy import select, update

from backend.core.database import get_sessionmaker
from backend.core.models import Task
from backend.security import secrets

log = logging.getLogger("orrery.taskbrain")

_ACTIVE = ("running", "queued")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def start(kind: str, title: str, conversation_id: str | uuid.UUID | None = None) -> str:
    """Record a unit of background work as 'running' and return its task id."""
    conv = uuid.UUID(str(conversation_id)) if conversation_id else None
    task = Task(kind=kind, title=(title or "Task").strip()[:300] or "Task", status="running", conversation_id=conv)
    async with get_sessionmaker()() as s:
        s.add(task)
        await s.commit()
        return str(task.id)


async def finish(task_id: str | None, status: str = "done", detail: str | None = None) -> None:
    """Mark a task terminal — but never clobber a status the user already set (e.g. canceled)."""
    if not task_id:
        return
    async with get_sessionmaker()() as s:
        row = await s.get(Task, uuid.UUID(task_id))
        if row is None or row.status not in _ACTIVE:
            return
        row.status = status
        row.finished_at = _now()
        if detail:
            row.detail = secrets.redact_secrets(str(detail))[:500]
        await s.commit()


async def cancel(task_id: str) -> bool:
    """Cancel a task from the UI: mark it canceled and stop the live run if it's a chat task."""
    async with get_sessionmaker()() as s:
        row = await s.get(Task, uuid.UUID(task_id))
        if row is None:
            return False
        conv = str(row.conversation_id) if row.conversation_id else None
        kind = row.kind
        if row.status in _ACTIVE:
            row.status = "canceled"
            row.finished_at = _now()
            await s.commit()
    if kind == "chat" and conv:
        from backend.features import chat
        chat.cancel_run(conv)
    return True


def _to_dict(row: Task) -> dict:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "title": row.title,
        "status": row.status,
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


async def recent(limit: int = 50) -> list[dict]:
    """Most-recent tasks (active first by recency), for the Task Brain panel."""
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(select(Task).order_by(Task.created_at.desc()).limit(max(1, min(limit, 200))))
        ).scalars().all()
        return [_to_dict(r) for r in rows]


async def active_count() -> int:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(Task.id).where(Task.status.in_(_ACTIVE)))).all()
        return len(rows)


async def reconcile_orphans() -> int:
    """On boot, a 'running' row's in-process task is gone — mark it 'interrupted'."""
    async with get_sessionmaker()() as s:
        result = await s.execute(
            update(Task).where(Task.status == "running").values(status="interrupted", finished_at=_now())
        )
        await s.commit()
        count = result.rowcount or 0
    if count:
        log.info("reconciled %d orphaned task(s) to interrupted", count)
    return count
