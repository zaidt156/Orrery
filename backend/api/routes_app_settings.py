"""/app-settings API routes (split from the api.py monolith; same behavior)."""
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from backend.api.deps import _require_admin_access, _require_conversation_access, _sse, _sse_run
from backend.api.schemas import *  # noqa: F401,F403 — request models
from backend.core import appconfig, database
from backend.core.config import settings
from backend.features import admin, app_updates, artifacts, chat, dashboards, data, datamodels, datasets, evaluate, exports, feedback, filepreview, local_models, mcp, projects, rag, route_telemetry, skills, team, usage
from backend.features import files as file_library
from backend.providers import accounts, ai, catalog
from backend.security import secrets

router = APIRouter()

@router.get("/branding")
async def get_branding() -> dict:
    saved = await appconfig.get_setting("branding", Branding().model_dump())
    try:
        return Branding.model_validate(saved).model_dump()
    except (TypeError, ValueError):
        return Branding().model_dump()

@router.put("/branding")
async def put_branding(body: Branding) -> dict:
    await _require_admin_access()
    return await appconfig.set_setting("branding", body.model_dump())

@router.get("/defaults")
async def get_defaults() -> dict:
    saved = await appconfig.get_setting("defaults", {}) or {}
    return {"model": str(saved.get("model", "")), "effort": str(saved.get("effort", ""))}

@router.put("/defaults")
async def put_defaults(body: DefaultsBody) -> dict:
    await _require_admin_access()
    effort = body.effort if body.effort in ("", "low", "high", "xhigh") else ""
    return await appconfig.set_setting("defaults", {"model": body.model.strip(), "effort": effort})

@router.get("/privacy")
async def get_privacy() -> dict:
    mode = await appconfig.get_setting("privacy_mode", "basic") or "basic"
    if mode not in ("off", "basic", "strict"):
        mode = "basic"
    return {"mode": mode}

@router.put("/privacy")
async def put_privacy(body: PrivacyMode) -> dict:
    await _require_admin_access()
    await appconfig.set_setting("privacy_mode", body.mode)
    return {"mode": body.mode}

@router.get("/database")
async def get_database() -> dict:
    await _require_admin_access()
    info = database.connection_info()
    info["status"] = "ok" if info["configured"] and await database.check_connection(force=True) else "error"
    return info

@router.delete("/database")
async def clear_database() -> dict:
    await _require_admin_access()
    await database.clear_database_url_and_reset()
    return {"ok": True, "restart_required": False}

@router.post("/database/test")
async def test_database(body: DbConnection) -> dict:
    await _require_admin_access()
    ok, error = await database.test_url(body.url)
    return {"ok": ok, "error": error}

@router.put("/database")
async def set_database(body: DbConnection) -> dict:
    await _require_admin_access()
    ok, error = await database.test_url(body.url)
    if not ok:
        return {"ok": False, "error": error}
    await database.save_database_url_and_reset(body.url)
    return {"ok": True, "restart_required": False}

@router.get("/usage")
async def get_usage() -> dict:
    return await usage.summary()

@router.put("/usage/cap")
async def put_usage_cap(body: SpendCap) -> dict:
    await _require_admin_access()
    await usage.set_cap(body.enabled, body.limit_usd, body.period)
    return await usage.summary()

@router.post("/feedback")
async def post_feedback(body: NewFeedback) -> dict:
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Feedback message is empty")
    return await feedback.submit(body.category, body.message, body.contact, body.context)

@router.get("/feedback")
async def list_feedback() -> dict:
    return {"feedback": await feedback.recent()}
