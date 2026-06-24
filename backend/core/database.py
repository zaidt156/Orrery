from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.config import settings
from backend.security import secrets

log = logging.getLogger("orrery.db")

_CONN_KEY = "database_url"
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_HEALTH_CACHE_TTL = 5.0
_health_cache: tuple[float, bool] | None = None


def resolve_database_url() -> str | None:
    """Keychain first, then .env. None if nothing is configured yet."""
    return secrets.get_secret(_CONN_KEY) or settings.database_url


def save_database_url(url: str) -> None:
    """Persist the connection string to the OS keychain."""
    secrets.set_secret(_CONN_KEY, url)


def get_engine() -> AsyncEngine:
    """Return the shared async engine, creating it on first use."""
    global _engine
    if _engine is None:
        url = resolve_database_url()
        if not url:
            raise RuntimeError("No database connection configured.")
        _engine = create_async_engine(url, pool_pre_ping=True)
    return _engine


async def check_connection(force: bool = False) -> bool:
    """True if a trivial query succeeds. Errors are logged with secrets redacted."""
    global _health_cache
    now = time.monotonic()
    if not force and _health_cache and now - _health_cache[0] < _HEALTH_CACHE_TTL:
        return _health_cache[1]
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        _health_cache = (now, True)
        return True
    except Exception as exc:  # noqa: BLE001 — any failure means "not connected"
        log.error("Database connection failed: %s", secrets.redact_url(str(exc)))
        _health_cache = (now, False)
        return False


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the shared async session factory, creating it on first use."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session that is closed after the request."""
    async with get_sessionmaker()() as session:
        yield session
