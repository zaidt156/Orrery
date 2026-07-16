from __future__ import annotations

import re
import threading
import time
import uuid

# Transient store for previews the user opens in the sidebar: HTML artifacts (rendered in a
# SANDBOXED iframe) and generated files like PDF (rendered inline by the webview's viewer).
# Content is the user's own reply/export; served from a dedicated route, never persisted.

MAX_ARTIFACT_BYTES = 8_000_000
_MAX_ITEMS = 40
_TTL_SECONDS = 3600.0
_lock = threading.Lock()
_store: dict[str, tuple[float, str, bytes, str | None]] = {}

# The download name travels into a Content-Disposition header, so it is reduced to plain,
# quote-free, single-line characters here — a name is never allowed to author a header.
_HEADER_UNSAFE = re.compile(r'[^A-Za-z0-9 ._()\[\]-]+')


def _header_safe_name(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = _HEADER_UNSAFE.sub("_", name.strip()).strip("._ ")
    return cleaned[:120] or None


def register(content: str | bytes, media_type: str = "text/html", filename: str | None = None) -> str:
    """Hold content for the preview route. `filename` is what the user gets if they save it from
    the viewer: without it the browser falls back to the URL, and the id is a uuid — which is how a
    CV once landed on disk as 324f1fb3b81345f0ba7247b717ada9d2.pdf."""
    data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    if not data:
        raise ValueError("There is nothing to preview.")
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError("This content is too large to preview.")
    artifact_id = uuid.uuid4().hex
    now = time.monotonic()
    with _lock:
        _store[artifact_id] = (now, media_type, data, _header_safe_name(filename))
        if len(_store) > _MAX_ITEMS:  # evict oldest
            for stale in sorted(_store, key=lambda key: _store[key][0])[: len(_store) - _MAX_ITEMS]:
                _store.pop(stale, None)
    return artifact_id


def get(artifact_id: str) -> tuple[str, bytes, str | None] | None:
    """Return (media_type, data, download_name) — download_name may be None."""
    now = time.monotonic()
    with _lock:
        item = _store.get(artifact_id)
        if item is None:
            return None
        created, media_type, data, filename = item
        if now - created > _TTL_SECONDS:
            _store.pop(artifact_id, None)
            return None
        return media_type, data, filename
