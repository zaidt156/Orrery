from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    """Repository root when running from source."""
    return Path(__file__).resolve().parents[2]


def bundle_dir() -> Path:
    """Read-only bundled resources location.

    In a PyInstaller onedir build this is the _internal directory. In source mode it is the
    repository root.
    """
    frozen_bundle = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and frozen_bundle:
        return Path(frozen_bundle).resolve()
    return project_root()


def app_dir() -> Path:
    """Writable application folder.

    In a packaged Windows/Linux build this is the folder beside the executable. In a packaged
    macOS .app bundle this is the folder beside Orrery.app, not Contents/MacOS inside the bundle.
    In source mode it is the repository root.
    """
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if (
            sys.platform == "darwin"
            and executable.parent.name == "MacOS"
            and executable.parent.parent.name == "Contents"
            and executable.parent.parent.parent.suffix == ".app"
        ):
            return executable.parent.parent.parent.parent
        return executable.parent
    return project_root()


def resource_path(*parts: str) -> Path:
    return bundle_dir().joinpath(*parts)


def runtime_path(*parts: str) -> Path:
    return app_dir().joinpath(*parts)


def user_data_dir() -> Path:
    """Return Orrery's upgrade-safe, per-user writable data directory.

    ``runtime_path`` remains for files intentionally colocated with a source checkout or portable
    build. Durable user state belongs here instead: installers may replace the application folder,
    and a signed macOS app bundle is read-only. ``ORRERY_DATA_DIR`` is an explicit development and
    managed-deployment override.
    """
    override = os.environ.get("ORRERY_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "Orrery"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Orrery"

    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return root / "orrery"


def settings_file() -> Path:
    """Configuration file location without making source development depend on installed paths."""
    override = os.environ.get("ORRERY_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return user_data_dir() / ".env"
    return runtime_path(".env")
