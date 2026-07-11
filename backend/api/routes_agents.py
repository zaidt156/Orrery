"""Authenticated local API for versioned agent definitions and builder resources."""

from fastapi import APIRouter, HTTPException, Query, Response, status

from backend.features import agents

router = APIRouter()


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
    from backend import tools
    from backend.features import dashboards, data, datasets, mcp, projects, rag, skills
    from backend.providers import ai

    return {
        "models": await ai.list_available_models(),
        "skills": await skills.list_user_skills(),
        "builtin_skills": skills.list_builtin(),
        "datasets": await datasets.list_datasets(),
        "ontologies": await rag.list_collections(kind="ontology"),
        "projects": await projects.list_projects(),
        "connections": await data.list_connections(),
        "dashboards": await dashboards.list_dashboards(),
        "mcp_servers": await mcp.list_servers(),
        "tools": tools.list_tools(),
        "connectors": [
            {"id": "slack", "label": "Slack", "available": True},
            {"id": "gmail", "label": "Gmail", "available": True},
        ],
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
