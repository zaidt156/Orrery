"""/projects API routes (split from the api.py monolith; same behavior)."""
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

@router.get("/projects")
async def projects_list() -> dict:
    return {"projects": await projects.list_projects()}

@router.post("/projects")
async def projects_create(body: ProjectBody) -> dict:
    return await projects.create_project(body.name, body.description, body.instructions)

@router.get("/projects/{pid}")
async def projects_get(pid: str) -> dict:
    try:
        project = await projects.get_project(pid)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.patch("/projects/{pid}")
async def projects_update(pid: str, body: ProjectBody) -> dict:
    try:
        project = await projects.update_project(
            pid,
            name=body.name,
            description=body.description,
            instructions=body.instructions,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.delete("/projects/{pid}")
async def projects_delete(pid: str) -> dict:
    try:
        deleted = await projects.delete_project(pid)
    except ValueError:
        deleted = False
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": True}

@router.get("/projects/{pid}/files")
async def projects_files_list(pid: str) -> dict:
    try:
        return {"files": await projects.list_files(pid)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None

@router.post("/projects/{pid}/files")
async def projects_files_add(pid: str, body: UploadDocs) -> dict:
    files = [a.model_dump() for a in body.files]
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    try:
        return await projects.add_files(pid, files)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None

@router.delete("/projects/{pid}/files")
async def projects_files_delete(pid: str, source: str) -> dict:
    try:
        return {"deleted": await projects.delete_file(pid, source)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None

@router.post("/projects/{pid}/conversations/{cid}")
async def projects_attach_conversation(pid: str, cid: str) -> dict:
    try:
        conv = await projects.set_conversation_project(cid, pid)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project or conversation not found") from None
    if conv is None:
        raise HTTPException(status_code=404, detail="Project or conversation not found")
    return conv

@router.delete("/conversations/{cid}/project")
async def conversation_clear_project(cid: str) -> dict:
    try:
        conv = await projects.set_conversation_project(cid, None)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversation not found") from None
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv

# --- conversations ---
