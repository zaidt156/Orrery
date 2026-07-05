"""Orrery API package: create_app + per-feature routers (split from the api.py monolith)."""
from __future__ import annotations

from backend.api.schemas import *  # noqa: F401,F403 — re-export request models (tests/api compat)

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.core.config import settings
from backend.core.observability import new_request_id
from backend.core.paths import resource_path
from backend.features import artifacts

_UI_DIST = resource_path("ui", "dist")


class _FreshHtmlStatic(StaticFiles):
    """Serve the SPA but never let the webview cache index.html — content-hashed assets
    can cache forever, but a stale index.html would point at old JS and silently run an old build.

    SPA fallback: an unknown path with no file extension serves index.html instead of a raw JSON
    404 — a strayed window (stale navigation after a restart) boots back into the app instead of
    stranding the user on {"detail":"Not Found"}. Real asset misses (paths with extensions) still 404."""

    async def get_response(self, path, scope):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                response = await super().get_response("index.html", scope)
            else:
                raise
        if response.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
            response = await super().get_response("index.html", scope)
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

# Keep the fallback backend page aligned with the current app mark. This only appears
# when the production UI has not been built yet.
_PLACEHOLDER = """<!doctype html><html><head><meta charset="utf-8">
<title>Orrery</title></head><body style="font-family:sans-serif;background:#0b1020;
color:#e8ecf5;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center;max-width:520px;padding:24px">
<svg width="72" height="72" viewBox="0 0 64 64" fill="none" aria-hidden="true" style="filter:drop-shadow(0 10px 20px #02051199)">
<rect x="4" y="4" width="56" height="56" rx="15" fill="#071022"/>
<rect x="5.25" y="5.25" width="53.5" height="53.5" rx="13.75" stroke="#2B395E" stroke-width="1.5"/>
<circle cx="32" cy="32" r="19.5" stroke="#E8ECF8" stroke-width="5.5"/>
<path d="M13.7 40.6C25.3 51.8 47 49.4 55.3 35.3" stroke="#82ADE8" stroke-width="4.2" stroke-linecap="round"/>
<path d="M13.1 31.8C13.1 20.9 21.1 12.4 31.4 12.4" stroke="#071022" stroke-width="7.2" stroke-linecap="round"/>
<circle cx="32" cy="32" r="8.1" fill="#F2B14E"/>
<circle cx="50.2" cy="19.8" r="4.3" fill="#F2B14E" stroke="#071022" stroke-width="2"/>
<circle cx="15.6" cy="43.5" r="3.4" fill="#9DB9F0" stroke="#071022" stroke-width="1.7"/>
</svg>
<h1 style="font-size:28px;margin:14px 0 8px">Orrery</h1>
<p>Backend is running. Build the UI (<code>cd ui &amp;&amp; npm run build</code>)
or set <code>ORRERY_DEV=1</code> for the dev server.</p></div>
</body></html>"""


_MAX_BODY_BYTES = settings.max_upload_bytes  # request body cap (configurable; blocks runaway payloads)
_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'self'; frame-ancestors 'none'"
)



def create_app(session_token: str) -> FastAPI:
    """Build the FastAPI application bound to this session's auth token."""
    api = FastAPI(title="Orrery", docs_url=None, redoc_url=None, openapi_url=None)

    @api.exception_handler(PermissionError)
    async def _permission_error(_request, exc: PermissionError):
        return JSONResponse({"detail": str(exc) or "Access denied"}, status_code=403)

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


    from backend.api import (
        routes_admin_team, routes_app_settings, routes_collections, routes_conversations,
        routes_dashboards, routes_data, routes_files, routes_local_models, routes_mcp,
        routes_models, routes_projects, routes_providers, routes_skills, routes_system, routes_tools,
    )
    for module in (
        routes_system, routes_models, routes_app_settings, routes_providers, routes_local_models,
        routes_data, routes_dashboards, routes_collections, routes_skills, routes_mcp,
        routes_admin_team, routes_projects, routes_conversations, routes_files, routes_tools,
    ):
        api.include_router(module.router, prefix="/api", dependencies=[Depends(require_token)])

    # serve the built UI last so /api routes take precedence
    if not settings.orrery_dev and _UI_DIST.is_dir():
        api.mount("/", _FreshHtmlStatic(directory=str(_UI_DIST), html=True), name="ui")
    else:

        @api.get("/", response_class=HTMLResponse)
        async def placeholder() -> str:
            return _PLACEHOLDER

    return api
