from __future__ import annotations

import asyncio
import base64
import logging
import os
import secrets as pysecrets
import sys
import threading

import uvicorn
import webview

# psycopg async needs the SelectorEventLoop on Windows (SQLAlchemy + Procrastinate)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from backend.core import database
from backend.core.config import settings
from backend.core.paths import resource_path, runtime_path
from backend.security.secrets import redact_url

from backend.core.observability import install as _install_logging

_install_logging(logging.INFO)  # root logging with per-request [id] field
log = logging.getLogger("orrery")

# fresh per-session token so other local processes can't drive the API. Electron can pass one in
# because it owns the desktop window and starts the backend as a child process.
SESSION_TOKEN = os.environ.get("ORRERY_SESSION_TOKEN") or pysecrets.token_urlsafe(32)
WEBVIEW_DATA_DIR = runtime_path("tmp", "webview2")

_ready = threading.Event()
_boot_error: list[BaseException] = []


class JsApi:
    """Exposed to the page as window.pywebview.api — native file save (webview blob
    downloads are unreliable, so the UI hands us bytes and we write them via a save dialog).

    Note: do NOT keep a reference to the window on this object — pywebview serializes the
    api's attributes to the page, and a window reference causes infinite recursion. Use
    webview.windows[0] at call time instead.
    """

    def save_file(self, filename: str, b64: str) -> dict:
        if not webview.windows:
            return {"ok": False, "error": "Window not ready."}
        window = webview.windows[0]
        save_dialog = getattr(getattr(webview, "FileDialog", None), "SAVE", None)
        if save_dialog is None:  # older pywebview
            save_dialog = getattr(webview, "SAVE_DIALOG", None)
        try:
            chosen = window.create_file_dialog(save_dialog, save_filename=filename or "orrery-file")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        if not chosen:
            return {"ok": False, "cancelled": True}
        target = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
        try:
            with open(target, "wb") as handle:
                handle.write(base64.b64decode(b64))
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(target)}


_js_api = JsApi()


def ensure_connection() -> str:
    """Resolve the DB connection string, prompting once on first run."""
    url = database.resolve_database_url()
    if not url:
        print("\nOrrery first run — no database configured.")
        print("Enter your PostgreSQL connection string, for example:")
        print("  postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery")
        url = input("Connection string: ").strip()
        if not url:
            raise SystemExit("No connection string provided.")
        database.save_database_url(url)
        print("Saved to the OS keychain.\n")
    log.info("Using database %s", redact_url(url))
    return url


async def _boot_and_serve() -> None:
    """Connect, migrate, then run the API server and queue worker until stopped."""
    from backend.api import create_app
    from backend.core.migrations import run_migrations
    from backend.core.queue import get_queue_app

    if not await database.check_connection(force=True):
        raise RuntimeError(
            "Could not connect to the database. Is it running? (docker compose up -d)"
        )
    await run_migrations()

    from backend.features import files as _files
    _files.cleanup()  # prune generated files past their TTL so tmp/ doesn't grow forever

    from backend.features import taskbrain as _taskbrain
    await _taskbrain.reconcile_orphans()  # mark last run's 'running' tasks as interrupted

    from backend.features import skills as _skills
    await _skills.refresh_user_skills()  # load the user's own enabled skills into memory

    api = create_app(SESSION_TOKEN)
    config = uvicorn.Config(
        api, host=settings.api_host, port=settings.api_port, log_level="info", access_log=False
    )
    server = uvicorn.Server(config)

    queue_app = get_queue_app()
    async with queue_app.open_async():
        # off the main thread → can't install OS signal handlers
        worker = asyncio.create_task(
            queue_app.run_worker_async(
                concurrency=4, wait=True, install_signal_handlers=False
            )
        )
        serve = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.05)
        log.info("API ready on http://%s:%s", settings.api_host, settings.api_port)
        _ready.set()
        try:
            await serve
        finally:
            worker.cancel()


def _start_backend_thread() -> None:
    def runner() -> None:
        try:
            asyncio.run(_boot_and_serve())
        except BaseException as exc:  # surface startup failures to the main thread
            _boot_error.append(exc)
            _ready.set()

    threading.Thread(target=runner, name="orrery-backend", daemon=True).start()


def _window_url() -> str:
    base = (
        settings.vite_url
        if settings.orrery_dev
        else f"http://{settings.api_host}:{settings.api_port}"
    )
    return f"{base}/?token={SESSION_TOKEN}"


def _app_icon() -> str | None:
    candidates = (
        ("orrery.ico",) if sys.platform == "win32" else ("orrery.png", "orrery.ico")
    )
    for name in candidates:
        path = resource_path("assets", "desktop", name)
        if path.exists():
            return str(path)
    return None


def _desktop_gui() -> str | None:
    return "qt" if sys.platform == "win32" else None


def _packaging_probe() -> None:
    """Fast frozen-build health check used by the release scripts.

    This intentionally does not start the database, API server, or WebView window. It imports the
    same desktop backend the packaged app uses so a broken zip fails before it reaches users.
    """
    print("Orrery packaging probe: checking desktop runtime...")
    required = [
        resource_path("ui", "dist", "index.html"),
        resource_path("skills"),
        resource_path("assets", "desktop", "orrery.png"),
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Packaged resource check failed. Missing: " + ", ".join(missing))
    if sys.platform == "win32":
        import webview.platforms.qt as _qt_backend
        from qtpy.QtWebEngineWidgets import QWebEngineView  # noqa: F401

        if getattr(_qt_backend, "renderer", "") != "qtwebengine":
            raise RuntimeError("Windows package must use Qt WebEngine desktop runtime.")
    elif sys.platform == "darwin":
        import webview.platforms.cocoa  # noqa: F401
    print("Orrery packaging probe: ok")


def main() -> None:
    # Windows groups the taskbar by process (python.exe) and shows its icon; giving the app
    # its own AppUserModelID makes Windows use our window icon in the taskbar instead.
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Orrery.Desktop.App")
        except Exception:  # noqa: BLE001 — cosmetic only
            pass

    ensure_connection()
    _start_backend_thread()

    if not _ready.wait(timeout=60):
        raise SystemExit("Backend did not become ready within 60s.")
    if _boot_error:
        raise SystemExit(f"Startup failed: {_boot_error[0]}")

    log.info("Opening Orrery window")
    WEBVIEW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    webview.create_window(
        "Orrery",
        url=_window_url(),
        width=1280,
        height=820,
        min_size=(940, 640),
        js_api=_js_api,
    )
    webview.start(
        gui=_desktop_gui(),
        icon=_app_icon(),
        storage_path=str(WEBVIEW_DATA_DIR),
        private_mode=True,
    )


def run_backend_only() -> None:
    ensure_connection()
    asyncio.run(_boot_and_serve())


if __name__ == "__main__":
    if "--packaging-probe" in sys.argv or os.environ.get("ORRERY_PACKAGING_PROBE") == "1":
        _packaging_probe()
    elif "--backend-only" in sys.argv or os.environ.get("ORRERY_BACKEND_ONLY") == "1":
        run_backend_only()
    else:
        main()
