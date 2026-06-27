from __future__ import annotations

import json
import pathlib
import asyncio
import hmac
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.core import appconfig, database
from backend.core.config import settings
from backend.core.observability import new_request_id
from backend.features import artifacts, chat, data, exports, feedback, filepreview, local_models, projects, rag, route_telemetry, usage
from backend.features import files as file_library
from backend.providers import accounts, ai, catalog
from backend.security import secrets

_UI_DIST = pathlib.Path(__file__).resolve().parent.parent / "ui" / "dist"


class _FreshHtmlStatic(StaticFiles):
    """Serve the SPA but never let the webview cache index.html — content-hashed assets
    can cache forever, but a stale index.html would point at old JS and silently run an old build."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

_PLACEHOLDER = """<!doctype html><html><head><meta charset="utf-8">
<title>Orrery</title></head><body style="font-family:sans-serif;background:#0b1020;
color:#e8ecf5;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><h1>🪐 Orrery</h1>
<p>Backend is running. Build the UI (<code>cd ui &amp;&amp; npm run build</code>)
or set <code>ORRERY_DEV=1</code> for the dev server.</p></div>
</body></html>"""


class NewConversation(BaseModel):
    model: str
    system_prompt: str | None = None
    effort: str | None = None
    context_window: Literal[131072, 262144, 1000000] = 1000000
    project_id: str | None = None


class UpdateConversation(BaseModel):
    model: str | None = None
    system_prompt: str | None = None
    effort: str | None = None
    context_window: Literal[131072, 262144, 1000000] | None = None
    project_id: str | None = None


class Attachment(BaseModel):
    name: str
    mime: str = ""
    kind: str  # image | text | pdf
    content: str  # data URL (image) or file text


class NewMessage(BaseModel):
    content: str
    attachments: list[Attachment] = []
    collection_id: str | None = None


class ProviderKey(BaseModel):
    key: str


class PlanConnection(BaseModel):
    acknowledged: bool = False


class SetActive(BaseModel):
    id: str
    label: str = ""
    provider: str = ""
    active: bool


class LocalModelAction(BaseModel):
    model: str
    active: bool | None = None


class NewCustomModel(BaseModel):
    label: str
    base_url: str
    model: str
    key: str = ""


class Branding(BaseModel):
    enabled: bool = False
    name: str = Field(default="", max_length=80)
    tagline: str = Field(default="", max_length=160)
    details: str = Field(default="", max_length=280)
    logo: str = Field(default="", max_length=1_500_000)

    @field_validator("logo")
    @classmethod
    def validate_logo(cls, value: str) -> str:
        if not value:
            return ""
        allowed = (
            "data:image/png;base64,",
            "data:image/jpeg;base64,",
            "data:image/webp;base64,",
            "data:image/gif;base64,",
        )
        if not value.startswith(allowed):
            raise ValueError("Logo must be an uploaded PNG, JPEG, WebP, or GIF image")
        return value


class SpendCap(BaseModel):
    enabled: bool = False
    limit_usd: float = Field(default=10.0, ge=0)
    period: Literal["hour", "day", "month", "all"] = "month"


class NewFeedback(BaseModel):
    category: Literal["bug", "idea", "praise", "general"] = "general"
    message: str
    contact: str = ""
    context: str = ""


class ProjectBody(BaseModel):
    name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=8000)


class NewConnection(BaseModel):
    name: str = ""
    url: str


class NewCollection(BaseModel):
    name: str = ""


class UploadDocs(BaseModel):
    files: list[Attachment] = []


class NewArtifact(BaseModel):
    html: str


class DbConnection(BaseModel):
    url: str


class PrivacyMode(BaseModel):
    mode: Literal["off", "basic", "strict"]


_MAX_BODY_BYTES = settings.max_upload_bytes  # request body cap (configurable; blocks runaway payloads)
_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'self'; frame-ancestors 'none'"
)


def create_app(session_token: str) -> FastAPI:
    """Build the FastAPI application bound to this session's auth token."""
    api = FastAPI(title="Orrery", docs_url=None, redoc_url=None, openapi_url=None)

    @api.middleware("http")
    async def _harden(request, call_next):
        length = request.headers.get("content-length")
        if length is not None:
            try:
                too_big = int(length) > _MAX_BODY_BYTES
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
            if too_big:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        # sandboxed HTML artifacts set their own headers (must be framable + run their own JS)
        if request.url.path.startswith("/artifacts/"):
            return response
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers.setdefault("Content-Security-Policy", _CSP)
        return response

    if settings.orrery_dev:
        # dev UI runs on a different origin (Vite)
        api.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.vite_url],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition"],
        )

    async def require_token(x_orrery_token: str | None = Header(default=None)) -> None:
        # constant-time compare so the token can't be guessed via response timing
        if not x_orrery_token or not hmac.compare_digest(x_orrery_token, session_token):
            raise HTTPException(status_code=401, detail="Invalid session token")
        new_request_id()  # tag this request so all its log lines share one [id]

    r = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    def _sse(source) -> StreamingResponse:
        async def event_stream():
            async for event in source:
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def _sse_run(conv_id: str, source) -> StreamingResponse:
        """Stream a conversation generation that keeps running on the backend even if the
        client disconnects (navigates away), so the reply always completes and is saved."""
        queue = chat.start_detached(conv_id, source)
        return _sse(chat.observe(queue))

    @r.get("/health")
    async def health() -> dict:
        db_ok = await database.check_connection()
        return {"status": "ok", "database": "ok" if db_ok else "error", "dev": settings.orrery_dev}

    async def _activate_provider(provider: str) -> None:
        """Turn on a provider's curated models when it's first configured (best-effort)."""
        try:
            models = await ai.provider_models(provider)
            await catalog.activate_many(
                [{"id": m["id"], "label": m["label"], "provider": m["provider"]} for m in models]
            )
        except Exception:  # noqa: BLE001 — activation is a convenience, never blocks key save
            pass

    # --- models & providers ---
    @r.get("/models")
    async def models() -> dict:
        return {"models": await ai.list_available_models()}

    @r.get("/models/catalog")
    async def models_catalog() -> dict:
        return {"models": await ai.list_catalog()}

    @r.post("/models/active")
    async def models_active(body: SetActive) -> dict:
        await catalog.set_active(body.id, body.label, body.provider, body.active)
        return {"id": body.id, "active": body.active}

    @r.post("/custom-models")
    async def custom_add(body: NewCustomModel) -> dict:
        if not body.base_url.strip() or not body.model.strip():
            raise HTTPException(status_code=400, detail="Base URL and model id are required")
        try:  # validation + SSRF guard raise ValueError/UnsafeUrlError → surface as a clean 400
            return await catalog.add_custom_model(
                body.label.strip() or body.model.strip(), body.base_url.strip(), body.model.strip(), body.key
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @r.delete("/custom-models/{cid}")
    async def custom_delete(cid: str) -> dict:
        if not await catalog.delete_custom_model(cid):
            raise HTTPException(status_code=404, detail="Custom model not found")
        return {"deleted": True}

    @r.get("/branding")
    async def get_branding() -> dict:
        saved = await appconfig.get_setting("branding", Branding().model_dump())
        try:
            return Branding.model_validate(saved).model_dump()
        except (TypeError, ValueError):
            return Branding().model_dump()

    @r.put("/branding")
    async def put_branding(body: Branding) -> dict:
        return await appconfig.set_setting("branding", body.model_dump())

    @r.get("/privacy")
    async def get_privacy() -> dict:
        mode = await appconfig.get_setting("privacy_mode", "basic") or "basic"
        if mode not in ("off", "basic", "strict"):
            mode = "basic"
        return {"mode": mode}

    @r.put("/privacy")
    async def put_privacy(body: PrivacyMode) -> dict:
        await appconfig.set_setting("privacy_mode", body.mode)
        return {"mode": body.mode}

    @r.get("/database")
    async def get_database() -> dict:
        info = database.connection_info()
        info["status"] = "ok" if info["configured"] and await database.check_connection(force=True) else "error"
        return info

    @r.delete("/database")
    async def clear_database() -> dict:
        await database.clear_database_url_and_reset()
        return {"ok": True, "restart_required": False}

    @r.post("/database/test")
    async def test_database(body: DbConnection) -> dict:
        ok, error = await database.test_url(body.url)
        return {"ok": ok, "error": error}

    @r.put("/database")
    async def set_database(body: DbConnection) -> dict:
        ok, error = await database.test_url(body.url)
        if not ok:
            return {"ok": False, "error": error}
        await database.save_database_url_and_reset(body.url)
        return {"ok": True, "restart_required": False}

    @r.get("/usage")
    async def get_usage() -> dict:
        return await usage.summary()

    @r.put("/usage/cap")
    async def put_usage_cap(body: SpendCap) -> dict:
        await usage.set_cap(body.enabled, body.limit_usd, body.period)
        return await usage.summary()

    @r.post("/feedback")
    async def post_feedback(body: NewFeedback) -> dict:
        if not body.message.strip():
            raise HTTPException(status_code=400, detail="Feedback message is empty")
        return await feedback.submit(body.category, body.message, body.contact, body.context)

    @r.get("/feedback")
    async def list_feedback() -> dict:
        return {"feedback": await feedback.recent()}

    @r.get("/providers")
    async def providers() -> dict:
        return await asyncio.to_thread(accounts.providers_status, ai.PROVIDERS)

    @r.put("/providers/{provider}/key")
    async def set_key(provider: str, body: ProviderKey) -> dict:
        if provider not in ai.PROVIDERS:
            raise HTTPException(status_code=404, detail="Unknown provider")
        if not body.key.strip():
            raise HTTPException(status_code=400, detail="Key is empty")
        secrets.set_provider_key(provider, body.key.strip())
        await _activate_provider(provider)  # so the new models show up in Chat right away
        return secrets.provider_key_status(provider)  # masked, never the raw key

    @r.delete("/providers/{provider}/key")
    async def clear_key(provider: str) -> dict:
        if provider not in ai.PROVIDERS:
            raise HTTPException(status_code=404, detail="Unknown provider")
        secrets.clear_provider_key(provider)
        return secrets.provider_key_status(provider)

    @r.post("/providers/anthropic/claude-plan/connect")
    async def connect_claude_plan() -> dict:
        try:
            status = await asyncio.to_thread(accounts.connect_claude_plan)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        try:  # auto-activate the plan's models; a seeding failure must not break connect
            await catalog.activate_many(
                [{"id": m["id"], "label": m["label"], "provider": m["provider"]}
                 for m in await asyncio.to_thread(accounts.claude_plan_models)]
            )
        except Exception:  # noqa: BLE001
            pass
        return status

    @r.delete("/providers/anthropic/claude-plan")
    async def disconnect_claude_plan() -> dict:
        return await asyncio.to_thread(accounts.disconnect_claude_plan)

    @r.post("/providers/anthropic/claude-plan/install")
    async def install_claude_cli(body: PlanConnection) -> dict:
        try:
            return await asyncio.to_thread(accounts.install_plan_cli, "claude_plan", body.acknowledged)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/providers/anthropic/claude-plan/login")
    async def login_claude_cli() -> dict:
        try:
            return await asyncio.to_thread(accounts.launch_plan_login, "claude_plan")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/providers/anthropic/claude-plan/refresh")
    async def refresh_claude_cli() -> dict:
        return await asyncio.to_thread(accounts.refresh_plan_mode, "claude_plan")

    async def _activate_cli_plan(models_fn) -> None:
        try:
            await catalog.activate_many(
                [{"id": m["id"], "label": m["label"], "provider": m["provider"]}
                 for m in await asyncio.to_thread(models_fn)]
            )
        except Exception:  # noqa: BLE001 — activation is best-effort, never blocks connect
            pass

    @r.post("/providers/openai/chatgpt-plan/connect")
    async def connect_chatgpt_plan(body: PlanConnection) -> dict:
        try:
            status = await asyncio.to_thread(accounts.connect_chatgpt_plan, body.acknowledged)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await _activate_cli_plan(accounts.chatgpt_plan_models)
        return status

    @r.delete("/providers/openai/chatgpt-plan")
    async def disconnect_chatgpt_plan() -> dict:
        return await asyncio.to_thread(accounts.disconnect_chatgpt_plan)

    @r.post("/providers/openai/chatgpt-plan/install")
    async def install_codex_cli(body: PlanConnection) -> dict:
        try:
            return await asyncio.to_thread(accounts.install_plan_cli, "chatgpt_plan", body.acknowledged)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/providers/openai/chatgpt-plan/login")
    async def login_codex_cli() -> dict:
        try:
            return await asyncio.to_thread(accounts.launch_plan_login, "chatgpt_plan")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/providers/openai/chatgpt-plan/refresh")
    async def refresh_codex_cli() -> dict:
        return await asyncio.to_thread(accounts.refresh_plan_mode, "chatgpt_plan")

    @r.post("/providers/google/gemini-plan/connect")
    async def connect_gemini_plan(body: PlanConnection) -> dict:
        try:
            status = await asyncio.to_thread(accounts.connect_gemini_plan, body.acknowledged)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await _activate_cli_plan(accounts.gemini_plan_models)
        return status

    @r.delete("/providers/google/gemini-plan")
    async def disconnect_gemini_plan() -> dict:
        return await asyncio.to_thread(accounts.disconnect_gemini_plan)

    # --- local models (official Ollama service) ---
    @r.get("/local-models")
    async def local_model_status() -> dict:
        return await local_models.status()

    @r.post("/local-models/install")
    async def install_local_runtime(body: PlanConnection) -> dict:
        try:
            await asyncio.to_thread(local_models.install, body.acknowledged)
            return await local_models.status()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @r.post("/local-models/start")
    async def start_local_runtime() -> dict:
        try:
            return await local_models.start()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @r.post("/local-models/pull")
    async def pull_local_model(body: LocalModelAction) -> StreamingResponse:
        return _sse(local_models.pull(body.model))

    @r.post("/local-models/active")
    async def activate_local_model(body: LocalModelAction) -> dict:
        if body.active is None:
            raise HTTPException(status_code=400, detail="Active state is required")
        try:
            return await local_models.set_active(body.model, body.active)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @r.post("/local-models/remove")
    async def remove_local_model(body: LocalModelAction) -> dict:
        try:
            return await local_models.remove(body.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    # --- data connections (read-only) ---
    @r.get("/connections")
    async def connections_list() -> dict:
        return {"connections": await data.list_connections()}

    @r.post("/connections")
    async def connection_add(body: NewConnection) -> dict:
        try:
            return await data.add_connection(body.name, body.url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.delete("/connections/{cid}")
    async def connection_delete(cid: str) -> dict:
        if not await data.delete_connection(cid):
            raise HTTPException(status_code=404, detail="Connection not found")
        return {"deleted": True}

    @r.get("/connections/{cid}/tables")
    async def connection_tables(cid: str) -> dict:
        try:
            return {"tables": await data.list_tables(cid)}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=secrets.redact_url(str(e))[:160])

    @r.get("/connections/{cid}/browse")
    async def connection_browse(cid: str, schema: str, table: str, limit: int = 100) -> dict:
        try:
            return await data.browse_table(cid, schema, table, limit)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=secrets.redact_url(str(e))[:160])

    # --- document collections (RAG) ---
    @r.get("/collections")
    async def collections_list() -> dict:
        return {"collections": await rag.list_collections()}

    @r.post("/collections")
    async def collection_create(body: NewCollection) -> dict:
        return await rag.create_collection(body.name)

    @r.delete("/collections/{cid}")
    async def collection_delete(cid: str) -> dict:
        if not await rag.delete_collection(cid):
            raise HTTPException(status_code=404, detail="Collection not found")
        return {"deleted": True}

    @r.post("/collections/{cid}/documents")
    async def collection_upload(cid: str, body: UploadDocs) -> dict:
        try:
            return {"added": await rag.add_documents(cid, [a.model_dump() for a in body.files])}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e)[:160])

    @r.get("/collections/{cid}/search")
    async def collection_search(cid: str, q: str, k: int = 5) -> dict:
        return {"results": await rag.search(cid, q, k)}

    # --- projects ---
    @r.get("/projects")
    async def projects_list() -> dict:
        return {"projects": await projects.list_projects()}

    @r.post("/projects")
    async def projects_create(body: ProjectBody) -> dict:
        return await projects.create_project(body.name, body.description, body.instructions)

    @r.get("/projects/{pid}")
    async def projects_get(pid: str) -> dict:
        try:
            project = await projects.get_project(pid)
        except ValueError:
            raise HTTPException(status_code=404, detail="Project not found") from None
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @r.patch("/projects/{pid}")
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

    @r.delete("/projects/{pid}")
    async def projects_delete(pid: str) -> dict:
        try:
            deleted = await projects.delete_project(pid)
        except ValueError:
            deleted = False
        if not deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"deleted": True}

    @r.post("/projects/{pid}/conversations/{cid}")
    async def projects_attach_conversation(pid: str, cid: str) -> dict:
        try:
            conv = await projects.set_conversation_project(cid, pid)
        except ValueError:
            raise HTTPException(status_code=404, detail="Project or conversation not found") from None
        if conv is None:
            raise HTTPException(status_code=404, detail="Project or conversation not found")
        return conv

    @r.delete("/conversations/{cid}/project")
    async def conversation_clear_project(cid: str) -> dict:
        try:
            conv = await projects.set_conversation_project(cid, None)
        except ValueError:
            raise HTTPException(status_code=404, detail="Conversation not found") from None
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conv

    # --- conversations ---
    @r.get("/conversations")
    async def conversations() -> dict:
        return {"conversations": await chat.list_conversations()}

    @r.post("/conversations")
    async def new_conversation(body: NewConversation) -> dict:
        try:
            return await chat.create_conversation(
                body.model, body.system_prompt, body.effort, body.context_window, body.project_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @r.get("/conversations/{cid}")
    async def conversation(cid: str) -> dict:
        conv = await chat.get_conversation(cid)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conv["running"] = chat.is_running(cid)  # so the UI can re-attach to a background run
        return conv

    @r.patch("/conversations/{cid}")
    async def patch_conversation(cid: str, body: UpdateConversation) -> dict:
        provided = body.model_dump(exclude_unset=True)
        try:
            conv = await chat.update_conversation(cid, **provided)
        except ValueError:
            raise HTTPException(status_code=404, detail="Conversation or project not found") from None
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conv

    @r.delete("/conversations/{cid}")
    async def remove_conversation(cid: str) -> dict:
        if not await chat.delete_conversation(cid):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"deleted": True}

    @r.post("/conversations/{cid}/messages")
    async def send_message(cid: str, body: NewMessage) -> StreamingResponse:
        attachments = [a.model_dump() for a in body.attachments]
        return _sse_run(cid, chat.stream_reply(cid, body.content, attachments, body.collection_id))

    @r.post("/conversations/{cid}/code-image")
    async def generate_code_image(cid: str, body: NewMessage) -> StreamingResponse:
        if body.attachments:
            raise HTTPException(status_code=400, detail="Code-rendered images do not accept attachments yet")
        return _sse_run(cid, chat.stream_code_image(cid, body.content))

    @r.post("/conversations/{cid}/regenerate")
    async def regenerate_message(cid: str) -> StreamingResponse:
        return _sse_run(cid, chat.regenerate(cid))

    @r.post("/conversations/{cid}/stop")
    async def stop_generation(cid: str) -> dict:
        chat.cancel_run(cid)
        return {"stopped": True}

    @r.get("/conversations/{cid}/resume")
    async def resume_generation(cid: str) -> StreamingResponse:
        # Re-attach to a generation that's still running in the background (client navigated away).
        return _sse(chat.resume(cid))

    @r.get("/tasks")
    async def list_tasks() -> dict:
        from backend.features import taskbrain
        return {"tasks": await taskbrain.recent(50)}

    @r.get("/task-routes")
    async def task_routes() -> dict:
        return await route_telemetry.summary()

    @r.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str) -> dict:
        from backend.features import taskbrain
        return {"canceled": await taskbrain.cancel(task_id)}

    @r.get("/conversations/{cid}/messages/{mid}/export/{export_format}")
    async def export_reply(cid: str, mid: str, export_format: str) -> Response:
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

    @r.get("/conversations/{cid}/messages/{mid}/preview/{export_format}")
    async def preview_reply(cid: str, mid: str, export_format: str) -> dict:
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
        artifact_id = artifacts.register(result.content, result.media_type)
        return {"url": f"/artifacts/{artifact_id}", "kind": export_format}

    @r.get("/files/{file_id}")
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

    @r.get("/files/{file_id}/preview")
    async def preview_file(file_id: str) -> dict:
        item = file_library.load(file_id)
        if item is None:
            raise HTTPException(status_code=404, detail="File not found or expired")
        meta, data = item
        content, media = filepreview.to_preview(meta["name"], meta["mime"], data)
        artifact_id = artifacts.register(content, media)
        return {"url": f"/artifacts/{artifact_id}", "mime": media}

    @r.post("/artifacts")
    async def create_artifact(body: NewArtifact) -> dict:
        try:
            artifact_id = artifacts.register(body.html)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {"id": artifact_id, "url": f"/artifacts/{artifact_id}"}

    # Unauthenticated GET so it can load in a sandboxed <iframe>. The iframe uses
    # sandbox="allow-scripts" WITHOUT allow-same-origin → opaque origin, no access to the
    # app/token. Content is the user's own reply. Its own permissive CSP lets the HTML run.
    _ARTIFACT_CSP = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
        "img-src * data: blob:; media-src * data: blob:; style-src 'unsafe-inline' *; "
        "script-src 'unsafe-inline' 'unsafe-eval'; font-src * data:; connect-src 'self'"
    )

    @api.get("/artifacts/{artifact_id}")
    async def serve_artifact(artifact_id: str) -> Response:
        item = artifacts.get(artifact_id)
        if item is None:
            return Response("This preview has expired. Re-open it from the chat.", status_code=404)
        media_type, data = item
        headers = {
            "X-Frame-Options": "SAMEORIGIN",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        }
        if media_type == "text/html":  # HTML runs sandboxed; binary files (PDF) render natively
            headers["Content-Security-Policy"] = _ARTIFACT_CSP
        return Response(content=data, media_type=media_type, headers=headers)

    api.include_router(r)

    # serve the built UI last so /api routes take precedence
    if not settings.orrery_dev and _UI_DIST.is_dir():
        api.mount("/", _FreshHtmlStatic(directory=str(_UI_DIST), html=True), name="ui")
    else:

        @api.get("/", response_class=HTMLResponse)
        async def placeholder() -> str:
            return _PLACEHOLDER

    return api
