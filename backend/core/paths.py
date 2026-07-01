from __future__ import annotations

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
