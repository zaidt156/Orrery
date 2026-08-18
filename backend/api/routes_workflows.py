"""Authenticated local API for Automations: workflow definitions, their runs, and the node catalog.

The engine (`backend.automation`) and the CRUD layer (`backend.features.workflows`) already existed;
this is the surface that was missing, which is why the Automations screen had nothing real to talk
to and rendered a hard-coded node list.

Ownership is enforced inside `features.workflows` against `team.current_owner_id()`, so a workflow
belonging to someone else is reported as absent rather than forbidden - the same shape the rest of
the API uses, and it does not confirm that an id exists.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.automation.registry import list_nodes
from backend.features import workflows

router = APIRouter()


def _known_id(wid: str) -> bool:
    """A malformed id is 'not found', not a 500.

    The CRUD layer parses ids with `uuid.UUID(...)`, which raises on anything that is not one.
    Checking here keeps that failure separate from the ValueError that spec validation raises,
    which has to reach the client as a 400 with its message intact.
    """
    try:
        uuid.UUID(wid)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


class NewWorkflow(BaseModel):
    name: str = Field(default="New workflow", max_length=160)
    description: str = Field(default="", max_length=2000)


class WorkflowPatch(BaseModel):
    """Every field optional: the canvas saves a spec, the list toggles enabled, and they are
    separate requests."""

    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    spec: dict | None = None
    enabled: bool | None = None
    schedule: str | None = Field(default=None, max_length=120)


@router.get("/workflow-nodes")
async def workflow_nodes() -> dict:
    """The registered node catalog, with each node's JSON schema.

    The canvas builds its palette and its per-node settings form from this, so adding a node class
    to `backend/automation/nodes.py` is enough to make it appear - no second list in the UI.
    """
    return {"nodes": list_nodes()}


@router.get("/workflows")
async def workflow_list() -> dict:
    return {"workflows": await workflows.list_workflows()}


@router.post("/workflows", status_code=status.HTTP_201_CREATED)
async def workflow_create(body: NewWorkflow) -> dict:
    return await workflows.create_workflow(body.name, body.description)


@router.get("/workflows/{wid}")
async def workflow_get(wid: str) -> dict:
    found = await workflows.get_workflow(wid) if _known_id(wid) else None
    if found is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return found


@router.patch("/workflows/{wid}")
async def workflow_update(wid: str, body: WorkflowPatch) -> dict:
    if not _known_id(wid):
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        updated = await workflows.update_workflow(
            wid, name=body.name, description=body.description, spec=body.spec,
            enabled=body.enabled, schedule=body.schedule,
        )
    except ValueError as exc:  # unknown node type, duplicate id, too many nodes
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if updated is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return updated


@router.delete("/workflows/{wid}", status_code=status.HTTP_204_NO_CONTENT)
async def workflow_delete(wid: str) -> Response:
    if not _known_id(wid) or not await workflows.delete_workflow(wid):
        raise HTTPException(status_code=404, detail="Workflow not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workflows/{wid}/runs", status_code=status.HTTP_201_CREATED)
async def workflow_run_start(wid: str) -> dict:
    if not _known_id(wid):
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        started = await workflows.start_run(wid, trigger="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if started is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return started


@router.get("/workflows/{wid}/runs")
async def workflow_run_list(wid: str, limit: int = Query(default=20, ge=1, le=100)) -> dict:
    if not _known_id(wid):
        return {"runs": []}
    return {"runs": await workflows.list_runs(wid, limit=limit)}


@router.get("/workflows/{wid}/runs/{run_id}")
async def workflow_run_detail(wid: str, run_id: str) -> dict:
    """One run with its durable per-node steps: input, output, and error for each."""
    known = _known_id(wid) and _known_id(run_id)
    detail = await workflows.run_detail(wid, run_id) if known else None
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail

