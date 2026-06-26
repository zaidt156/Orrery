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


def normalize_url(url: str) -> str:
    """Accept common Postgres URL forms and force the async psycopg driver."""
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def save_database_url(url: str) -> None:
    """Persist the connection string to the OS keychain."""
    secrets.set_secret(_CONN_KEY, normalize_url(url))


def clear_database_url() -> None:
    """Forget the saved connection (reverts to the .env default, or none)."""
    secrets.delete_secret(_CONN_KEY)


async def reset_database_engine() -> None:
    """Dispose the live engine and clear cached session/health state so the next call
    rebuilds against the current connection — no app restart needed after a URL change."""
    global _engine, _sessionmaker, _health_cache
    if _engine is not None:
        try:
            await _engine.dispose()
        except Exception as exc:  # noqa: BLE001 — disposing a dead engine shouldn't block the switch
            log.warning("Engine dispose failed during reset: %s", secrets.redact_url(str(exc)))
    _engine = None
    _sessionmaker = None
    _health_cache = None
    try:  # the background queue holds its own connector — drop it too (lazy import avoids a cycle)
        from backend.core.queue import reset_queue_app
        reset_queue_app()
    except Exception:  # noqa: BLE001 — queue reset is best-effort
        pass


async def save_database_url_and_reset(url: str) -> None:
    """Save a new connection and switch the live engine over to it immediately."""
    save_database_url(url)
    await reset_database_engine()


async def clear_database_url_and_reset() -> None:
    """Forget the saved connection and drop the live engine immediately."""
    clear_database_url()
    await reset_database_engine()


def connection_info() -> dict:
    """Current connection for display — masked (never exposes the password)."""
    url = resolve_database_url()
    if not url:
        return {"configured": False, "masked": "", "source": None}
    source = "keychain" if secrets.get_secret(_CONN_KEY) else "env"
    return {"configured": True, "masked": secrets.redact_url(url), "source": source}


async def test_url(url: str) -> tuple[bool, str]:
    """Try connecting to a candidate URL without touching the live engine."""
    candidate = normalize_url(url)
    if not candidate:
        return False, "Enter a connection string."
    if not candidate.startswith("postgresql+psycopg://"):
        return False, "Use a PostgreSQL URL, e.g. postgresql://user:password@host:5432/dbname"
    probe = None
    try:
        probe = create_async_engine(candidate, pool_pre_ping=True, connect_args={"connect_timeout": 8})
        async with probe.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, ""
    except Exception as exc:  # noqa: BLE001 — report a sanitized reason
        return False, secrets.redact_url(str(exc))[:280]
    finally:
        if probe is not None:
            await probe.dispose()


def get_engine() -> AsyncEngine:
    """Return the shared async engine, creating it on first use."""
    global _engine
    if _engine is None:
        url = resolve_database_url()
        if not url:
            raise RuntimeError("No database connection configured.")
        _engine = create_async_engine(normalize_url(url), pool_pre_ping=True)
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
