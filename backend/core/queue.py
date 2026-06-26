from __future__ import annotations

import logging
from functools import lru_cache

from procrastinate import App, PsycopgConnector

from backend.core.database import resolve_database_url

log = logging.getLogger("orrery.queue")


def _dsn() -> str:
    url = resolve_database_url()
    if not url:
        raise RuntimeError("No database connection configured.")
    # Procrastinate wants a plain libpq DSN, not the SQLAlchemy URL
    return url.replace("postgresql+psycopg://", "postgresql://")


async def _health_ping() -> str:
    """Trivial task proving the worker executes jobs end to end."""
    log.info("health_ping executed")
    return "ok"


@lru_cache(maxsize=1)
def get_queue_app() -> App:
    """Build the Procrastinate app on first use — NOT at import time, because the database
    may not be configured yet (importing this module must never crash the setup flow)."""
    app = App(connector=PsycopgConnector(conninfo=_dsn()))
    app.task(name="health_ping")(_health_ping)
    return app


def reset_queue_app() -> None:
    """Drop the cached app so the next worker/migration picks up a changed connection."""
    get_queue_app.cache_clear()
