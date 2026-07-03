"""/local-models API routes (split from the api.py monolith; same behavior)."""
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

@router.get("/local-models")
async def local_model_status() -> dict:
    return await local_models.status()

@router.post("/local-models/install")
async def install_local_runtime(body: PlanConnection) -> dict:
    try:
        await asyncio.to_thread(local_models.install, body.acknowledged)
        return await local_models.status()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

@router.post("/local-models/start")
async def start_local_runtime() -> dict:
    try:
        return await local_models.start()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

@router.post("/local-models/pull")
async def pull_local_model(body: LocalModelAction) -> StreamingResponse:
    return _sse(local_models.pull(body.model))

@router.post("/local-models/active")
async def activate_local_model(body: LocalModelAction) -> dict:
    if body.active is None:
        raise HTTPException(status_code=400, detail="Active state is required")
    try:
        return await local_models.set_active(body.model, body.active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

@router.post("/local-models/remove")
async def remove_local_model(body: LocalModelAction) -> dict:
    try:
        return await local_models.remove(body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

# --- data connections (read-only) ---
