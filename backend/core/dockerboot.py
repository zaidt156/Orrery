"""First-run Docker bootstrap for the installed desktop app.

When Orrery starts with no database configured and no console to ask on (the packaged
Electron build pipes stdin to nowhere), asking with input() would crash the backend.
Instead, if Docker is available we provision the same bundled PostgreSQL the setup
scripts use — identical image, container name, credentials, and volume as
docker-compose.yml — so a fresh install "just works" the moment Docker Desktop is there.

Security (security.md): only the LOCAL dev container with the throwaway dev password is
ever started, published on 127.0.0.1 only; the resulting URL is saved to the OS keychain
exactly like a user-entered connection string, and nothing here logs a secret.

The MARKER_* strings are printed to stdout on failure; the Electron shell tails its
backend log for them to show the matching "install/start Docker" dialog. Keep them stable.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from backend.core import proc

log = logging.getLogger("orrery.dockerboot")

DEFAULT_URL = "postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery"
CONTAINER = "orrery-postgres"
IMAGE = "pgvector/pgvector:pg17"

MARKER_DOCKER_MISSING = "ORRERY_SETUP:DOCKER_MISSING"
MARKER_DOCKER_STOPPED = "ORRERY_SETUP:DOCKER_STOPPED"
MARKER_PROVISION_FAILED = "ORRERY_SETUP:PROVISION_FAILED"

_RUN_TIMEOUT = 30  # seconds per docker CLI call (except the image pull, which gets its own)


def should_autoprovision(configured_url: str | None, *, stdin_isatty: bool) -> bool:
    """Provision only on a truly unconfigured, headless start — never over a user's choice."""
    return not configured_url and not stdin_isatty


def _is_bundled_local_url(url: str | None) -> bool:
    """True when the URL is the bundled local database that provision() manages."""
    return bool(url) and ("127.0.0.1:5432/orrery" in url or "localhost:5432/orrery" in url)


def should_ensure_local(configured_url: str | None, *, stdin_isatty: bool) -> bool:
    """Bring the bundled local database up (starting Docker if needed) whenever Orrery would
    actually USE it — a fresh install with no URL, OR a returning user whose SAVED URL is that
    same bundled local DB. A user's own external Postgres URL is left untouched, and a console
    (dev / setup script) run manages Docker itself."""
    if stdin_isatty:
        return False
    return (not configured_url) or _is_bundled_local_url(configured_url)


def run_args() -> list[str]:
    """The docker run equivalent of the docker-compose.yml service, bound to localhost only."""
    return [
        "docker", "run", "-d",
        "--name", CONTAINER,
        "--restart", "unless-stopped",
        "-e", "POSTGRES_USER=orrery",
        "-e", "POSTGRES_PASSWORD=orrery_dev_password",
        "-e", "POSTGRES_DB=orrery",
        "-p", "127.0.0.1:5432:5432",
        "-v", "orrery_pgdata:/var/lib/postgresql/data",
        IMAGE,
    ]


def _docker_desktop_exe() -> Path | None:
    """Path to the Docker Desktop launcher, if installed."""
    if sys.platform == "darwin":
        app = Path("/Applications/Docker.app")
        return app if app.exists() else None
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        exe = Path(pf, "Docker", "Docker", "Docker Desktop.exe")
        return exe if exe.is_file() else None
    return None


def _docker_bin() -> str:
    """The docker CLI command to spawn.

    Windows: return the bare name so PATHEXT resolves docker.EXE — NOT the extensionless 'docker'
    file shutil.which reports (that's the WSL/Linux CLI and CreateProcess rejects it, WinError 193).
    Only fall back to the explicit docker.exe path when it isn't on PATH at all.
    macOS: proc.find_executable covers the app's minimal PATH + the Docker.app bundle."""
    import shutil

    if sys.platform == "win32":
        if not shutil.which("docker.exe"):
            pf = os.environ.get("ProgramFiles", r"C:\Program Files")
            cand = Path(pf, "Docker", "Docker", "resources", "bin", "docker.exe")
            if cand.is_file():
                return str(cand)
        return "docker"
    return proc.find_executable("docker") or "docker"


def _docker_installed() -> bool:
    """Docker present on disk — CLI on PATH OR the Docker Desktop app — even if the engine is down."""
    return proc.find_executable("docker") is not None or _docker_desktop_exe() is not None or (
        sys.platform == "win32"
        and Path(os.environ.get("ProgramFiles", r"C:\Program Files"),
                 "Docker", "Docker", "resources", "bin", "docker.exe").is_file()
    )


def start_docker_desktop() -> bool:
    """Launch Docker Desktop if it's installed. Returns True if a launch was attempted."""
    try:
        if sys.platform == "darwin":
            if _docker_desktop_exe() is None:
                return False
            proc.popen(["open", "-a", "Docker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        exe = _docker_desktop_exe()
        if exe is not None:
            proc.popen([str(exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:  # noqa: BLE001 — best effort; caller falls back to the setup dialog
        log.warning("could not launch Docker Desktop", exc_info=True)
    return False


def wait_docker_ready(timeout_s: int = 150) -> bool:
    """Poll `docker info` until the engine answers (Docker Desktop can take a minute to boot)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if _docker("info", timeout=10).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(3)
    return False


def _docker(*args: str, timeout: int = _RUN_TIMEOUT) -> subprocess.CompletedProcess:
    return proc.run(
        [_docker_bin(), *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def docker_state() -> str:
    """"ready" (engine answering), "stopped" (Docker installed, engine down), or "missing".

    Detects Docker Desktop on disk, not just the CLI on PATH — a packaged app's minimal PATH
    (and a not-yet-started engine) otherwise made Orrery ask users to install Docker they had."""
    if not _docker_installed():
        return "missing"
    try:
        probe = _docker("info")
    except (OSError, subprocess.TimeoutExpired):
        return "stopped"
    return "ready" if probe.returncode == 0 else "stopped"


def _container_exists() -> bool:
    try:
        listed = _docker("ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Names}}")
    except (OSError, subprocess.TimeoutExpired):
        return False
    return CONTAINER in (listed.stdout or "").split()


def _wait_ready(timeout_s: int = 120) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            probe = _docker("exec", CONTAINER, "pg_isready", "-U", "orrery", "-d", "orrery")
            if probe.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(2)
    return False


def provision() -> str | None:
    """Start (or create) the bundled PostgreSQL and return its URL, or None with a marker printed.

    print() goes to the desktop shell's backend log, which is what surfaces the right
    next step to the user — keep the markers first on their line."""
    state = docker_state()
    if state == "missing":
        print(f"{MARKER_DOCKER_MISSING} Docker Desktop is not installed; cannot start the bundled database.", flush=True)
        return None
    if state == "stopped":
        # Docker Desktop is installed but the engine is down — START it and wait, per "if it
        # exists, start and run it", instead of asking the user to do it and reopen Orrery.
        log.info("Docker engine is down; starting Docker Desktop and waiting for it to be ready")
        print("Starting Docker Desktop and waiting for it to be ready (first start can take a minute)...", flush=True)
        if not start_docker_desktop() or not wait_docker_ready():
            print(f"{MARKER_DOCKER_STOPPED} Docker Desktop is installed but could not be started automatically; start it and reopen Orrery.", flush=True)
            return None

    try:
        if _container_exists():
            log.info("Bundled database container exists; starting it")
            started = _docker("start", CONTAINER)
            ok = started.returncode == 0
        else:
            log.info("Creating the bundled database container (first run may pull the image)")
            print("First run: downloading the bundled PostgreSQL image (one time, a few minutes)...", flush=True)
            created = proc.run(run_args(), capture_output=True, text=True, timeout=600, check=False)
            ok = created.returncode == 0
            if not ok:
                log.error("docker run failed: %s", (created.stderr or "")[-400:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.error("Docker call failed: %s", exc)
        ok = False

    if ok and _wait_ready():
        log.info("Bundled PostgreSQL is ready")
        return DEFAULT_URL

    print(f"{MARKER_PROVISION_FAILED} The bundled database could not be started; open Docker Desktop and retry, or set your own connection string in Settings.", flush=True)
    return None
