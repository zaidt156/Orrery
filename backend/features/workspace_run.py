"""Running a command in the attached folder.

This is where Orrery Work stops being safe by construction. ADR-007 says it plainly and it is worth
repeating at the top of the file that implements it: **path confinement bounds where files are
touched, not what a process may do once it is running.** A command here has the user's privileges
and the user's toolchain. `pip install`, `git push`, anything reaching the network — none of that is
prevented by resolving a path, and no amount of care in this module changes that.

What this module actually promises, and what its tests hold it to:

- It runs **in the root**, always, with the root as the working directory.
- It **stops when told**, and the whole process tree stops — killing the shell and leaving its
  children is how a "stopped" command keeps writing to the user's folder minutes later.
- It **stops on its own** eventually, because a command with no timeout is a hung turn.
- Its **output is bounded**, keeping the end as well as the beginning: a failing build prints
  thousands of lines and then the reason, and head-only truncation throws away the only part
  anyone wanted.
- Its **failures are data**. A non-zero exit is a result, not an exception.
- **Orrery's own secrets do not ride along** in the environment it inherits.

The deny-list at the bottom is not a security boundary and does not pretend to be — anyone who wants
past it walks past it. It is there for the likely case rather than the adversarial one: a model that
has misunderstood the task and reached for something that destroys the machine.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from backend.core import proc

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 900
MAX_STDOUT_CHARS = 40_000
MAX_STDERR_CHARS = 20_000
# How much of a truncated stream is kept from the front. The rest comes from the end, because that
# is where a failure explains itself.
_HEAD_SHARE = 0.6
_TRUNCATION_NOTE = "\n\n… [output truncated by Orrery] …\n\n"

# Orrery's own configuration, which the spawned command has no business seeing. The user's real
# environment is inherited on purpose — that is what "like a normal terminal" means — but Orrery
# being the parent process should not silently hand its credentials to every command it runs.
_SCRUBBED_ENV_EXACT = frozenset({"DATABASE_URL", "ORRERY_TOKEN", "ORRERY_ADMIN_TOKEN"})
_SCRUBBED_ENV_PREFIXES = ("ORRERY_",)


class RefusedCommand(ValueError):
    """The command was not run because it destroys the machine rather than doing work in a folder."""


async def run_command(root: Path | str, command: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run one command with `root` as its working directory and return what happened."""
    text = (command or "").strip()
    if not text:
        raise ValueError("There is no command to run.")
    if not 1 <= int(timeout) <= MAX_TIMEOUT:
        raise ValueError(f"A command's time limit must be between 1 and {MAX_TIMEOUT} seconds.")
    if refuses(text):
        raise RefusedCommand(
            "That command destroys the machine rather than doing work in a folder, so it was not run."
        )

    cwd = Path(str(root)).resolve(strict=False)
    if not cwd.is_dir():
        raise ValueError("The attached folder is no longer there.")

    shell_name, argv = _shell_for(text)
    started = time.perf_counter()
    process = await asyncio.to_thread(_spawn, argv, cwd)
    try:
        stdout, stderr, timed_out = await asyncio.to_thread(_wait, process, timeout)
    except asyncio.CancelledError:
        # The turn was stopped. Cancellation is honoured HERE, at the tool boundary, rather than
        # only in the UI — otherwise "stop" leaves a process still changing the user's files. The
        # worker thread is still blocked in communicate(); killing the tree is what releases it.
        #
        # Handed to a plain daemon thread rather than awaited: awaiting anything while a task is
        # being cancelled is fragile — a second cancel, or a loop already shutting down, and the
        # cleanup never runs. The kill has to happen whatever the loop does next.
        threading.Thread(target=_terminate_tree, args=(process,), daemon=True).start()
        raise

    out_text, out_cut = _bounded(stdout, MAX_STDOUT_CHARS)
    err_text, err_cut = _bounded(stderr, MAX_STDERR_CHARS)
    return {
        "command": text,
        "shell": shell_name,
        "cwd": str(cwd),
        "exit_code": process.returncode if process.returncode is not None else -1,
        "timed_out": timed_out,
        "stdout": out_text,
        "stderr": err_text,
        "truncated": out_cut or err_cut,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


# --- spawning and waiting, in a worker thread -----------------------------------------------------
#
# Blocking `subprocess` in a thread, NOT `asyncio.create_subprocess_exec`. On Windows the app runs
# the *Selector* event loop because psycopg async requires it (see app.py), and the Selector loop
# does not implement subprocesses at all — the asyncio spelling raises NotImplementedError in the
# one configuration the app actually ships on. This is the same pattern every other CLI call in
# Orrery uses, for the same reason.

def _spawn(argv: list[str], cwd: Path):
    return proc.popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,  # a command that waits for input would hang forever
        env=_child_environment(),
        **_process_group_flags(),
    )


def _wait(process, timeout: int) -> tuple[bytes, bytes, bool]:
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return stdout, stderr, False
    except subprocess.TimeoutExpired:
        _terminate_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except Exception:  # noqa: BLE001 - the timeout itself is the result worth reporting
            stdout, stderr = b"", b""
        return stdout, stderr, True


# --- the shell ------------------------------------------------------------------------------------

def _shell_for(command: str) -> tuple[str, list[str]]:
    """Which interpreter runs this, reported alongside the result.

    "Run a command" means nothing without saying what read it — the same line does different things
    in bash, PowerShell and cmd. bash is preferred where it exists because that is what people write
    and what the user asked for; Windows without it falls back to PowerShell, which is the shell that
    machine actually has.

    `-c`, not `-lc`. A login shell sources profiles, and a profile is free to change the working
    directory — which would quietly move the command out of the attached folder, breaking the one
    thing this module actually guarantees. The parent's environment is inherited either way, so the
    user's toolchain is still visible, and Windows now behaves the same way as the POSIX branch.
    """
    if sys.platform != "win32":
        return "sh", ["/bin/sh", "-c", command]
    bash = _windows_bash()
    if bash:
        return "bash", [bash, "-c", command]
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell:
        return "powershell", [powershell, "-NoProfile", "-NonInteractive", "-Command", command]
    return "cmd", [os.environ.get("COMSPEC", "cmd.exe"), "/c", command]


def _windows_bash() -> str | None:
    """Git Bash, if it is there — but never the WSL launcher.

    `C:\\Windows\\System32\\bash.exe` is not a shell, it is the entry point into a Linux distribution
    with its own filesystem. A command sent through it runs somewhere else entirely: the attached
    folder does not exist at that path (it would be `/mnt/c/...`), so the working directory Orrery
    just resolved and promised is simply not where the command lands. That is worse than having no
    bash at all, because it looks like it worked.
    """
    found = proc.find_executable("bash") or shutil.which("bash")
    if not found:
        return None
    try:
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve(strict=False)
        resolved = Path(found).resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    if resolved.is_relative_to(system_root):
        return None  # the WSL launcher, or something else pretending to be a shell
    return found


def _child_environment() -> dict[str, str]:
    """The user's environment, minus Orrery's own configuration."""
    return {
        key: value for key, value in os.environ.items()
        if key not in _SCRUBBED_ENV_EXACT and not key.startswith(_SCRUBBED_ENV_PREFIXES)
    }


# --- stopping it ----------------------------------------------------------------------------------

def _process_group_flags() -> dict:
    """Put the command in its own group so the whole tree can be killed, not just the shell."""
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def _terminate_tree(process) -> None:
    """Kill the command and everything it started.

    A shell spawns children, and those children spawn their own. Killing the shell alone leaves a
    build or a dev server running against the user's folder long after Orrery reported it stopped,
    which is worse than never having offered to stop it.
    """
    if process.returncode is not None:
        return
    if sys.platform == "win32":
        # taskkill /T is the only reliable way to reach a whole tree on Windows; there is no
        # process-group signal that children inherit the way they do on POSIX.
        with contextlib.suppress(Exception):
            proc.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                     capture_output=True, timeout=10)
    else:
        import signal
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    with contextlib.suppress(Exception):
        process.kill()
    with contextlib.suppress(Exception):
        process.wait(timeout=5)


# --- bounding what comes back ---------------------------------------------------------------------

def _bounded(raw: bytes, limit: int) -> tuple[str, bool]:
    text = (raw or b"").decode("utf-8", "replace")
    if len(text) <= limit:
        return text, False
    head = int(limit * _HEAD_SHARE)
    tail = limit - head - len(_TRUNCATION_NOTE)
    if tail <= 0:
        return text[:limit], True
    return f"{text[:head]}{_TRUNCATION_NOTE}{text[-tail:]}", True


# --- the accident guard -----------------------------------------------------------------------------

# Commands whose purpose is destroying the machine, not doing work in a folder. This is a guard
# against a model that has misunderstood its task, NOT a security boundary: a deny-list of patterns
# is trivially walked past by anyone trying, and ADR-007 is honest that a running process is not
# confined at all. Catching none of the obvious cases because it cannot catch all cases would be the
# wrong conclusion.
#
# It is deliberately narrow. A deny-list that catches real work — `rm -rf node_modules` is exactly
# what people mean — is a deny-list people turn off, and then it catches nothing.
_CATASTROPHIC = (
    # rm -rf against a filesystem root or a home directory (not a project subdirectory)
    re.compile(r"\brm\s+(-[a-z]*\s+)*-[a-z]*[rR][a-z]*[fF]?[a-z]*\s+(--no-preserve-root\s+)*[/~]\s*\*?\s*($|[;&|])"),
    re.compile(r"\brm\s+(-[a-z]*\s+)*-[a-z]*[fF][a-z]*[rR][a-z]*\s+(--no-preserve-root\s+)*[/~]\s*\*?\s*($|[;&|])"),
    re.compile(r"--no-preserve-root"),
    re.compile(r"\bmkfs(\.\w+)?\b"),                       # reformat a filesystem
    re.compile(r"\bdd\b[^\n|;&]*\bof=/dev/(sd|nvme|hd|disk)"),  # write straight to a disk device
    re.compile(r">\s*/dev/(sd|nvme|hd|disk)\w*"),
    re.compile(r":\s*\(\s*\)\s*\{.*\|.*&.*\}\s*;\s*:"),    # the classic fork bomb
    re.compile(r"\bchmod\s+(-[a-zA-Z]+\s+)*0*777\s+/\s*($|[;&|])"),
    # Windows-shaped versions of the same intent
    re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),
    re.compile(r"\bdel\s+/[a-zA-Z]\s.*[a-zA-Z]:\\\*", re.IGNORECASE),
    re.compile(r"Remove-Item\b[^\n]*\s[a-zA-Z]:\\+\s*($|[;&|])", re.IGNORECASE),
    re.compile(r"\bvssadmin\s+delete\s+shadows", re.IGNORECASE),   # ransomware's first move
    re.compile(r"\bcipher\s+/w", re.IGNORECASE),                   # wipe free space
)


def refuses(command: str) -> bool:
    """True when a command destroys the machine rather than doing work in a folder."""
    text = " ".join((command or "").split())
    return any(pattern.search(text) for pattern in _CATASTROPHIC)
