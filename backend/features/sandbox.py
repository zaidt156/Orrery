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
import uuid
from dataclasses import dataclass, field
from pathlib import Path

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


def image_ready() -> bool:
    """True once the sandbox image has been built and is available locally."""
    try:
        result = proc.run(
            [_docker_bin(), "image", "inspect", IMAGE],
            capture_output=True, timeout=25,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001 — any failure means "not ready"
        return False


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


def run_code(code: str) -> SandboxResult:
    """Run Python in the sandbox and return its logs plus any files it wrote to out/."""
    if not code or not code.strip():
        raise SandboxError("There is no code to run.")
    if len(code) > _MAX_CODE_CHARS:
        raise SandboxError("The generated code is too large to run.")

    workdir = Path(tempfile.mkdtemp(prefix="orrery-sbx-"))
    out_dir = workdir / "out"
    out_dir.mkdir()
    (workdir / "main.py").write_text(code, encoding="utf-8")
    name = f"orrery-sbx-{uuid.uuid4().hex[:12]}"

    command = [
        _docker_bin(), "run", "--rm", "--name", name,
        "--network", "none",
        "--memory", _MEMORY, "--memory-swap", _MEMORY,
        "--cpus", _CPUS, "--pids-limit", _PIDS,
        "--read-only", "--tmpfs", "/tmp:size=256m,exec",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "1000:1000",
        "-v", f"{workdir}:/work", "-w", "/work",
        IMAGE, "python", "main.py",
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

    return SandboxResult(
        ok=(exit_code == 0 and not timed_out),
        stdout=stdout, stderr=stderr, exit_code=exit_code, timed_out=timed_out, files=files,
    )
