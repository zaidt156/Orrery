"""/models API routes (split from the api.py monolith; same behavior)."""

from fastapi import APIRouter, HTTPException

from backend.api.deps import _require_admin_access
from backend.api.schemas import *  # noqa: F401,F403 — request models
from backend.providers import ai, catalog

router = APIRouter()

@router.get("/models")
async def models() -> dict:
    items = await ai.list_available_models()
    for m in items:  # so the context selector only offers sizes the model actually has
        m["context_window"] = ai.model_context_window(m["id"])
    return {"models": items}

@router.get("/models/catalog")
async def models_catalog() -> dict:
    return {"models": await ai.list_catalog()}

@router.post("/models/active")
async def models_active(body: SetActive) -> dict:
    await _require_admin_access()
    await catalog.set_active(body.id, body.label, body.provider, body.active)
    return {"id": body.id, "active": body.active}

@router.post("/custom-models")
async def custom_add(body: NewCustomModel) -> dict:
    await _require_admin_access()
    if not body.base_url.strip() or not body.model.strip():
        raise HTTPException(status_code=400, detail="Base URL and model id are required")
    try:  # validation + SSRF guard raise ValueError/UnsafeUrlError → surface as a clean 400
        return await catalog.add_custom_model(
            body.label.strip() or body.model.strip(), body.base_url.strip(), body.model.strip(), body.key
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

@router.delete("/custom-models/{cid}")
async def custom_delete(cid: str) -> dict:
    await _require_admin_access()
    if not await catalog.delete_custom_model(cid):
        raise HTTPException(status_code=404, detail="Custom model not found")
    return {"deleted": True}
