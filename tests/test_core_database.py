"""Core database URL normalization — the live engine path and the test path must agree."""

import pytest

from backend.core.database import normalize_url


def test_normalize_postgres_url():
    assert normalize_url("postgres://u:p@h:5432/db").startswith("postgresql+psycopg://")
    assert normalize_url("postgresql://u:p@h:5432/db").startswith("postgresql+psycopg://")
    assert normalize_url("postgresql+psycopg://u:p@h:5432/db").startswith("postgresql+psycopg://")


def test_normalize_url_preserves_body():
    assert normalize_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"


def test_normalize_url_blank():
    assert normalize_url("") == ""
    assert normalize_url("   ") == ""


# --- a health probe has to be bounded -----------------------------------------------------------
#
# `check_connection` caught every exception but waited forever for one. With PostgreSQL down,
# `GET /api/health` never answered: the endpoint that exists to report a broken database hung on it,
# and so did the sidebar indicator that polls it. It also made the test suite unrunnable without
# Docker, since the session tests call that route.

@pytest.mark.anyio
async def test_check_connection_gives_up_rather_than_waiting_forever(monkeypatch):
    """An unreachable database must read as 'not connected', quickly."""
    import asyncio
    import time as _time

    from backend.core import database

    class _NeverAnswers:
        def connect(self):
            return self

        async def __aenter__(self):
            await asyncio.sleep(3600)
            return self

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(database, "get_engine", lambda: _NeverAnswers())
    monkeypatch.setattr(database, "_health_cache", None)

    started = _time.monotonic()
    connected = await database.check_connection(force=True)
    elapsed = _time.monotonic() - started

    assert connected is False, "an unreachable database is not a healthy one"
    assert elapsed < database.HEALTH_TIMEOUT_SECONDS + 3, (
        f"check_connection took {elapsed:.1f}s; it must be bounded"
    )


@pytest.mark.anyio
async def test_a_reachable_database_still_reports_connected(monkeypatch):
    """The timeout must not turn a working database into a broken one."""
    from backend.core import database

    class _Answers:
        def connect(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def execute(self, _statement):
            return None

    monkeypatch.setattr(database, "get_engine", lambda: _Answers())
    monkeypatch.setattr(database, "_health_cache", None)

    assert await database.check_connection(force=True) is True
