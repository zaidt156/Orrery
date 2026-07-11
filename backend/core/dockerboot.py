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
import subprocess
import time

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


def _docker(*args: str, timeout: int = _RUN_TIMEOUT) -> subprocess.CompletedProcess:
    return proc.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def docker_state() -> str:
    """"ready" (daemon answering), "stopped" (CLI present, daemon down), or "missing".

    find_executable (not bare which) — a packaged macOS app's minimal PATH can't see docker,
    which made Orrery ask users to install Docker they already had."""
    if proc.find_executable("docker") is None:
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
        print(f"{MARKER_DOCKER_STOPPED} Docker Desktop is installed but not running; start it and reopen Orrery.", flush=True)
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
