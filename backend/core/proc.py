"""Windowless subprocess helpers.

The desktop app runs under pythonw.exe, which has no console. Without CREATE_NO_WINDOW, every
child process (claude/codex/gemini/docker/ollama probes) briefly pops up its own console window —
a visible flash whenever the model picker or status checks run. These wrappers suppress that.
"""

from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _inject(kwargs: dict) -> dict:
    if CREATE_NO_WINDOW:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
    return kwargs


def run(*args, **kwargs):
    """subprocess.run with no flashing console window on Windows."""
    return subprocess.run(*args, **_inject(kwargs))


def popen(*args, **kwargs):
    """subprocess.Popen with no flashing console window on Windows."""
    return subprocess.Popen(*args, **_inject(kwargs))
