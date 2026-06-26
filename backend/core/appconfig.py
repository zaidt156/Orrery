from __future__ import annotations

import json
import logging
from typing import Any

from backend.core.database import get_sessionmaker
from backend.core.models import AppSetting

# small non-secret app config (branding, spend cap, privacy mode…) stored as JSON in app_settings.
# Keys are a fixed, typed registry so unknown keys are rejected and shapes are validated (plan #10).

log = logging.getLogger("orrery.appconfig")

_ALLOWED_SETTINGS: dict[str, type] = {
    "branding": dict,
    "spend_cap": dict,
    "privacy_mode": str,
}


def _validate_setting(key: str, value: Any) -> None:
    expected = _ALLOWED_SETTINGS.get(key)
    if expected is None:
        raise ValueError(f"Unknown app setting: {key}")
    if not isinstance(value, expected):
        raise ValueError(f"Invalid value type for setting {key}: expected {expected.__name__}")


async def get_setting(key: str, default: Any = None) -> Any:
    async with get_sessionmaker()() as s:
        row = await s.get(AppSetting, key)
        if row is None:
            return default
        try:
            return json.loads(row.value)
        except (TypeError, ValueError):
            log.warning("corrupt JSON for app setting %r; returning default", key)
            return default


async def set_setting(key: str, value: Any) -> Any:
    _validate_setting(key, value)
    payload = json.dumps(value)
    async with get_sessionmaker()() as s:
        row = await s.get(AppSetting, key)
        if row is None:
            s.add(AppSetting(key=key, value=payload))
        else:
            row.value = payload
        await s.commit()
    return value
