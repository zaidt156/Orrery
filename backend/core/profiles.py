"""Layered configuration with visible provenance (ADR-004).

Orrery used to have exactly two places a setting could come from: a field default and `.env`.
That is fine until you want a profile you can check in, a per-user override that survives an
upgrade, and an answer to "why is this value what it is". Harness designs solve that with ordered
layers plus a command that dumps the resolved tree; this is the same idea at Orrery's scale.

Layers, lowest precedence first:

1. ``defaults``      - the field default in `Settings`
2. ``profile``       - a checked-in ``orrery.toml`` beside the project, or ``ORRERY_PROFILE``
3. ``home``          - ``<user data dir>/config.toml``, which survives reinstalling the app
4. ``env-file``      - ``.env`` (unchanged; still where local development puts things)
5. ``environment``   - real environment variables, which always win

Nothing here reads or stores a secret. Provider keys and the database URL live in the OS keychain
(security.md §1); a connection string that appears in a layer is shown redacted by `dump()`.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from backend.core import paths

LAYERS = ("defaults", "profile", "home", "env-file", "environment")


def profile_file() -> Path:
    override = os.environ.get("ORRERY_PROFILE", "").strip()
    if override:
        return Path(override).expanduser()
    return paths.project_root() / "orrery.toml"


def home_file() -> Path:
    return paths.user_data_dir() / "config.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    """A missing file is simply an absent layer. A malformed one is not silently ignored."""
    try:
        raw = path.read_bytes()
    except (OSError, ValueError):
        return {}
    try:
        loaded = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path} is not valid TOML: {exc}") from None
    # accept both a flat table and an [orrery] section, so the file can live beside other config
    section = loaded.get("orrery")
    values = section if isinstance(section, dict) else loaded
    return {str(k).lower(): v for k, v in values.items()}


def file_layers() -> dict[str, dict[str, Any]]:
    """The TOML layers only, lowest precedence first."""
    return {"profile": _read_toml(profile_file()), "home": _read_toml(home_file())}


def merged_file_values() -> dict[str, Any]:
    """Profile then home, so home wins - what the settings source feeds to pydantic."""
    merged: dict[str, Any] = {}
    for values in file_layers().values():
        merged.update(values)
    return merged


def _env_file_values() -> dict[str, Any]:
    path = paths.settings_file()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    out: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip().lower()] = value.strip().strip('"').strip("'")
    return out


def _is_secretish(name: str, value: Any) -> bool:
    lowered = name.lower()
    if any(word in lowered for word in ("url", "key", "token", "secret", "password")):
        return isinstance(value, str) and bool(value)
    return False


def dump(settings: Any) -> list[dict[str, Any]]:
    """Every setting, its resolved value, and which layer supplied it.

    Values that could carry a credential are redacted, because the whole point of this output is
    that it can be pasted into an issue.
    """
    from backend.security.secrets import redact_secrets, redact_url

    present: dict[str, dict[str, Any]] = {
        "profile": file_layers()["profile"],
        "home": file_layers()["home"],
        "env-file": _env_file_values(),
        "environment": {k.lower(): v for k, v in os.environ.items()},
    }

    rows: list[dict[str, Any]] = []
    for name in sorted(type(settings).model_fields):
        value = getattr(settings, name)
        source = "defaults"
        for layer in ("profile", "home", "env-file", "environment"):
            if name in present[layer]:
                source = layer
        shown: Any = value
        if _is_secretish(name, value):
            shown = redact_secrets(redact_url(str(value)))
        rows.append({"setting": name, "value": shown, "source": source})
    return rows


def render(settings: Any) -> str:
    """The `--dump-config` text: aligned, and safe to share."""
    rows = dump(settings)
    width = max((len(r["setting"]) for r in rows), default=10)
    lines = [
        "Orrery configuration (lowest precedence first: " + " < ".join(LAYERS) + ")",
        "",
        f"  {'setting'.ljust(width)}  {'source'.ljust(11)}  value",
        f"  {'-' * width}  {'-' * 11}  -----",
    ]
    for r in rows:
        lines.append(f"  {r['setting'].ljust(width)}  {r['source'].ljust(11)}  {r['value']}")
    lines += ["", f"  profile file : {profile_file()}", f"  home file    : {home_file()}",
              f"  env file     : {paths.settings_file()}"]
    return "\n".join(lines)
