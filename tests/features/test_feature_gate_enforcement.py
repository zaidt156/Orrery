"""Admin feature flags have to be enforced by the server, not by the navigation bar.

Turning a surface off in Admin hid its React tab and nothing else: `POST /api/agents/{id}/runs`,
the workflow run route, and the dashboard routes all still answered. A control that only removes the
button is not an authorization control (security.md §4) — anything that can reach loopback with the
session, including a tool or a script, was never gated at all.

These tests are deliberately database-free: they monkeypatch the flag read and assert what the route
boundary does with the answer, so the gate is pinned independently of PostgreSQL.
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api import create_app, deps
from backend.features import admin

# Deliberately no event-loop policy change here. The db-marked suites set the Windows selector
# policy at import because psycopg needs it; doing the same from a module that never reaches a
# database is a global side effect that changes how every other TestClient in the session runs —
# it hung tests/security/test_session.py. These tests are refused before any handler, so they need
# no database and no policy.

TOKEN = "secret-token"

# One representative route per gated surface. GET routes only: a refusal has to happen before the
# handler, so these must never reach a database even when the gate lets them through.
GATED_ROUTES = [
    ("agents", "/api/agents"),
    ("automations", "/api/workflows"),
    ("dashboards", "/api/dashboards"),
    ("mcp", "/api/mcp"),
]


@pytest.fixture
def client():
    return TestClient(create_app(TOKEN))


@pytest.fixture
def auth():
    return {"X-Orrery-Token": TOKEN}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def all_features_off(monkeypatch):
    """Every flag off, without a database: the gate's answer is what is under test, not its source."""
    async def _off(name):
        return False

    async def _all_off():
        return {name: False for name in admin.FEATURES}

    monkeypatch.setattr(admin, "feature_enabled", _off)
    monkeypatch.setattr(admin, "effective_flags", _all_off)


@pytest.mark.parametrize(("flag", "path"), GATED_ROUTES)
def test_a_disabled_surface_is_refused_by_the_server(client, auth, all_features_off, flag, path):
    """The tab being hidden is a courtesy. This is the control."""
    response = client.get(path, headers=auth)

    assert response.status_code == 403, f"{path} answered with {flag} disabled"


@pytest.mark.parametrize(("flag", "path"), GATED_ROUTES)
def test_a_disabled_surface_is_refused_even_with_a_valid_session(client, all_features_off, flag, path):
    """A disabled feature is not an authentication problem, so it must not read as one."""
    response = client.get(path, headers={"X-Orrery-Token": TOKEN})

    assert response.status_code != 401, "a valid session should not be reported as unauthenticated"
    assert response.status_code == 403


def test_the_flags_themselves_are_never_gated(client, auth, all_features_off):
    """If the route that reports the flags were gated, turning everything off would be permanent.

    The workspace has to be able to read its own configuration in order to recover it.
    """
    response = client.get("/api/tools", headers=auth)

    assert response.status_code == 200
    assert "features" in response.json()


def test_admin_routes_are_never_gated_by_a_feature_flag(client, auth, all_features_off):
    """Administration is how a feature gets turned back on; gating it would be a lockout."""
    response = client.get("/api/admin", headers=auth)

    assert response.status_code != 403


@pytest.mark.anyio
async def test_the_gate_allows_an_enabled_feature(monkeypatch):
    """The dependency itself, away from any route, so the allow path is proven too."""
    async def _on(name):
        assert name == "agents"
        return True

    monkeypatch.setattr(admin, "feature_enabled", _on)

    assert await deps.require_feature("agents")() is None


@pytest.mark.anyio
async def test_the_gate_refuses_an_unreadable_flag_state(monkeypatch):
    """An unknown state disables. A gate that opens when it cannot decide is not a gate."""
    async def _broken(name):
        raise RuntimeError("app config is unreachable")

    monkeypatch.setattr(admin, "feature_enabled", _broken)

    with pytest.raises(HTTPException) as raised:
        await deps.require_feature("agents")()

    assert raised.value.status_code == 403


@pytest.mark.anyio
async def test_the_gate_names_the_feature_it_refused(monkeypatch):
    """A 403 that does not say which switch to flip sends the user hunting."""
    async def _off(name):
        return False

    monkeypatch.setattr(admin, "feature_enabled", _off)

    with pytest.raises(HTTPException) as raised:
        await deps.require_feature("automations")()

    assert "Automations" in raised.value.detail
