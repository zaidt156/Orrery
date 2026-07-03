"""/system API routes (split from the api.py monolith; same behavior)."""
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

@router.get("/health")
async def health() -> dict:
    db_ok = await database.check_connection()
    return {"status": "ok", "database": "ok" if db_ok else "error", "dev": settings.orrery_dev}

@router.get("/app/update")
async def app_update() -> dict:
    return await asyncio.to_thread(app_updates.check_for_updates)
