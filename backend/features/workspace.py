"""Orrery Work's path boundary — the one seam every workspace tool resolves through.

ADR-007 chose host execution and direct writes, which trades isolation for confinement: nothing
stops a command from using the user's real toolchain, so the guarantee Orrery *can* make is that no
read, write, glob, grep or command target ever resolves outside the attached folder.

That makes this module security-critical, and it has one rule worth stating loudly:

    Resolve the real path FIRST, then check it.

Checking a string and resolving afterwards is the classic ordering bug — `escape/keys.txt` looks
like a child of the root right up until `escape` turns out to be a symlink to somewhere else. Every
check below runs on a fully resolved path, and containment is compared by path *components*, never
by string prefix, because `/tmp/project-evil` starts with `/tmp/project` and is not inside it.

Every tool goes through `resolve_in_root`. No tool does its own path arithmetic: a second, weaker
check written later is exactly how the hole gets made.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePath

# Bypass normal path semantics entirely: Win32 device namespace, and UNC network shares. Refused on
# every platform rather than only on Windows, so a POSIX host cannot be used to smuggle one through
# into a config or a database row that a Windows host later resolves.
_DEVICE_OR_UNC = re.compile(r"^[\\/]{2}")


class PathOutsideRoot(ValueError):
    """A workspace path resolved outside its root, or could not be resolved safely."""


def resolve_in_root(root: Path | str, candidate: str | None) -> Path:
    """Resolve `candidate` against `root` and return it, or raise `PathOutsideRoot`.

    The candidate may be relative to the root or absolute inside it, may use either separator, and
    need not exist yet — creating a file requires resolving a target that is not there. What it may
    never do is land outside the root once every link in it has been followed.
    """
    if candidate is None:
        raise PathOutsideRoot("No path was given.")
    text = str(candidate).strip()
    if not text:
        raise PathOutsideRoot("No path was given.")
    if "\x00" in text:
        # A NUL truncates the path in some C-level consumers, so what is checked and what is opened
        # can differ. Refuse rather than reason about which layer wins.
        raise PathOutsideRoot("Path contains a null byte.")
    if _DEVICE_OR_UNC.match(text):
        raise PathOutsideRoot("Device and network paths are not allowed in a workspace.")

    text = text.replace("\\", "/")
    base = _resolved_root(root)

    target = PurePath(text)
    resolved = _resolve(Path(text) if target.is_absolute() else base / text)

    if not _is_within(resolved, base):
        raise PathOutsideRoot("Path resolves outside the attached folder.")
    return resolved


def _resolved_root(root: Path | str) -> Path:
    base = _resolve(Path(str(root)))
    if not base.is_absolute():
        raise PathOutsideRoot("The workspace root must be an absolute path.")
    return base


def _resolve(path: Path) -> Path:
    """Fully resolve a path, following links, whether or not the leaf exists.

    `strict=False` resolves as much of the path as exists and appends the rest literally, which is
    what makes "create a file that is not there yet" work while still following any link in the
    directories above it.
    """
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:  # loops, permission failures, malformed paths
        raise PathOutsideRoot("Path could not be resolved safely.") from exc


def _is_within(candidate: Path, base: Path) -> bool:
    """Containment by path components, never by string prefix.

    `Path.is_relative_to` compares parts, so `/tmp/project-evil` is correctly *not* inside
    `/tmp/project` — a `str.startswith` check would say it is, silently.
    """
    if candidate == base:
        return True
    try:
        return candidate.is_relative_to(base)
    except (ValueError, OSError):
        return False
