import os
import sys
from pathlib import Path

from backend.core import paths

# These simulate a frozen bundle, so the fake executable path has to be ABSOLUTE on the machine
# running the test. "C:/..." is absolute on Windows but a relative path on Linux and macOS, where
# app_dir() then resolves it against the working directory and the assertion drifts.
FAKE_ROOT = Path("C:/") if os.name == "nt" else Path("/")


def test_macos_frozen_app_dir_is_folder_beside_app(monkeypatch):
    bundle = FAKE_ROOT / "packages" / "Orrery-macOS"
    executable = bundle / "Orrery.app" / "Contents" / "MacOS" / "Orrery"

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert paths.app_dir() == bundle


def test_non_macos_frozen_app_dir_is_executable_parent(monkeypatch):
    executable = FAKE_ROOT / "Orrery-Windows" / "Orrery.exe"

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert paths.app_dir() == executable.parent


def test_user_data_dir_honors_explicit_override(monkeypatch, tmp_path):
    target = tmp_path / "private-orrery-data"
    monkeypatch.setenv("ORRERY_DATA_DIR", str(target))

    assert paths.user_data_dir() == target


def test_windows_user_data_dir_is_outside_install(monkeypatch):
    monkeypatch.delenv("ORRERY_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/Ada/AppData/Local")
    monkeypatch.setattr(sys, "platform", "win32")

    assert paths.user_data_dir() == Path("C:/Users/Ada/AppData/Local/Orrery")


def test_macos_user_data_dir_uses_application_support(monkeypatch):
    monkeypatch.delenv("ORRERY_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/ada")))

    assert paths.user_data_dir() == Path("/Users/ada/Library/Application Support/Orrery")


def test_linux_user_data_dir_uses_xdg(monkeypatch):
    monkeypatch.delenv("ORRERY_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "/home/ada/.data")
    monkeypatch.setattr(sys, "platform", "linux")

    assert paths.user_data_dir() == Path("/home/ada/.data/orrery")


def test_frozen_settings_file_is_upgrade_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("ORRERY_DATA_DIR", str(tmp_path / "user-data"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert paths.settings_file() == tmp_path / "user-data" / ".env"


def test_source_settings_file_remains_the_project_env(monkeypatch):
    monkeypatch.delenv("ORRERY_DATA_DIR", raising=False)
    monkeypatch.delenv("ORRERY_ENV_FILE", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert paths.settings_file() == paths.project_root() / ".env"
