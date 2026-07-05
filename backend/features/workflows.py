"""Workflow CRUD + run management. Execution itself lives in backend.automation.engine and is
driven by a durable Procrastinate job; per-user ownership follows the chats/projects pattern."""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select

from backend.automation.engine import MAX_NODES, execute_run
from backend.automation.registry import get_node
from backend.core.database import get_sessionmaker
from backend.core.models import Workflow, WorkflowRun, WorkflowRunStep
from backend.features import team

log = logging.getLogger("orrery.workflows")


def _owned_by(row, owner_id: str | None) -> bool:
    return owner_id is None or getattr(row, "owner_id", None) == owner_id


def _dict(w: Workflow) -> dict:
    try:
        spec = json.loads(w.spec or "{}")
    except (ValueError, TypeError):
        spec = {}
    return {
        "id": str(w.id), "name": w.name, "description": w.description or "",
        "spec": spec, "enabled": bool(w.enabled), "schedule": w.schedule or "",
        "node_count": len(spec.get("nodes") or []),
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


def _validate_spec(spec: dict) -> dict:
    nodes = list(spec.get("nodes") or [])
    if len(nodes) > MAX_NODES:
        raise ValueError(f"A workflow can have at most {MAX_NODES} nodes.")
    seen: set[str] = set()
    for n in nodes:
        nid = str(n.get("id") or "")
        if not nid or nid in seen:
            raise ValueError("Every node needs a unique id.")
        seen.add(nid)
        if get_node(str(n.get("type") or "")) is None:
            raise ValueError(f"Unknown node type: {n.get('type')!r}")
    edges = [e for e in (spec.get("edges") or [])
             if e.get("source") in seen and e.get("target") in seen]
    return {"nodes": nodes, "edges": edges}


async def list_workflows() -> list[dict]:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        q = select(Workflow).order_by(Workflow.updated_at.desc())
        if owner is not None:
            q = q.where(Workflow.owner_id == owner)
        rows = (await s.execute(q)).scalars().all()
        return [_dict(r) for r in rows]


async def create_workflow(name: str, description: str = "") -> dict:
    async with get_sessionmaker()() as s:
        row = Workflow(name=(name.strip() or "New workflow")[:160],
                       description=description.strip() or None,
                       spec=json.dumps({"nodes": [], "edges": []}),
                       owner_id=await team.current_owner_id())
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return _dict(row)


async def get_workflow(wid: str) -> dict | None:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        row = await s.get(Workflow, uuid.UUID(wid))
        if row is None or not _owned_by(row, owner):
            return None
        return _dict(row)


async def update_workflow(wid: str, *, name=None, description=None, spec=None,
                          enabled=None, schedule=None) -> dict | None:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        row = await s.get(Workflow, uuid.UUID(wid))
        if row is None or not _owned_by(row, owner):
            return None
        if name is not None:
            row.name = (name.strip() or row.name)[:160]
        if description is not None:
            row.description = description.strip() or None
        if spec is not None:
            cleaned = _validate_spec(spec)
            try:
                history = json.loads(row.history) if row.history else []
            except (ValueError, TypeError):
                history = []
            history.append(json.loads(row.spec or "{}"))
            row.history = json.dumps(history[-10:])  # versioned on save (rollback window)
            row.spec = json.dumps(cleaned)
        if enabled is not None:
            row.enabled = bool(enabled)
        if schedule is not None:
            row.schedule = schedule.strip() or None
        await s.commit()
        await s.refresh(row)
        return _dict(row)


async def delete_workflow(wid: str) -> bool:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        row = await s.get(Workflow, uuid.UUID(wid))
        if row is None or not _owned_by(row, owner):
            return False
        await s.delete(row)
        await s.commit()
        return True


async def start_run(wid: str, trigger: str = "manual") -> dict:
    """Create the durable run row, then defer execution to the Procrastinate worker."""
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        wf = await s.get(Workflow, uuid.UUID(wid))
        if wf is None or not _owned_by(wf, owner):
            raise ValueError("Workflow not found.")
        if not wf.enabled:
            raise ValueError("This workflow is paused — enable it first.")
        run = WorkflowRun(workflow_id=wf.id, trigger=trigger)
        s.add(run)
        await s.commit()
        await s.refresh(run)
        run_id = str(run.id)

    from backend.core.queue import get_queue_app
    try:
        await get_queue_app().configure_task(name="run_workflow").defer_async(run_id=run_id)
    except Exception:  # noqa: BLE001 — queue down (e.g. tests): run inline so manual runs still work
        log.warning("queue defer failed; executing run %s inline", run_id)
        await execute_run(run_id)
    return {"run_id": run_id}


async def list_runs(wid: str, limit: int = 20) -> list[dict]:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        wf = await s.get(Workflow, uuid.UUID(wid))
        if wf is None or not _owned_by(wf, owner):
            return []
        rows = (await s.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
            .order_by(WorkflowRun.created_at.desc()).limit(limit)
        )).scalars().all()
        return [{
            "id": str(r.id), "status": r.status, "trigger": r.trigger, "error": r.error,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        } for r in rows]


async def run_detail(wid: str, run_id: str) -> dict | None:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        wf = await s.get(Workflow, uuid.UUID(wid))
        if wf is None or not _owned_by(wf, owner):
            return None
        run = await s.get(WorkflowRun, uuid.UUID(run_id))
        if run is None or run.workflow_id != wf.id:
            return None
        steps = (await s.execute(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)
            .order_by(WorkflowRunStep.created_at)
        )).scalars().all()
        return {
            "id": str(run.id), "status": run.status, "trigger": run.trigger, "error": run.error,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "steps": [{
                "node_id": st.node_id, "node_type": st.node_type, "status": st.status,
                "input": st.input, "output": st.output, "error": st.error,
                "duration_ms": st.duration_ms,
            } for st in steps],
        }
