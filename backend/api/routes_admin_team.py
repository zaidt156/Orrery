"""/admin-team API routes (split from the api.py monolith; same behavior)."""
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

@router.get("/admin")
async def admin_status() -> dict:
    return await admin.status()

@router.post("/admin/token")
async def admin_set_token(body: AdminToken) -> dict:
    if not admin.set_admin_token(body.token, body.current):
        raise HTTPException(status_code=403, detail="Could not set token (wrong current token, or empty).")
    return {"ok": True}

@router.put("/admin/features")
async def admin_set_features(body: AdminFlags) -> dict:
    # In team mode an admin *user* is authorized by their role; otherwise fall back to the token.
    if await team.is_admin():
        await admin.apply_flags(body.flags)
    elif not await admin.set_flags(body.flags, body.token):
        raise HTTPException(status_code=403, detail="Admin token required to change features.")
    return await admin.status()

# --- team access: identity, keys, roles (shared-database multi-user) ---
@router.get("/team")
async def team_status() -> dict:
    return await team.status()

@router.post("/team/setup")
async def team_setup(body: TeamSetup) -> dict:
    res = await team.setup_team(body.name)
    if not res["ok"]:
        raise HTTPException(status_code=409, detail=res["error"])
    return res

@router.post("/team/unlock")
async def team_unlock(body: TeamUnlock) -> dict:
    res = await team.unlock(body.key)
    if not res["ok"]:
        raise HTTPException(status_code=403, detail=res["error"])
    return res

@router.post("/team/signout")
async def team_signout() -> dict:
    team.sign_out()
    return {"ok": True}

@router.get("/team/users")
async def team_users() -> dict:
    if not await team.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required.")
    return {"users": await team.list_users()}

@router.post("/team/users")
async def team_create_user(body: TeamUserBody) -> dict:
    if not await team.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required.")
    return await team.create_user(body.name, body.role)

@router.patch("/team/users/{uid}")
async def team_update_user(uid: str, body: TeamUserUpdate) -> dict:
    if not await team.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required.")
    res = await team.set_user(uid, role=body.role, disabled=body.disabled)
    if not res["ok"]:
        raise HTTPException(status_code=409, detail=res["error"])
    return res

@router.delete("/team/users/{uid}")
async def team_delete_user(uid: str) -> dict:
    if not await team.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required.")
    res = await team.delete_user(uid)
    if not res["ok"]:
        raise HTTPException(status_code=409, detail=res["error"])
    return res

# --- projects ---
