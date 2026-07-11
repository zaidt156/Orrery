"""Subprocess helpers shared by every CLI probe/call (claude, codex, gemini, docker, ollama…).

Two platform quirks live here so call sites stay clean:
- Windows: the app runs under pythonw.exe (no console); without CREATE_NO_WINDOW every child
  process briefly pops its own console window.
- macOS: a packaged .app launches with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), so bare
  names like "docker" are invisible even when installed — the cause of the "install Docker"
  loop on machines that HAVE Docker. Bare argv[0] names are resolved against the well-known
  install locations before spawning.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_MAC_BIN_DIRS = ("/usr/local/bin", "/opt/homebrew/bin")
_MAC_BUNDLE_BINS = {
    "docker": ("/Applications/Docker.app/Contents/Resources/bin/docker",),
    "ollama": ("/Applications/Ollama.app/Contents/Resources/ollama",),
    "soffice": ("/Applications/LibreOffice.app/Contents/MacOS/soffice",),
}


def find_executable(name: str) -> str | None:
    """shutil.which plus the well-known macOS locations a GUI app's minimal PATH misses."""
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "darwin":
        candidates = [f"{directory}/{name}" for directory in _MAC_BIN_DIRS]
        candidates += list(_MAC_BUNDLE_BINS.get(name, ()))
        for candidate in candidates:
            if Path(candidate).is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


def _resolve_argv(args: tuple) -> tuple:
    """macOS only: swap a bare argv[0] command name for its resolved absolute path."""
    if sys.platform != "darwin" or not args:
        return args
    argv = args[0]
    if isinstance(argv, (list, tuple)) and argv and isinstance(argv[0], str) and "/" not in argv[0]:
        resolved = find_executable(argv[0])
        if resolved and resolved != argv[0]:
            return ([resolved, *argv[1:]], *args[1:])
    return args


def _inject(kwargs: dict) -> dict:
    if CREATE_NO_WINDOW:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
    return kwargs


def run(*args, **kwargs):
    """subprocess.run — windowless on Windows, PATH-resilient on macOS."""
    return subprocess.run(*_resolve_argv(args), **_inject(kwargs))


def popen(*args, **kwargs):
    """subprocess.Popen — windowless on Windows, PATH-resilient on macOS."""
    return subprocess.Popen(*_resolve_argv(args), **_inject(kwargs))
