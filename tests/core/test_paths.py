import sys
from pathlib import Path

from backend.core import paths


def test_macos_frozen_app_dir_is_folder_beside_app(monkeypatch):
    executable = Path("C:/packages/Orrery-macOS/Orrery.app/Contents/MacOS/Orrery")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert paths.app_dir() == Path("C:/packages/Orrery-macOS")


def test_non_macos_frozen_app_dir_is_executable_parent(monkeypatch):
    executable = Path("C:/Orrery-Windows/Orrery.exe")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert paths.app_dir() == executable.parent
