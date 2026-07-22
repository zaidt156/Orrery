"""P0 outage regressions: identity and authorization must fail CLOSED on database errors.

A broad exception must never promote a caller to solo/admin or all-features-enabled; solo mode is
granted only when a successful query proves no team exists (the first-run state)."""
import asyncio
import sys

import pytest

from backend.features import admin, team
from backend.security import secrets

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Captured at import (collection) time, before the conftest autouse fixture patches them to solo.
_REAL_TEAM_MODE = team.team_mode
_REAL_CURRENT_USER = team.current_user
_REAL_IS_ADMIN = team.is_admin


def _boom():
    raise RuntimeError("database is down")


@pytest.fixture
def db_outage(monkeypatch):
    monkeypatch.setattr(team, "team_mode", _REAL_TEAM_MODE)
    monkeypatch.setattr(team, "current_user", _REAL_CURRENT_USER)
    monkeypatch.setattr(team, "is_admin", _REAL_IS_ADMIN)
    monkeypatch.setattr(team, "get_sessionmaker", _boom)


@pytest.mark.anyio
async def test_outage_reports_team_mode_not_solo(db_outage):
    assert await team.team_mode() is True


@pytest.mark.anyio
async def test_outage_locks_identity_and_admin(db_outage):
    assert await team.current_user() is None
    assert await team.is_admin() is False


@pytest.mark.anyio
async def test_outage_locks_identity_even_with_a_stored_key(db_outage):
    secrets.set_secret("team_access_key", "some-stored-key")
    assert await team.current_user() is None


@pytest.mark.anyio
async def test_outage_owner_scope_is_locked_team(db_outage):
    assert await team.owner_scope() == (True, None)
    with pytest.raises(PermissionError):
        await team.current_owner_id()


@pytest.mark.anyio
async def test_outage_status_shows_locked(db_outage):
    result = await team.status()
    assert result["team_mode"] is True
    assert result["locked"] is True
    assert result["user"] is None


@pytest.mark.anyio
async def test_outage_refuses_team_bootstrap(db_outage):
    result = await team.setup_team("Attacker")
    assert result["ok"] is False
    assert "verify" in result["error"].lower()


@pytest.mark.anyio
async def test_outage_disables_all_feature_gates(db_outage):
    flags = await admin.effective_flags()
    assert flags and not any(flags.values())
    assert await admin.feature_enabled("web_search") is False
    assert await admin.feature_enabled("mcp") is False


@pytest.mark.anyio
async def test_healthy_empty_team_table_still_means_solo(monkeypatch):
    """The fail-closed change must not cost the real first-run state: a PROVEN empty
    team table keeps solo mode (full local privileges)."""
    from sqlalchemy import func, select

    from backend.core.database import get_sessionmaker
    from backend.core.migrations import run_migrations
    from backend.core.models import TeamUser

    monkeypatch.setattr(team, "team_mode", _REAL_TEAM_MODE)
    monkeypatch.setattr(team, "current_user", _REAL_CURRENT_USER)
    try:
        await run_migrations()
        async with get_sessionmaker()() as s:
            count = (await s.execute(select(func.count(TeamUser.id)))).scalar_one()
    except Exception:  # noqa: BLE001 — no live test database on this machine
        pytest.skip("live database unavailable")
    if count:
        pytest.skip("a team exists in the test database")
    assert await team.team_mode() is False
    assert await team.current_user() == team.SOLO_USER
