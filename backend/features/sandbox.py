"""Sandboxed code execution — the ChatGPT/Claude "code interpreter" path.

Model-written Python runs inside a throwaway Docker container that is locked down hard:
no network, capped memory/CPU/PIDs, read-only root filesystem, non-root user, all Linux
capabilities dropped, no privilege escalation, and a wall-clock timeout. The only writable
surface is a per-run host temp dir mounted at /work; we hand back whatever files the code
writes to /work/out plus its stdout/stderr. Nothing the model writes touches the host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.core import proc
from backend.core.config import settings

IMAGE = "orrery-sandbox:latest"
TIMEOUT_SECONDS = settings.sandbox_timeout_seconds
_MEMORY = "640m"
_CPUS = "1.0"
_PIDS = "256"
_MAX_OUTPUT_FILES = 12
_MAX_TOTAL_OUTPUT_BYTES = 30_000_000
_MAX_FILE_BYTES = 25_000_000
_MAX_LOG_CHARS = 6_000
_MAX_CODE_CHARS = 200_000
_LAYOUT = {
    "root": "/work",
    "input": "/work/input",
    "workspace": "/work/workspace",
    "output": "/work/out",
}


def _docker_bin() -> str:
    candidate = os.environ.get("ORRERY_DOCKER", r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
    return candidate if Path(candidate).exists() else "docker"


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxFile:
    name: str
    data: bytes


@dataclass
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    files: list[SandboxFile] = field(default_factory=list)
    run_id: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)


# The readiness probe shells out to `docker image inspect`, which is slow (and blocks the
# event loop from its async callers) and is hit several times per chat turn. The image state
# changes rarely, so cache the answer per process: a present image is trusted for longer,
# while an absent one is re-checked sooner so a just-started Docker Desktop is picked up
# quickly. Degrades safely either way — a stale "ready" that fails just falls back to docgen.
_READY_TTL_OK = 30.0
_READY_TTL_MISS = 5.0
_ready_cache: tuple[bool, float] | None = None  # (value, monotonic expiry)


def _probe_image_ready() -> bool:
    try:
        result = proc.run(
            [_docker_bin(), "image", "inspect", IMAGE],
            capture_output=True, timeout=25,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001 — any failure means "not ready"
        return False


def image_ready(*, refresh: bool = False) -> bool:
    """True once the sandbox image has been built and is available locally (briefly cached)."""
    global _ready_cache
    now = time.monotonic()
    if not refresh and _ready_cache is not None and now < _ready_cache[1]:
        return _ready_cache[0]
    value = _probe_image_ready()
    _ready_cache = (value, now + (_READY_TTL_OK if value else _READY_TTL_MISS))
    return value


def _collect_outputs(out_dir: Path) -> list[SandboxFile]:
    files: list[SandboxFile] = []
    total = 0
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size == 0 or size > _MAX_FILE_BYTES:
            continue
        if len(files) >= _MAX_OUTPUT_FILES or total + size > _MAX_TOTAL_OUTPUT_BYTES:
            break
        files.append(SandboxFile(name=path.name, data=path.read_bytes()))
        total += size
    return files


def _build_manifest(
    run_id: str,
    *,
    ok: bool,
    exit_code: int,
    timed_out: bool,
    files: list[SandboxFile],
) -> dict[str, Any]:
    """Public, sanitized run metadata. Never include generated code, logs, prompts, or secrets."""
    return {
        "run_id": run_id,
        "engine": "docker",
        "image": IMAGE,
        "layout": dict(_LAYOUT),
        "limits": {
            "timeout_seconds": TIMEOUT_SECONDS,
            "memory": _MEMORY,
            "cpus": _CPUS,
            "pids": _PIDS,
            "max_output_files": _MAX_OUTPUT_FILES,
            "max_total_output_bytes": _MAX_TOTAL_OUTPUT_BYTES,
            "max_file_bytes": _MAX_FILE_BYTES,
        },
        "status": {
            "ok": ok,
            "exit_code": exit_code,
            "timed_out": timed_out,
        },
        "outputs": [
            {
                "name": file.name,
                "size": len(file.data),
            }
            for file in files
        ],
    }


def run_code(code: str) -> SandboxResult:
    """Run Python in the sandbox and return its logs plus any files it wrote to out/."""
    return _run_entry(code, "main.py", ["python", "main.py"])


def run_shell(script: str) -> SandboxResult:
    """Run a shell script in the SAME hardened container (no network, read-only root, dropped caps,
    non-root, cpu/memory/pids caps). Shell adds no exposure Python didn't already have inside the
    box — it just lets the model use the container's CLI tools directly."""
    return _run_entry(script, "script.sh", ["sh", "script.sh"])


def _run_entry(entry_content: str, entry_name: str, argv: list[str]) -> SandboxResult:
    if not entry_content or not entry_content.strip():
        raise SandboxError("There is no code to run.")
    if len(entry_content) > _MAX_CODE_CHARS:
        raise SandboxError("The generated code is too large to run.")

    run_id = uuid.uuid4().hex[:12]
    workdir = Path(tempfile.mkdtemp(prefix=f"orrery-sbx-{run_id}-"))
    input_dir = workdir / "input"
    workspace_dir = workdir / "workspace"
    out_dir = workdir / "out"
    input_dir.mkdir()
    workspace_dir.mkdir()
    out_dir.mkdir()
    (workdir / entry_name).write_text(entry_content, encoding="utf-8", newline="\n")
    name = f"orrery-sbx-{run_id}"

    command = [
        _docker_bin(), "run", "--rm", "--name", name,
        "--network", "none",
        "--memory", _MEMORY, "--memory-swap", _MEMORY,
        "--cpus", _CPUS, "--pids-limit", _PIDS,
        "--read-only", "--tmpfs", "/tmp:size=256m,exec",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "1000:1000",
        "-v", f"{workdir}:/work", "-w", "/work",
        IMAGE, *argv,
    ]

    timed_out = False
    stdout = stderr = ""
    exit_code = -1
    try:
        completed = proc.run(command, capture_output=True, timeout=TIMEOUT_SECONDS)
        exit_code = completed.returncode
        stdout = completed.stdout.decode("utf-8", "replace")[:_MAX_LOG_CHARS]
        stderr = completed.stderr.decode("utf-8", "replace")[:_MAX_LOG_CHARS]
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or b"").decode("utf-8", "replace")[:_MAX_LOG_CHARS] if exc.stdout else ""
        stderr = f"Execution exceeded the {TIMEOUT_SECONDS}s limit and was stopped."
        proc.run([_docker_bin(), "kill", name], capture_output=True, timeout=25)
    except FileNotFoundError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise SandboxError("Docker was not found. Is Docker Desktop installed and running?") from exc

    try:
        files = _collect_outputs(out_dir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    ok = exit_code == 0 and not timed_out
    return SandboxResult(
        ok=ok,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        files=files,
        run_id=run_id,
        manifest=_build_manifest(run_id, ok=ok, exit_code=exit_code, timed_out=timed_out, files=files),
    )
