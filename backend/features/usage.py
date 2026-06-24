from __future__ import annotations

import datetime

from sqlalchemy import func, select

from backend.core import appconfig
from backend.core.database import get_sessionmaker
from backend.core.models import UsageEvent

# API-key spend tracking + cap. Subscription (CLI plan) and local (Ollama) routes are
# exempt — they don't bill per token. The cap window is user-chosen: hour/day/month/all.

_CAP_KEY = "spend_cap"
_DEFAULT_CAP = {"enabled": False, "limit_usd": 10.0, "period": "month"}
_PERIODS = ("hour", "day", "month", "all")


def _window_start(period: str, now: datetime.datetime) -> datetime.datetime | None:
    if period == "hour":
        return now - datetime.timedelta(hours=1)
    if period == "day":
        return now - datetime.timedelta(days=1)
    if period == "month":
        return now - datetime.timedelta(days=30)
    return None  # "all" → no lower bound


async def record(provider: str, model: str, tokens_in: int, tokens_out: int, cost: float) -> None:
    async with get_sessionmaker()() as s:
        s.add(UsageEvent(
            provider=provider, model=model,
            tokens_in=int(tokens_in or 0), tokens_out=int(tokens_out or 0), cost=float(cost or 0.0),
        ))
        await s.commit()


async def get_cap() -> dict:
    cap = await appconfig.get_setting(_CAP_KEY, dict(_DEFAULT_CAP))
    if cap.get("period") not in _PERIODS:
        cap["period"] = "month"
    return cap


async def set_cap(enabled: bool, limit_usd: float, period: str) -> dict:
    cap = {
        "enabled": bool(enabled),
        "limit_usd": max(0.0, float(limit_usd)),
        "period": period if period in _PERIODS else "month",
    }
    await appconfig.set_setting(_CAP_KEY, cap)
    return cap


async def _spend(period: str) -> dict:
    start = _window_start(period, datetime.datetime.now(datetime.timezone.utc))
    async with get_sessionmaker()() as s:
        q = select(
            func.coalesce(func.sum(UsageEvent.cost), 0.0),
            func.coalesce(func.sum(UsageEvent.tokens_in), 0),
            func.coalesce(func.sum(UsageEvent.tokens_out), 0),
        )
        if start is not None:
            q = q.where(UsageEvent.created_at >= start)
        cost, tin, tout = (await s.execute(q)).one()
    return {"cost": float(cost or 0.0), "tokens_in": int(tin or 0), "tokens_out": int(tout or 0)}


async def summary() -> dict:
    cap = await get_cap()
    spend = await _spend(cap["period"])
    over = cap["enabled"] and spend["cost"] >= cap["limit_usd"]
    return {"cap": cap, "period": cap["period"], **spend, "over": over}


async def cap_exceeded() -> tuple[bool, dict]:
    """(blocked, summary) — blocked is True only when a cap is enabled and the window is over it."""
    info = await summary()
    return bool(info["over"]), info
