"""/system API routes (split from the api.py monolith; same behavior)."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core import database
from backend.core.clipboard import set_clipboard_text
from backend.core.config import settings
from backend.features import app_updates

router = APIRouter()


class ClipboardCopyIn(BaseModel):
    text: str = ""


@router.get("/health")
async def health() -> dict:
    db_ok = await database.check_connection()
    return {"status": "ok", "database": "ok" if db_ok else "error", "dev": settings.orrery_dev}


@router.get("/app/update")
async def app_update() -> dict:
    return await asyncio.to_thread(app_updates.check_for_updates)


@router.post("/clipboard/copy")
async def clipboard_copy(payload: ClipboardCopyIn) -> dict:
    try:
        await asyncio.to_thread(set_clipboard_text, payload.text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Clipboard copy failed: {exc}") from exc
    return {"ok": True}
