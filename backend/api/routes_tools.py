"""Tool catalog and optional Crabbox executor settings."""
from __future__ import annotations

from fastapi import APIRouter

from backend import tools
from backend.api.deps import _require_admin_access
from backend.features import admin, crabbox

router = APIRouter()


@router.get("/tools")
async def get_tools() -> dict:
    return {
        "tools": tools.list_tools(),
        "features": await admin.effective_flags(),
    }


@router.get("/crabbox/status")
async def get_crabbox_status() -> dict:
    return await crabbox.status()


@router.put("/crabbox/settings")
async def put_crabbox_settings(body: crabbox.CrabboxSettings) -> dict:
    await _require_admin_access()
    settings = await crabbox.save_settings(body.model_dump())
    return {"settings": settings, "status": await crabbox.status()}
