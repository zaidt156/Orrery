"""Changing files in the attached folder — the only irreversible thing Orrery Work does.

ADR-007 gave up diff-then-apply. The user chose direct writes, and that choice is defensible, but it
means a wrong edit is on disk with nothing staged to reject. What Orrery offers in exchange is a
record: every mutation described by path, action and content digest, so "what did it change" has an
answer that does not come from the model's own account of itself.

This module produces the *facts*. `workspace_log.py` makes them durable, and the tools in
`workspace_tools.py` join the two. The split is the same one used everywhere else in this feature:
the part that touches files has no database in it, so the dangerous code stays testable without one.

Three rules the tests hold this to:

**Every path goes through `resolve_in_root`.** No exceptions, no second check written later.

**A write is atomic.** Content goes to a temporary file beside the target and is then moved into
place, so a failure mid-write cannot leave a truncated file where a working one used to be. Losing
the new content is recoverable; losing the old content as well is not.

**An edit states what it saw.** `edit_file` takes the digest of the content the caller actually
read and refuses if the file has changed since. This is not concurrency theatre — it removes the
case where a model reads a file, thinks while a build or another edit rewrites it, and then writes
back something derived from a version that no longer exists.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from backend.features.workspace import relative_in_root, resolve_in_root

# A single write is a source file, not a dataset. The cap is checked before anything is opened, so
# an oversized write costs nothing and leaves nothing behind.
MAX_WRITE_BYTES = 10_000_000


class StaleContent(ValueError):
    """The file changed after the caller read it, so the edit was refused rather than applied."""


def digest_of(raw: bytes) -> str:
    """sha256 of the bytes.

    Of the bytes, deliberately, not of decoded text: line endings and encoding differences are real
    differences, and digesting the decoded string would call two genuinely different files identical.
    """
    return hashlib.sha256(raw).hexdigest()


def write_file(root: Path | str, path: str, content: str) -> dict:
    """Create or replace a file. Returns what changed, for the log."""
    resolved = resolve_in_root(root, path)
    raw = content.encode("utf-8")
    if len(raw) > MAX_WRITE_BYTES:
        raise ValueError(
            f"That content is too large to write ({len(raw):,} bytes; the limit is "
            f"{MAX_WRITE_BYTES:,})."
        )
    if resolved.is_dir():
        raise IsADirectoryError(f"{path} is a directory, not a file.")

    existed = resolved.exists()
    before = digest_of(resolved.read_bytes()) if existed else None
    resolved.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(resolved, raw)
    return _record(relative_in_root(root, resolved), "modified" if existed else "created",
                   before, digest_of(raw), len(raw))


def edit_file(root: Path | str, path: str, observed_digest: str, content: str) -> dict:
    """Replace a file's contents, but only if it still holds what the caller read."""
    resolved = resolve_in_root(root, path)
    if resolved.is_dir():
        raise IsADirectoryError(f"{path} is a directory, not a file.")
    if not resolved.exists():
        # An edit means "change what is there". Creating on a miss would let a mistyped path invent
        # a file somewhere nobody thinks to look.
        raise FileNotFoundError(f"{path} does not exist in the attached folder.")

    current = digest_of(resolved.read_bytes())
    if current != (observed_digest or ""):
        raise StaleContent(
            f"{path} has changed since it was read, so the edit was not applied — read it again "
            "and redo the change against the current contents."
        )
    return write_file(root, path, content)


def delete_file(root: Path | str, path: str) -> dict:
    """Remove one file.

    One file at a time, and never a directory. Removing a tree is a far larger action than a single
    log row can honestly describe, and it is available through `work_run`, where the user sees the
    command they are approving rather than a path.
    """
    resolved = resolve_in_root(root, path)
    if resolved.is_dir():
        raise IsADirectoryError(
            f"{path} is a directory. Removing a whole directory is not something this tool does — "
            "run the command for it instead, so it is visible as a command."
        )
    if not resolved.exists():
        raise FileNotFoundError(f"{path} does not exist in the attached folder.")

    before = digest_of(resolved.read_bytes())
    resolved.unlink()
    return _record(relative_in_root(root, resolved), "deleted", before, None, 0)


def _record(path: str, action: str, before: str | None, after: str | None, size: int) -> dict:
    """One shape for all three operations, so the code that logs them needs no branches.

    `path` is already resolved and root-relative. The audit record has to describe the file that
    actually changed, not repeat the string the caller supplied.
    """
    return {
        "path": str(path).replace("\\", "/"),
        "action": action,
        "digest_before": before,
        "digest_after": after,
        "bytes_after": size,
    }


def _atomic_write(target: Path, raw: bytes) -> None:
    """Write beside the target, then move into place.

    The temporary file is in the same directory on purpose: `os.replace` is only atomic within a
    filesystem, and a temp directory elsewhere would silently degrade to copy-then-delete. If the
    move fails, the original is still whole and the temporary file is cleaned up.
    """
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=".orrery-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, str(target))
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
