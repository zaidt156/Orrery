from __future__ import annotations

import asyncio
import base64
import logging
import secrets as pysecrets
import sys
import threading
from pathlib import Path

import uvicorn
import webview

# psycopg async needs the SelectorEventLoop on Windows (SQLAlchemy + Procrastinate)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from backend.core import database
from backend.core.config import settings
from backend.security.secrets import redact_url

from backend.core.observability import install as _install_logging

_install_logging(logging.INFO)  # root logging with per-request [id] field
log = logging.getLogger("orrery")

# fresh per-session token so other local processes can't drive the API
SESSION_TOKEN = pysecrets.token_urlsafe(32)
APP_ICON = Path(__file__).resolve().parent / "assets" / "desktop" / "orrery.ico"
WEBVIEW_DATA_DIR = Path(__file__).resolve().parent / "tmp" / "webview2"

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
        icon=str(APP_ICON) if APP_ICON.exists() else None,
        storage_path=str(WEBVIEW_DATA_DIR),
        private_mode=True,
    )


if __name__ == "__main__":
    main()
