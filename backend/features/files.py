"""Local file library: generated files live on disk, metadata travels with the chat message.

Per the file-generation architecture, large binaries never go in Postgres — they're written to a
local directory and served by id. Each file gets a sidecar .meta with its display name + mime so
the serving route stays self-describing.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import mimetypes
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from backend.core.config import settings
from backend.core.paths import user_data_dir
from backend.features.sandbox import SandboxFile

log = logging.getLogger("orrery.files")

_DIR = user_data_dir() / "tmp" / "generated"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
MAX_FILE_BYTES = 25_000_000
_MAX_OFFICE_PREVIEW_CACHE_ITEMS = 40
MAX_APP_BUNDLE_FILES = 12
MAX_APP_BUNDLE_BYTES = 20_000_000
_WINDOWS_DEVICE_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


_INVALID_APP_PATH_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def _safe_name(name: str) -> str:
    cleaned = _SAFE.sub("_", (name or "file").strip()).strip("._") or "file"
    return cleaned[:120]


def safe_app_member_path(name: str) -> PurePosixPath:
    """Revalidate model-produced paths at the host write boundary."""
    if not name or len(name) > 240 or "\\" in name or "\x00" in name:
        raise ValueError("App bundle contains an unsafe file path.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("App bundle contains an unsafe file path.")
    for part in path.parts:
        stem = part.split(".", 1)[0].lower()
        if (
            _INVALID_APP_PATH_CHARS.search(part)
            or part.endswith((" ", "."))
            or stem in _WINDOWS_DEVICE_NAMES
        ):
            raise ValueError("App bundle contains an unsafe file path.")
    return path


def _app_zip(members: list[tuple[PurePosixPath, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, data in sorted(members, key=lambda item: item[0].as_posix()):
            info = zipfile.ZipInfo(path.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def store_app_bundle(name: str, files: list[SandboxFile]) -> dict:
    """Persist one approved app as a ZIP plus a private extracted preview directory."""
    if not files or len(files) > MAX_APP_BUNDLE_FILES:
        raise ValueError("App bundle has an invalid number of files.")

    parsed = [(safe_app_member_path(item.name), bytes(item.data)) for item in files]
    folded = [path.as_posix().casefold() for path, _data in parsed]
    if len(set(folded)) != len(folded):
        raise ValueError("App bundle contains duplicate file paths.")
    if "index.html" not in {path.as_posix() for path, _data in parsed}:
        raise ValueError("App bundle is missing index.html.")
    total_bytes = sum(len(data) for _path, data in parsed)
    if total_bytes <= 0 or total_bytes > MAX_APP_BUNDLE_BYTES:
        raise ValueError("App bundle exceeds the size limit.")

    archive = _app_zip(parsed)
    if len(archive) > MAX_FILE_BYTES:
        raise ValueError("App bundle ZIP exceeds the size limit.")

    _DIR.mkdir(parents=True, exist_ok=True)
    app_root = _DIR / "apps"
    app_root.mkdir(exist_ok=True)
    file_id = uuid.uuid4().hex
    staging = app_root / f".{file_id}.tmp"
    preview = app_root / file_id
    temp_blob = _DIR / f".{file_id}.blob.tmp"
    blob = _DIR / file_id
    temp_meta = _DIR / f".{file_id}.meta.tmp"
    meta_path = _DIR / f"{file_id}.meta"
    safe_name = _safe_name(name or "small-app.zip")
    if not safe_name.lower().endswith(".zip"):
        safe_name = f"{safe_name[:116]}.zip"
    meta = {
        "id": file_id,
        "name": safe_name,
        "mime": "application/zip",
        "size": len(archive),
        "artifact_type": "app_bundle",
        "entrypoint": "index.html",
        "member_count": len(parsed),
    }

    try:
        staging.mkdir()
        for member, data in parsed:
            target = staging.joinpath(*member.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        temp_blob.write_bytes(archive)
        temp_meta.write_text(json.dumps(meta), encoding="utf-8")
        staging.replace(preview)
        temp_blob.replace(blob)
        temp_meta.replace(meta_path)
    except Exception:
        for partial in (temp_blob, blob, temp_meta, meta_path):
            partial.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        if preview.is_symlink():
            preview.unlink(missing_ok=True)
        else:
            shutil.rmtree(preview, ignore_errors=True)
        raise
    return meta


def store_filegen_output(result: dict) -> list[dict]:
    """Store an approved file-generation result using its declared output kind."""
    generated = result.get("files") or []
    if result.get("kind") == "app":
        stored = store_app_bundle(result.get("bundle_name") or "small-app.zip", generated)
        return [{"kind": "file", **stored}]

    produced: list[dict] = []
    for item in generated:
        mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
        try:
            produced.append({"kind": "file", **store(item.name, mime, item.data)})
        except ValueError:
            continue
    return produced


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


# Explicit map, not mimetypes.guess_type: the serving route sets X-Content-Type-Options: nosniff, so
# a wrong type stops the file from loading (a browser will not run a script served as text/plain).
# guess_type reads the OS registry on Windows, where .js has been observed as text/plain — so the
# critical bundle types are pinned here. Every key must stay within filegen._APP_ALLOWED_EXTENSIONS.
_APP_MIME = {
    "html": "text/html; charset=utf-8", "htm": "text/html; charset=utf-8",
    "js": "text/javascript; charset=utf-8", "mjs": "text/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8", "json": "application/json; charset=utf-8",
    "txt": "text/plain; charset=utf-8", "svg": "image/svg+xml",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "ico": "image/x-icon",
    "woff": "font/woff", "woff2": "font/woff2", "ttf": "font/ttf", "otf": "font/otf",
    "mp3": "audio/mpeg", "wav": "audio/wav", "mp4": "video/mp4", "webm": "video/webm",
}


def app_bundle_meta(artifact_id: str) -> dict | None:
    """Return an app bundle's metadata, or None unless it exists and is genuinely an app_bundle."""
    if not re.fullmatch(r"[0-9a-f]{32}", artifact_id or ""):
        return None
    meta_path = _DIR / f"{artifact_id}.meta"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return meta if meta.get("artifact_type") == "app_bundle" else None


def read_app_bundle_file(artifact_id: str, rel_path: str = "index.html") -> tuple[bytes, str] | None:
    """Read one file from a bundle's extracted preview dir, confined to that dir.

    Returns (data, mime) or None if the bundle/file is missing or the path escapes the directory.
    Confinement is by resolved real path: resolve() collapses `..` and follows symlinks, so anything
    that would land outside the bundle root fails the is_relative_to check and is refused. This is the
    load-bearing traversal guard for the (necessarily unauthenticated) app-serving route.
    """
    if app_bundle_meta(artifact_id) is None:
        return None
    try:
        root = (_DIR / "apps" / artifact_id).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not root.is_dir():
        return None

    candidate = (rel_path or "").strip().lstrip("/")
    if not candidate or candidate.endswith("/"):
        candidate = f"{candidate}index.html"
    if "\x00" in candidate or "\\" in candidate:  # NUL and backslash are never legitimate here
        return None

    try:
        target = (root / candidate).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not (target == root or target.is_relative_to(root)):
        return None
    if not target.is_file():
        return None
    try:
        data = target.read_bytes()
    except OSError:
        return None
    return data, _APP_MIME.get(target.suffix.lstrip(".").lower(), "application/octet-stream")


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
    """Delete expired generated artifacts without leaving partial app bundles."""
    hours = settings.generated_file_ttl_hours if ttl_hours is None else ttl_hours
    if hours <= 0 or not _DIR.is_dir():
        return 0
    cutoff = time.time() - hours * 3600
    removed = 0
    app_root = _DIR / "apps"
    app_ids: set[str] = set()

    def remove_path(path: Path) -> int:
        try:
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
                return 1
            if path.is_dir():
                shutil.rmtree(path)
                return 1
        except OSError:
            return 0
        return 0

    if app_root.is_dir():
        try:
            for app_path in app_root.iterdir():
                if re.fullmatch(r"[0-9a-f]{32}", app_path.name):
                    app_ids.add(app_path.name)
                    continue
                if re.fullmatch(r"\.[0-9a-f]{32}\.tmp", app_path.name):
                    try:
                        if app_path.stat().st_mtime < cutoff:
                            removed += remove_path(app_path)
                    except OSError:
                        continue
        except OSError:
            pass

    try:
        for meta_path in _DIR.glob("*.meta"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            artifact_id = str(meta.get("id") or "")
            if meta.get("artifact_type") == "app_bundle" and re.fullmatch(r"[0-9a-f]{32}", artifact_id):
                app_ids.add(artifact_id)
    except OSError:
        pass

    managed_names = {name for artifact_id in app_ids for name in (artifact_id, f"{artifact_id}.meta")}

    for artifact_id in app_ids:
        blob = _DIR / artifact_id
        meta_path = _DIR / f"{artifact_id}.meta"
        preview = app_root / artifact_id
        parts = (blob, meta_path, preview)
        if not all(path.exists() or path.is_symlink() for path in parts):
            for path in parts:
                removed += remove_path(path)
            continue
        try:
            expired = min(blob.stat().st_mtime, meta_path.stat().st_mtime) < cutoff
        except OSError:
            expired = True
        if expired:
            for path in parts:
                removed += remove_path(path)

    try:
        for path in _DIR.iterdir():
            if path.is_dir():
                continue
            if path.name in managed_names:
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    removed += remove_path(path)
            except OSError:
                continue
    except OSError:
        return removed

    if app_root.is_dir():
        try:
            app_root.rmdir()
        except OSError:
            pass
    if removed:
        log.info("cleaned %d expired generated file(s)", removed)
    return removed
