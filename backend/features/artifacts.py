from __future__ import annotations

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
_store: dict[str, tuple[float, str, bytes]] = {}


def register(content: str | bytes, media_type: str = "text/html") -> str:
    data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    if not data:
        raise ValueError("There is nothing to preview.")
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError("This content is too large to preview.")
    artifact_id = uuid.uuid4().hex
    now = time.monotonic()
    with _lock:
        _store[artifact_id] = (now, media_type, data)
        if len(_store) > _MAX_ITEMS:  # evict oldest
            for stale in sorted(_store, key=lambda key: _store[key][0])[: len(_store) - _MAX_ITEMS]:
                _store.pop(stale, None)
    return artifact_id


def get(artifact_id: str) -> tuple[str, bytes] | None:
    now = time.monotonic()
    with _lock:
        item = _store.get(artifact_id)
        if item is None:
            return None
        created, media_type, data = item
        if now - created > _TTL_SECONDS:
            _store.pop(artifact_id, None)
            return None
        return media_type, data
