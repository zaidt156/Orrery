"""/files API routes (split from the api.py monolith; same behavior)."""
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


@router.get("/file-preview/status")
async def file_preview_status() -> dict:
    return filepreview.office_preview_status()


@router.post("/file-preview/install")
async def install_file_preview(body: PlanConnection) -> dict:
    await _require_admin_access()
    try:
        return await asyncio.to_thread(filepreview.install_office_preview, body.acknowledged)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

@router.get("/conversations/{cid}/messages/{mid}/export/{export_format}")
async def export_reply(cid: str, mid: str, export_format: str) -> Response:
    await _require_conversation_access(cid)
    if export_format not in exports.SUPPORTED_FORMATS:
        raise HTTPException(status_code=404, detail="Unsupported export format")
    try:
        result = await exports.export_message(cid, mid, export_format)
    except exports.ExportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except exports.ExportTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "Cache-Control": "no-store",
        },
    )

@router.get("/conversations/{cid}/messages/{mid}/preview/{export_format}")
async def preview_reply(cid: str, mid: str, export_format: str) -> dict:
    await _require_conversation_access(cid)
    if export_format not in exports.SUPPORTED_FORMATS:
        raise HTTPException(status_code=404, detail="Unsupported export format")
    try:
        result = await exports.preview_message(cid, mid, export_format)
    except exports.ExportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except exports.ExportTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except ValueError as exc:  # malformed/borderline spec — don't 500 the preview
        raise HTTPException(status_code=422, detail=str(exc)[:200]) from None
    content, media = await asyncio.to_thread(
        filepreview.to_preview,
        result.filename,
        result.media_type,
        result.content,
    )
    artifact_id = artifacts.register(content, media)
    return {"url": f"/artifacts/{artifact_id}", "kind": export_format, "mime": media}

@router.get("/files/{file_id}")
async def download_file(file_id: str) -> Response:
    item = file_library.load(file_id)
    if item is None:
        raise HTTPException(status_code=404, detail="File not found or expired")
    meta, data = item
    return Response(
        content=data,
        media_type=meta["mime"],
        headers={
            "Content-Disposition": f'attachment; filename="{meta["name"]}"',
            "Cache-Control": "no-store",
        },
    )

@router.get("/files/{file_id}/preview")
async def preview_file(file_id: str) -> dict:
    item = file_library.load(file_id)
    if item is None:
        raise HTTPException(status_code=404, detail="File not found or expired")
    meta, data = item
    office_file = filepreview.is_office_file(meta["name"])
    cache_path = file_library.office_preview_cache_path(file_id, data) if office_file else None
    content, media = await asyncio.to_thread(
        filepreview.to_preview,
        meta["name"],
        meta["mime"],
        data,
        cache_path=cache_path,
    )
    artifact_id = artifacts.register(content, media)
    rendered_pdf = office_file and b'data-renderer="qt-pdf"' in content
    partial = rendered_pdf and b'data-preview-complete="false"' in content
    faithful = rendered_pdf and not partial
    hint = None
    if partial:
        hint = "The Office preview is partial because the safe page or byte limit was reached."
    elif office_file and not faithful:
        hint = "LibreOffice is unavailable or conversion failed; showing the HTML fallback."
    return {
        "url": f"/artifacts/{artifact_id}",
        "mime": media,
        "renderer": (
            "libreoffice"
            if faithful
            else "libreoffice-partial"
            if partial
            else "html-fallback"
            if office_file
            else "native"
        ),
        "hint": hint,
    }

@router.post("/artifacts")
async def create_artifact(body: NewArtifact) -> dict:
    try:
        artifact_id = artifacts.register(body.html)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"id": artifact_id, "url": f"/artifacts/{artifact_id}"}
