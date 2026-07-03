"""/conversations API routes (split from the api.py monolith; same behavior)."""
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

@router.get("/conversations")
async def conversations() -> dict:
    return {"conversations": await chat.list_conversations()}

@router.post("/conversations")
async def new_conversation(body: NewConversation) -> dict:
    try:
        return await chat.create_conversation(
            body.model, body.system_prompt, body.effort, body.context_window, body.project_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

@router.get("/conversations/{cid}")
async def conversation(cid: str) -> dict:
    conv = await chat.get_conversation(cid)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv["running"] = chat.is_running(cid)  # so the UI can re-attach to a background run
    return conv

@router.patch("/conversations/{cid}")
async def patch_conversation(cid: str, body: UpdateConversation) -> dict:
    provided = body.model_dump(exclude_unset=True)
    try:
        conv = await chat.update_conversation(cid, **provided)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversation or project not found") from None
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv

@router.delete("/conversations/{cid}")
async def remove_conversation(cid: str) -> dict:
    if not await chat.delete_conversation(cid):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}

@router.post("/conversations/{cid}/messages")
async def send_message(cid: str, body: NewMessage) -> StreamingResponse:
    await _require_conversation_access(cid)
    attachments = [a.model_dump() for a in body.attachments]
    return _sse_run(cid, chat.stream_reply(cid, body.content, attachments, body.collection_id))

@router.get("/conversations/{cid}/attachment-text")
async def conversation_attachment_text(cid: str, source: str) -> dict:
    text_content = await chat.attachment_text(cid, source)
    if text_content is None:
        raise HTTPException(status_code=404, detail="No stored text for that attachment.")
    return {"source": source, "text": text_content}

@router.post("/conversations/{cid}/messages/{mid}/reasoning")
async def save_message_reasoning(cid: str, mid: str, body: ReasoningBody) -> dict:
    return {"saved": await chat.save_reasoning(cid, mid, body.reasoning)}

# --- answer evaluation: regenerate with other models, judge anonymously, pick the best ---
@router.post("/conversations/{cid}/messages/{mid}/evaluate")
async def evaluate_message(cid: str, mid: str, body: EvaluateBody) -> dict:
    try:
        return await evaluate.evaluate(cid, mid, body.models, body.judge)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — provider errors are already sanitized
        raise HTTPException(status_code=502, detail=str(e)[:300])

@router.post("/conversations/{cid}/messages/{mid}/adopt")
async def adopt_message(cid: str, mid: str, body: AdoptBody) -> dict:
    if not await evaluate.adopt(cid, mid, body.text, body.model):
        raise HTTPException(status_code=404, detail="Message not found")
    return {"adopted": True}

@router.post("/conversations/{cid}/code-image")
async def generate_code_image(cid: str, body: NewMessage) -> StreamingResponse:
    await _require_conversation_access(cid)
    if body.attachments:
        raise HTTPException(status_code=400, detail="Code-rendered images do not accept attachments yet")
    return _sse_run(cid, chat.stream_code_image(cid, body.content))

@router.post("/conversations/{cid}/regenerate")
async def regenerate_message(cid: str) -> StreamingResponse:
    await _require_conversation_access(cid)
    return _sse_run(cid, chat.regenerate(cid))

@router.post("/conversations/{cid}/stop")
async def stop_generation(cid: str) -> dict:
    await _require_conversation_access(cid)
    chat.cancel_run(cid)
    return {"stopped": True}

@router.get("/conversations/{cid}/resume")
async def resume_generation(cid: str) -> StreamingResponse:
    # Re-attach to a generation that's still running in the background (client navigated away).
    await _require_conversation_access(cid)
    return _sse(chat.resume(cid))

@router.get("/tasks")
async def list_tasks() -> dict:
    from backend.features import taskbrain
    return {"tasks": await taskbrain.recent(50)}

@router.get("/task-routes")
async def task_routes() -> dict:
    return await route_telemetry.summary()

@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict:
    from backend.features import taskbrain
    return {"canceled": await taskbrain.cancel(task_id)}

