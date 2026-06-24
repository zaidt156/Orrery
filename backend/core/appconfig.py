from __future__ import annotations

import json
from typing import Any

from backend.core.database import get_sessionmaker
from backend.core.models import AppSetting

# small non-secret app config (branding, spend cap…) stored as JSON in app_settings


async def get_setting(key: str, default: Any = None) -> Any:
    async with get_sessionmaker()() as s:
        row = await s.get(AppSetting, key)
        if row is None:
            return default
        try:
            return json.loads(row.value)
        except (TypeError, ValueError):
            return default


async def set_setting(key: str, value: Any) -> Any:
    payload = json.dumps(value)
    async with get_sessionmaker()() as s:
        row = await s.get(AppSetting, key)
        if row is None:
            s.add(AppSetting(key=key, value=payload))
        else:
            row.value = payload
        await s.commit()
    return value
