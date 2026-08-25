from __future__ import annotations

import asyncio
import logging
import os
import secrets as pysecrets
import sys
import threading
import webbrowser

import uvicorn

# psycopg async needs the SelectorEventLoop on Windows (SQLAlchemy + Procrastinate)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from backend.core import database
from backend.core.config import settings
from backend.core import paths
from backend.core.paths import resource_path
from backend.security.secrets import redact_url

from backend.core.observability import install as _install_logging

_install_logging(logging.INFO)  # root logging with per-request [id] field
log = logging.getLogger("orrery")

# fresh per-session token so other local processes can't drive the API. The browser never sees it:
# it receives a single-use launch code and trades it for an httpOnly cookie (backend/security/session.py).
SESSION_TOKEN = os.environ.get("ORRERY_SESSION_TOKEN") or pysecrets.token_urlsafe(32)

API_HOST = os.environ.get("ORRERY_API_HOST", "").strip() or settings.api_host
_api_port: int | None = None


def _resolve_api_port() -> int:
    """An explicit ORRERY_API_PORT always wins. Otherwise prefer the configured port but fall back
    to a free one, so a second Orrery (an installed copy launched beside a dev run) never dies on
    bind (Errno 10048)."""
    global _api_port
    if _api_port is not None:
        return _api_port
    explicit = os.environ.get("ORRERY_API_PORT", "").strip()
    if explicit:
        _api_port = int(explicit)
        return _api_port
    import socket

    try:
        with socket.socket() as probe:
            probe.bind((API_HOST, settings.api_port))
        _api_port = settings.api_port
    except OSError:
        with socket.socket() as probe:
            probe.bind((API_HOST, 0))
            _api_port = probe.getsockname()[1]
        log.info("Port %s is busy (another Orrery running?) - using %s instead",
                 settings.api_port, _api_port)
    return _api_port

_ready = threading.Event()
# Set only when the backend stops. The idle loop in main() must wait on THIS, never on _ready:
# _ready is already set by then, so waiting on it returns instantly and spins the main thread at
# 100% CPU, which starves the backend thread's event loop through the GIL.
_stopped = threading.Event()
_boot_error: list[BaseException] = []
_session_code: list[str] = []  # filled once the API app exists; the launch URL needs it


def ensure_connection() -> str:
    """Resolve the DB connection string on first run.

    With a console (dev run / setup script): ask interactively, as before. Without one
    (the installed desktop build pipes stdin to nowhere — input() would crash the backend):
    auto-provision the bundled Docker PostgreSQL when Docker is available, else exit with a
    setup marker the desktop shell turns into an actionable dialog."""
    from backend.core import dockerboot

    url = database.resolve_database_url()
    # Electron always starts the packaged backend with --backend-only and no usable prompt. A
    # console-mode PyInstaller child can still report a hidden TTY on Windows, so isatty() alone
    # is not enough: treating that hidden console as interactive skips Docker recovery and leaves
    # the backend to time out against a stopped local database.
    backend_only = "--backend-only" in sys.argv or os.environ.get("ORRERY_BACKEND_ONLY") == "1"
    has_console = not backend_only and bool(sys.stdin) and sys.stdin.isatty()
    # Bring the bundled local database up automatically — starting Docker if it's installed but
    # not running — whenever Orrery would actually use it: a fresh install (no URL) OR a returning
    # user whose SAVED URL is that same local DB (the previous code skipped this when a URL existed,
    # so reopening with Docker stopped just failed). A user's own external Postgres URL is untouched.
    if dockerboot.should_ensure_local(url, stdin_isatty=has_console):
        provisioned = dockerboot.provision()
        if provisioned:
            url = provisioned
            database.save_database_url(url)
        elif not has_console:
            # provision() already printed the ORRERY_SETUP:* marker the desktop shell turns into
            # the actionable Install/Start-Docker dialog; exit so that dialog is shown.
            raise SystemExit("Orrery could not start its local database (see the setup dialog).")
    if not url:
        if not has_console:
            raise SystemExit(
                "No database is configured and no console is available to ask on. "
                "Install/start Docker Desktop for the bundled database, or set a connection string in Settings."
            )
        print("\nOrrery first run - no database configured.")
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

    from backend.features import life as _life
    _life.bootstrap()  # create the upgrade-safe solo memory charter once; never overwrites it

    from backend.features import files as _files
    _files.cleanup()  # prune generated files past their TTL so tmp/ doesn't grow forever

    from backend.features import taskbrain as _taskbrain
    await _taskbrain.reconcile_orphans()  # mark last run's 'running' tasks as interrupted

    from backend.features import agent_runs as _agent_runs
    await _agent_runs.reconcile_orphans()  # agent runs left 'running' by a closed app

    # Close tool calls a crash left open (ADR-005 slice 1). This never re-runs a body: it records
    # whether the call had started, so an effect that may have happened is marked unknown rather
    # than quietly presented as safe to retry.
    from backend.tools import lifecycle as _lifecycle
    _recovered = await _lifecycle.reconcile_incomplete_calls()
    if any(_recovered.values()):
        log.info("Recovered interrupted tool calls: %s", _recovered)

    from backend.features import skills as _skills
    await _skills.refresh_user_skills()  # load the user's own enabled skills into memory

    # Declared plugins mount before anything serves, so their policy is in place for the first
    # request. A failure raises here on purpose: running without a policy the user asked for is
    # the least safe outcome available (ADR-004).
    from backend.core import plugins as _plugins
    mounted = _plugins.mount_all()
    if mounted:
        log.info("Mounted plugins: %s", ", ".join(mounted))

    # litellm costs seconds to import and the model picker needs it on the very first paint.
    # Warm it in a worker thread so that cost is paid while the user is still looking at the
    # loading screen, instead of stalling their first request behind it.
    from backend.providers import ai as _ai
    threading.Thread(target=_ai.warm_model_metadata, name="orrery-warm-models", daemon=True).start()

    api = create_app(SESSION_TOKEN)
    _session_code.append(api.state.session.code)
    config = uvicorn.Config(
        api, host=API_HOST, port=_resolve_api_port(), log_level="info", access_log=False
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
        log.info("API ready on http://%s:%s", API_HOST, _resolve_api_port())
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
        finally:
            _stopped.set()  # wakes the idle loop in main() as soon as serving ends

    threading.Thread(target=runner, name="orrery-backend", daemon=True).start()


def _base_url() -> str:
    return (
        settings.vite_url
        if settings.orrery_dev
        else f"http://{API_HOST}:{_resolve_api_port()}"
    )


def _browser_url() -> str:
    """The URL to open. The launch code is single-use and the page strips it from the address bar,
    so it never settles into history or a bookmark."""
    code = _session_code[0] if _session_code else ""
    return f"{_base_url()}/?c={code}" if code else _base_url()


def _packaging_probe() -> None:
    """Fast frozen-build health check used by the release scripts.

    This intentionally does not start the database or the API server. It imports the same runtime
    the packaged app uses so a broken build fails before it reaches users. There is no GUI runtime
    to check any more — the workspace is served to the user's browser.
    """
    print("Orrery packaging probe: checking runtime...")
    required = [
        resource_path("ui", "dist", "index.html"),
        resource_path("skills"),
        resource_path("assets", "desktop", "orrery.png"),
        resource_path("LIFE.md"),
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Packaged resource check failed. Missing: " + ", ".join(missing))
    from backend.features.filepreview import pdf_renderer_available

    if not pdf_renderer_available():
        raise RuntimeError("PDF preview renderer is missing from the packaged runtime.")
    # litellm counts tokens with tiktoken; its encodings load via the tiktoken_ext plugin package,
    # which PyInstaller misses unless collected — a broken build fails every API-key chat with
    # "Unknown encoding cl100k_base", so catch it here instead of in users' chats.
    import tiktoken

    if len(tiktoken.get_encoding("cl100k_base").encode("orrery")) < 1:
        raise RuntimeError("tiktoken cl100k_base encoding returned no tokens.")
    print("Orrery packaging probe: ok")


def _build_ui_bundle(ui_dir) -> None:
    """Run the one-time workspace build. Output is left on the console: it takes a minute the
    first time and silence would look like a hang."""
    from backend.core import proc

    # Windows ships npm twice: `npm` (a shell script) and `npm.cmd`. PATH order can hand back the
    # extensionless one, which CreateProcess refuses with "not a valid Win32 application", so ask
    # for the .cmd first on Windows.
    candidates = ("npm.cmd", "npm") if sys.platform == "win32" else ("npm",)
    npm = next((found for name in candidates if (found := proc.find_executable(name))), None)
    if npm is None:
        raise SystemExit(
            "Orrery needs Node.js 20+ to build its workspace the first time, and npm was not "
            "found on PATH. "
            "Install Node from https://nodejs.org/ and start Orrery again, or build it yourself "
            "with:  cd ui && npm install && npm run build"
        )

    # `npm ci` is the reproducible install and needs the committed lockfile; fall back to
    # `npm install` only if that lockfile is somehow absent.
    install = [npm, "ci"] if (ui_dir / "package-lock.json").exists() else [npm, "install"]
    print("\n  First run: building the workspace bundle. This happens once and takes a minute.\n",
          flush=True)
    for argv in (install, [npm, "run", "build"]):
        shown = " ".join(["npm", *argv[1:]])  # name the command that actually ran (ci vs install)
        try:
            done = proc.run(argv, cwd=str(ui_dir), timeout=1800, check=False)
        except OSError as exc:
            raise SystemExit(f"Could not run `{shown}`: {exc}") from None
        if done.returncode != 0:
            raise SystemExit(
                f"The workspace build failed during `{shown}` (exit {done.returncode}). "
                "The output above says why; fix it, or build manually with:  "
                "cd ui && npm install && npm run build"
            )


def _ensure_ui_bundle(auto_build: bool = True) -> None:
    """Make sure there is a workspace to serve, building it once on a fresh checkout.

    In dev the workspace comes from Vite. Otherwise the API serves ui/dist, and a checkout that has
    never run a UI build has nothing to serve. This used to stop with instructions, which made a
    fresh install a multi-command ritual; the build is deterministic and only needed once, so
    Orrery just does it. A packaged build always ships the bundle and never builds anything.
    """
    if settings.orrery_dev:
        return
    index = resource_path("ui", "dist", "index.html")
    if index.exists():
        return

    ui_dir = paths.project_root() / "ui"
    packaged = bool(getattr(sys, "frozen", False))
    if packaged or not auto_build or not (ui_dir / "package.json").is_file():
        raise SystemExit(
            f"The workspace bundle is missing ({index}). "
            "Build it once with:  cd ui && npm install && npm run build"
        )

    _build_ui_bundle(ui_dir)
    if not index.exists():
        raise SystemExit(
            f"The workspace build finished but produced no bundle at {index}. "
            "Build it manually with:  cd ui && npm install && npm run build"
        )


def _idle_until_stopped(poll: float = 1.0) -> None:
    """Keep the process alive while the backend thread serves.

    Waits on `_stopped`, which stays unset while Orrery runs, so each iteration really does sleep.
    Waiting on `_ready` here (it is already set by this point) returns instantly and turns this
    into a busy loop that starves the backend thread through the GIL - measured at 530ms of added
    latency on every request, including static chunks.
    """
    while not _boot_error and not _stopped.wait(timeout=poll):
        pass


def main(open_browser: bool = True, auto_build: bool = True) -> None:
    """Run Orrery and hand the workspace to the user's own browser."""
    _ensure_ui_bundle(auto_build)
    ensure_connection()
    _start_backend_thread()

    if not _ready.wait(timeout=60):
        raise SystemExit("Backend did not become ready within 60s.")
    if _boot_error:
        raise SystemExit(f"Startup failed: {_boot_error[0]}")

    url = _browser_url()
    # printed, never logged: the launch code is a credential and log files outlive the session
    # flush: stdout block-buffers whenever it is not a terminal, and this URL is the only way
    # in when the browser does not open - it must not sit in a buffer until the process ends.
    print(f"\n  Orrery is running at {_base_url()}", flush=True)
    print(
        f"  Opening your browser. If it doesn't open, paste this once:\n\n    {url}\n",
        flush=True,
    )
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 — the printed URL is the fallback
            log.info("Could not launch a browser automatically; open the URL above.")
    try:
        _idle_until_stopped()
    except KeyboardInterrupt:
        print("\nOrrery stopped.")


def run_backend_only() -> None:
    ensure_connection()
    asyncio.run(_boot_and_serve())


USAGE = """Orrery - a local-first AI workspace, served to your own browser.

Usage:
  orrery [web] [--no-browser]   start Orrery and open the workspace (default)

Options:
  --no-browser    start the backend but do not open a browser; use the printed URL
  --no-build      never build the workspace bundle; fail if it is missing
  --dump-config   print every setting, its value, and which layer supplied it, then exit
  -h, --help      show this message
"""


def cli(argv: list[str] | None = None) -> None:
    """Console-script entry point (`orrery web`).

    `web` is the default and only user-facing mode. The build and service modes stay flag-driven
    because the packaging scripts and the frozen executables invoke them that way.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if "--dump-config" in args:
        from backend.core import profiles
        print(profiles.render(settings))
        return
    if "--packaging-probe" in args or os.environ.get("ORRERY_PACKAGING_PROBE") == "1":
        _packaging_probe()
        return
    if "--backend-only" in args or os.environ.get("ORRERY_BACKEND_ONLY") == "1":
        run_backend_only()
        return

    if args and args[0] == "web":
        args = args[1:]
    if "-h" in args or "--help" in args:
        print(USAGE)
        return

    unknown = [arg for arg in args if arg not in ("--no-browser", "--no-build", "--dump-config")]
    if unknown:
        print("Unrecognized argument(s):", *unknown, file=sys.stderr)
        print(USAGE, file=sys.stderr)
        raise SystemExit(2)

    main(open_browser="--no-browser" not in args, auto_build="--no-build" not in args)


if __name__ == "__main__":
    cli()
