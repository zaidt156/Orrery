"""/admin-team API routes (split from the api.py monolith; same behavior)."""

from fastapi import APIRouter, HTTPException

from backend.api.deps import _require_admin_access
from backend.api.schemas import *  # noqa: F401,F403 — request models
from backend.features import admin, team

router = APIRouter()

@router.get("/admin")
async def admin_status() -> dict:
    return await admin.status()

@router.post("/admin/token")
async def admin_set_token(body: AdminToken) -> dict:
    if await team.team_mode():
        await _require_admin_access()
    if not admin.set_admin_token(body.token, body.current):
        raise HTTPException(status_code=403, detail="Could not set token (wrong current token, or empty).")
    return {"ok": True}

@router.put("/admin/features")
async def admin_set_features(body: AdminFlags) -> dict:
    # Team mode is role-authorized. Never let the legacy solo-admin token elevate a member.
    if await team.team_mode():
        await _require_admin_access()
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
    await _require_admin_access()
    return {"users": await admin.apply_user_feature_flags(await team.list_users())}

@router.post("/team/users")
async def team_create_user(body: TeamUserBody) -> dict:
    await _require_admin_access()
    return await team.create_user(body.name, body.role)

@router.patch("/team/users/{uid}")
async def team_update_user(uid: str, body: TeamUserUpdate) -> dict:
    await _require_admin_access()
    res = await team.set_user(uid, role=body.role, disabled=body.disabled)
    if not res["ok"]:
        raise HTTPException(status_code=409, detail=res["error"])
    if "feature_flags" in body.model_fields_set:
        await admin.set_user_feature_flags(uid, body.feature_flags)
    return res

@router.delete("/team/users/{uid}")
async def team_delete_user(uid: str) -> dict:
    await _require_admin_access()
    res = await team.delete_user(uid)
    if not res["ok"]:
        raise HTTPException(status_code=409, detail=res["error"])
    await admin.clear_user_feature_flags(uid)
    return res

# --- projects ---
