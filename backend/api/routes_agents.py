"""Authenticated local API for versioned agent definitions, builder resources, and runs."""

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.features import agent_runs, agents, team

router = APIRouter()


# The schema already reserves these trigger kinds, but no inbound receiver is registered yet.
# Keep them visible to clients without implying that configuring one makes it operational.
AGENT_CONNECTORS = (
    {
        "id": "api",
        "label": "Scoped API",
        "available": False,
        "reason": "The scoped agent API receiver is not implemented yet.",
    },
    {
        "id": "slack",
        "label": "Slack",
        "available": False,
        "reason": "The Slack event receiver is not implemented yet.",
    },
    {
        "id": "gmail",
        "label": "Gmail",
        "available": False,
        "reason": "The Gmail event receiver is not implemented yet.",
    },
)


class AgentRunStart(BaseModel):
    input: str = Field(default="", max_length=100_000)


class ApprovalDecision(BaseModel):
    approve: bool


def _bad_config(exc: agents.AgentConfigError) -> None:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents")
async def agent_list(
    include_archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return await agents.list_agents(
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )


@router.get("/agents/catalog")
async def agent_catalog() -> dict:
    """Builder resources. Deliberately NO live model discovery here — that can probe provider
    CLIs for seconds and used to leave the whole builder empty; the UI reads /models instead."""
    from backend import tools
    from backend.features import dashboards, data, datasets, mcp, projects, rag, skills

    return {
        "skills": await skills.list_user_skills(),
        "builtin_skills": skills.list_builtin(),
        "datasets": await datasets.list_datasets(),
        "ontologies": await rag.list_collections(kind="ontology"),
        "projects": await projects.list_projects(),
        "connections": await data.list_connections(),
        "dashboards": await dashboards.list_dashboards(),
        "mcp_servers": await mcp.list_servers(),
        "tools": tools.list_tools(),
        "connectors": [dict(connector) for connector in AGENT_CONNECTORS],
    }


@router.post("/agents", status_code=status.HTTP_201_CREATED)
async def agent_create(body: agents.AgentConfig) -> dict:
    try:
        return await agents.create_agent(body)
    except agents.AgentConfigError as exc:
        _bad_config(exc)


@router.get("/agents/{agent_id}")
async def agent_get(agent_id: str) -> dict:
    item = await agents.get_agent(agent_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return item


@router.put("/agents/{agent_id}")
async def agent_update(agent_id: str, body: agents.AgentConfig) -> dict:
    try:
        item = await agents.update_agent(agent_id, body)
    except agents.AgentConfigError as exc:
        _bad_config(exc)
    if item is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return item


@router.patch("/agents/{agent_id}/status")
async def agent_status(agent_id: str, body: agents.AgentStatusUpdate) -> dict:
    try:
        item = await agents.set_agent_status(agent_id, body.status)
    except agents.AgentConfigError as exc:
        _bad_config(exc)
    if item is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return item


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def agent_archive(agent_id: str) -> Response:
    item = await agents.set_agent_status(agent_id, "archived")
    if item is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/agents/{agent_id}/runs", status_code=status.HTTP_201_CREATED)
async def agent_run_start(agent_id: str, body: AgentRunStart) -> dict:
    owner = await team.current_owner_id()
    try:
        return await agent_runs.start_run(agent_id, owner_id=owner, input_text=body.input,
                                          trigger_type="manual", principal="local-owner")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/runs")
async def agent_run_list(agent_id: str, limit: int = Query(default=50, ge=1, le=100)) -> dict:
    owner = await team.current_owner_id()
    return {"runs": await agent_runs.list_runs(agent_id, owner_id=owner, limit=limit)}


@router.get("/agent-runs/{run_id}")
async def agent_run_get(run_id: str) -> dict:
    owner = await team.current_owner_id()
    run = await agent_runs.get_run(run_id, owner_id=owner)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/agent-runs/{run_id}/cancel")
async def agent_run_cancel(run_id: str) -> dict:
    owner = await team.current_owner_id()
    if not await agent_runs.cancel_run(run_id, owner_id=owner):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"ok": True}


@router.get("/agent-approvals")
async def agent_approvals() -> dict:
    owner = await team.current_owner_id()
    return {"approvals": await agent_runs.list_pending_approvals(owner_id=owner)}


@router.post("/agent-approvals/{approval_id}/decide")
async def agent_approval_decide(approval_id: str, body: ApprovalDecision) -> dict:
    owner = await team.current_owner_id()
    result = await agent_runs.decide_approval(approval_id, approve=body.approve, owner_id=owner)
    if result is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return result
