from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from backend.core.version import APP_VERSION, UPDATE_REPOSITORY


def _version_tuple(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for piece in cleaned.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or "0"))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    return _version_tuple(latest) > _version_tuple(current)


def check_for_updates(timeout: float = 6.0) -> dict[str, Any]:
    current = APP_VERSION
    url = f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Orrery/{current}",
        },
    )
    base = {
        "current_version": current,
        "repository": UPDATE_REPOSITORY,
        "release_url": f"https://github.com/{UPDATE_REPOSITORY}/releases",
    }
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_001)  # fixed GitHub endpoint, but still cap the body
            if len(raw) > 2_000_000:
                raise OSError("Update metadata response is too large.")
            payload = json.loads(raw.decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {
            **base,
            "ok": False,
            "update_available": False,
            "error": str(exc),
        }

    tag = str(payload.get("tag_name") or "")
    latest = tag.lstrip("vV") or current
    assets = [
        {
            "name": str(asset.get("name") or ""),
            "url": str(asset.get("browser_download_url") or ""),
            "size": int(asset.get("size") or 0),
        }
        for asset in payload.get("assets", [])
        if isinstance(asset, dict)
    ]
    return {
        **base,
        "ok": True,
        "update_available": is_newer(latest, current),
        "latest_version": latest,
        "latest_tag": tag,
        "name": str(payload.get("name") or tag or "Latest release"),
        "published_at": str(payload.get("published_at") or ""),
        "html_url": str(payload.get("html_url") or base["release_url"]),
        "assets": assets,
    }

