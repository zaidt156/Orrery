"""Local file library: generated files live on disk, metadata travels with the chat message.

Per the file-generation architecture, large binaries never go in Postgres — they're written to a
local directory and served by id. Each file gets a sidecar .meta with its display name + mime so
the serving route stays self-describing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from pathlib import Path

from backend.core.config import settings
from backend.core.paths import user_data_dir

log = logging.getLogger("orrery.files")

_DIR = user_data_dir() / "tmp" / "generated"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
MAX_FILE_BYTES = 25_000_000
_MAX_OFFICE_PREVIEW_CACHE_ITEMS = 40


def _safe_name(name: str) -> str:
    cleaned = _SAFE.sub("_", (name or "file").strip()).strip("._") or "file"
    return cleaned[:120]


def store(name: str, mime: str, data: bytes) -> dict:
    """Persist a generated file and return its metadata record."""
    if not data:
        raise ValueError("Refusing to store an empty file.")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Generated file exceeds the size limit.")
    _DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    (_DIR / file_id).write_bytes(data)
    meta = {"id": file_id, "name": _safe_name(name), "mime": mime or "application/octet-stream", "size": len(data)}
    (_DIR / f"{file_id}.meta").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def load(file_id: str) -> tuple[dict, bytes] | None:
    if not re.fullmatch(r"[0-9a-f]{32}", file_id or ""):  # ids are uu4 hex; blocks path traversal
        return None
    blob = _DIR / file_id
    meta_path = _DIR / f"{file_id}.meta"
    if not blob.is_file() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return meta, blob.read_bytes()


def office_preview_cache_path(file_id: str, data: bytes) -> Path:
    """Return the content-addressed PDF sidecar path, removing stale variants for this artifact."""
    if not re.fullmatch(r"[0-9a-f]{32}", file_id or ""):
        raise ValueError("Invalid generated file id.")
    _DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:20]
    target = _DIR / f"{file_id}.{digest}.preview.pdf"
    for stale in _DIR.glob(f"{file_id}.*.preview.pdf"):
        if stale != target:
            try:
                stale.unlink()
            except OSError:
                pass
    other_previews = [path for path in _DIR.glob("*.preview.pdf") if path != target]
    excess = len(other_previews) - max(0, _MAX_OFFICE_PREVIEW_CACHE_ITEMS - 1)
    if excess > 0:
        dated = []
        for path in other_previews:
            try:
                dated.append((path.stat().st_mtime, path))
            except OSError:
                continue
        for _mtime, stale in sorted(dated, key=lambda item: item[0])[:excess]:
            try:
                stale.unlink()
            except OSError:
                pass
    return target


def cleanup(ttl_hours: int | None = None) -> int:
    """Delete generated files (and their .meta) older than the TTL so the dir can't grow forever.
    Best-effort: returns the count removed; never raises."""
    hours = settings.generated_file_ttl_hours if ttl_hours is None else ttl_hours
    if hours <= 0 or not _DIR.is_dir():
        return 0
    cutoff = time.time() - hours * 3600
    removed = 0
    try:
        for path in _DIR.iterdir():
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    if removed:
        log.info("cleaned %d expired generated file(s)", removed)
    return removed
