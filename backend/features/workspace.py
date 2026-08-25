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


# --- reading an attached folder -------------------------------------------------------------------
#
# These three cannot damage anything, which is why they are built before the ones that can. That
# does not make them harmless: a read that follows a link out of the root exfiltrates whatever it
# lands on, and a search that walks `node_modules` hangs the turn. Both are bounded here, and every
# bound that bites says so in the result — a model handed a silently filtered list concludes the
# files do not exist, which is a worse failure than being told the list was cut short.

MAX_READ_BYTES = 200_000      # a file larger than this is summarised by its head, not withheld
MAX_FIND_RESULTS = 500
MAX_GREP_MATCHES = 200
MAX_LINE_CHARS = 500          # one minified bundle should not fill the model's context
MAX_SCANNED_FILES = 20_000    # a backstop for a pattern that matches the whole disk
# A file bigger than this is not searched. The bound has to hold on the way IN: capping the output
# after reading the file caps what the model sees and not what the process pays, and an attached
# folder with a multi-gigabyte log in it would be a crash rather than a slow search.
MAX_GREP_FILE_BYTES = 2_000_000

# Directories nobody means when they say "search the project": version control internals, dependency
# trees, build output, caches. Skipped by default and named in the result. A pattern that mentions
# one explicitly opts back in, so this is a default rather than a wall.
SKIPPED_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".tox", ".gradle", "target",
})


def read_file(root: Path | str, path: str, *, max_bytes: int = MAX_READ_BYTES) -> dict:
    """One file's text, with its path relative to the root.

    Relative, not absolute: an absolute path tells the model where on the user's disk the folder
    lives, which is neither its business nor useful to it.
    """
    resolved = resolve_in_root(root, path)
    if resolved.is_dir():
        raise IsADirectoryError(f"{path} is a directory, not a file.")
    if not resolved.exists():
        raise FileNotFoundError(f"{path} does not exist in the attached folder.")

    size = resolved.stat().st_size
    # Read only what is wanted, plus one byte to tell "exactly full" from "there is more".
    with resolved.open("rb") as handle:
        raw = handle.read(max(0, int(max_bytes)) + 1)
    truncated = len(raw) > max_bytes
    raw = raw[:max_bytes]
    if _looks_binary(raw):
        raise ValueError(f"{path} is a binary file, so there is no text to read.")
    return {
        "path": _relative(resolved, root),
        "text": raw.decode("utf-8", "replace"),
        "size": size,
        "truncated": truncated,
    }


def find(root: Path | str, pattern: str, *, limit: int = MAX_FIND_RESULTS) -> dict:
    """Paths matching a glob, relative to the root, sorted."""
    base = _resolved_root(root)
    _reject_escaping_pattern(base, pattern)
    wanted = _explicitly_wanted(pattern)

    paths: list[str] = []
    skipped: set[str] = set()
    truncated = False
    for scanned, candidate in enumerate(base.glob(pattern)):
        if scanned >= MAX_SCANNED_FILES:
            truncated = True
            break
        hidden = _skipped_ancestor(candidate, base, wanted)
        if hidden:
            skipped.add(hidden)
            continue
        if not candidate.is_file():
            continue
        try:  # a glob can still surface a link that leaves the root
            resolve_in_root(base, str(candidate))
        except PathOutsideRoot:
            continue
        if len(paths) >= limit:
            truncated = True
            break
        paths.append(_relative(candidate, base))
    return {"paths": sorted(paths), "skipped": sorted(skipped), "truncated": truncated}


def grep(root: Path | str, expression: str, *, glob: str = "**/*",
         limit: int = MAX_GREP_MATCHES) -> dict:
    """Lines matching a regular expression, as `{path, line, text}`."""
    try:
        rx = re.compile(expression)
    except re.error as exc:
        raise ValueError(f"That search expression isn't valid: {exc}") from None

    found = find(root, glob, limit=MAX_SCANNED_FILES)
    base = _resolved_root(root)
    matches: list[dict] = []
    skipped_files: list[str] = []
    truncated = found["truncated"]
    for relative in found["paths"]:
        if len(matches) >= limit:
            truncated = True
            break
        target = base / relative
        try:
            if target.stat().st_size > MAX_GREP_FILE_BYTES:
                skipped_files.append(relative)  # named, because a silent skip reads as "no match"
                continue
            raw = target.read_bytes()
        except OSError:
            continue
        if _looks_binary(raw):
            continue  # matching inside a binary produces noise, not answers
        for number, line in enumerate(raw.decode("utf-8", "replace").splitlines(), start=1):
            if len(matches) >= limit:
                truncated = True
                break
            if rx.search(line):
                matches.append({"path": relative, "line": number, "text": line[:MAX_LINE_CHARS]})
    return {"matches": matches, "skipped": found["skipped"],
            "skipped_files": skipped_files, "truncated": truncated}


def _relative(path: Path, root: Path | str) -> str:
    return path.relative_to(_resolved_root(root)).as_posix()


def _looks_binary(raw: bytes) -> bool:
    """A NUL byte in the first block is the same test `grep` itself uses, and it is good enough."""
    return b"\x00" in raw[:8192]


def _reject_escaping_pattern(base: Path, pattern: str) -> None:
    """A glob is not a path, so `resolve_in_root` can't vet it directly — vet its literal head.

    Everything up to the first wildcard is a real path, and if that already leaves the root then no
    amount of matching afterwards brings it back.
    """
    head = pattern.replace("\\", "/").split("*", 1)[0].split("?", 1)[0].split("[", 1)[0]
    head = head.rsplit("/", 1)[0] if "/" in head else ""
    resolve_in_root(base, head or ".")


def _explicitly_wanted(pattern: str) -> set[str]:
    """Skipped directories named in the pattern itself. Asking for them is asking for them."""
    parts = {p for p in pattern.replace("\\", "/").split("/") if p}
    return parts & SKIPPED_DIRS


def _skipped_ancestor(candidate: Path, base: Path, wanted: set[str]) -> str | None:
    try:
        parts = candidate.relative_to(base).parts
    except ValueError:
        return None
    for part in parts[:-1] if candidate.is_file() else parts:
        if part in SKIPPED_DIRS and part not in wanted:
            return part
    return None


# --- choosing a folder ----------------------------------------------------------------------------
#
# ADR-007 rests the entire security model on one sentence: the attached folder is the boundary.
# That sentence is worth exactly as much as the folder is specific. Attach the whole disk and
# confinement still holds perfectly — every path resolves inside the root, every check passes, and
# the model has everything. The guarantee is not weakened, it is emptied.
#
# So this runs once, at the only moment it can matter: when the folder is chosen.

class UnattachableRoot(ValueError):
    """The chosen folder cannot be a workspace root."""


# Directories whose contents are the system, or somebody's whole life, rather than a project.
_POSIX_SYSTEM_ROOTS = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/var", "/boot", "/dev", "/proc",
                       "/sys", "/System", "/Library", "/Applications", "/private")
_WINDOWS_SYSTEM_NAMES = ("windows", "program files", "program files (x86)", "programdata",
                         "system32", "$recycle.bin")


def check_attachable(candidate: Path | str) -> Path:
    """Return the resolved folder, or explain why it cannot be attached.

    Refusals name what to do instead: a rejection the user can't act on reads as a broken app.
    """
    path = Path(str(candidate).strip())
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        raise UnattachableRoot("That folder could not be opened. Pick another folder.") from None

    if not resolved.exists():
        raise UnattachableRoot("That folder does not exist. Pick a folder that is already there.")
    if not resolved.is_dir():
        raise UnattachableRoot("That is a file, not a folder. Attach the folder that contains it.")

    if resolved.parent == resolved:  # a drive root or "/"
        raise UnattachableRoot(
            "That is the whole drive. Attach the project folder you want worked on, not the disk."
        )
    if _is_home_itself(resolved):
        raise UnattachableRoot(
            "That is your home folder, which holds everything you have. Attach one project inside it."
        )
    if _is_system_directory(resolved):
        raise UnattachableRoot(
            "That folder belongs to the operating system. Attach a project folder instead."
        )
    return resolved


def _is_home_itself(resolved: Path) -> bool:
    """The home directory, not its contents — its subfolders are what people mean to attach."""
    try:
        return resolved == Path.home().resolve(strict=False)
    except (OSError, RuntimeError):
        return False


def _is_system_directory(resolved: Path) -> bool:
    text = resolved.as_posix()
    if any(text == root or text.startswith(f"{root}/") for root in _POSIX_SYSTEM_ROOTS):
        return True
    parts = [p.lower() for p in resolved.parts]
    return any(name in parts for name in _WINDOWS_SYSTEM_NAMES)
