"""/dashboards API routes (split from the api.py monolith; same behavior)."""
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from backend.api.deps import _require_conversation_access, _sse, _sse_run
from backend.api.schemas import *  # noqa: F401,F403 — request models
from backend.core import appconfig, database
from backend.core.config import settings
from backend.features import admin, app_updates, artifacts, chat, dashboards, data, datamodels, datasets, evaluate, exports, feedback, filepreview, local_models, mcp, projects, rag, route_telemetry, skills, team, usage
from backend.features import files as file_library
from backend.providers import accounts, ai, catalog
from backend.security import secrets

router = APIRouter()

@router.get("/dashboards")
async def dashboards_list() -> dict:
    return {"dashboards": await dashboards.list_dashboards()}

@router.post("/dashboards")
async def dashboard_create(body: DashboardCreate) -> dict:
    try:
        return await dashboards.create_dashboard(body.model, body.connection_ids, body.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/dashboards/{did}")
async def dashboard_get(did: str) -> dict:
    out = await dashboards.get_dashboard(did)
    if out is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return out

@router.post("/dashboards/{did}/run")
async def dashboard_run(did: str) -> dict:
    out = await dashboards.run_dashboard(did)
    if out is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return out

@router.post("/dashboards/{did}/revise")
async def dashboard_revise(did: str, body: DashboardRevise) -> dict:
    try:
        out = await dashboards.revise_dashboard(did, body.model, body.instruction)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return out

@router.put("/dashboards/{did}/transforms")
async def dashboard_set_transforms(did: str, body: TransformsBody) -> dict:
    try:
        out = await dashboards.set_transforms(did, body.transforms)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return out

@router.put("/dashboards/{did}/layout")
async def dashboard_set_layout(did: str, body: LayoutBody) -> dict:
    try:
        out = await dashboards.set_layout(did, body.order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return out

@router.post("/dashboards/{did}/rollback")
async def dashboard_rollback(did: str) -> dict:
    try:
        out = await dashboards.rollback_dashboard(did)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return out

@router.delete("/dashboards/{did}")
async def dashboard_delete(did: str) -> dict:
    if not await dashboards.delete_dashboard(did):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return {"deleted": True}

# --- document collections (RAG) ---
