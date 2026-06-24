from __future__ import annotations

import logging

from procrastinate import App, PsycopgConnector

from backend.core.database import resolve_database_url

log = logging.getLogger("orrery.queue")


def _dsn() -> str:
    url = resolve_database_url()
    if not url:
        raise RuntimeError("No database connection configured.")
    # Procrastinate wants a plain libpq DSN, not the SQLAlchemy URL
    return url.replace("postgresql+psycopg://", "postgresql://")


app = App(connector=PsycopgConnector(conninfo=_dsn()))


@app.task(name="health_ping")
async def health_ping() -> str:
    """Trivial task proving the worker executes jobs end to end."""
    log.info("health_ping executed")
    return "ok"
