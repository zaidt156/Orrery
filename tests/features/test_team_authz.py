"""Team-mode authorization sweep (Step 108 follow-up, plan Task 5c).

Two invariants, enforced at the API/feature layer rather than the UI:
- a LOCKED team client (team mode on, no valid key) fails closed with 403 on private surfaces;
- one member can never see or act on another member's agents, runs, or approvals.
"""
import asyncio
import sys
import uuid

import pytest

from backend.features import agent_runs, agents, team

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ── locked client → 403 on the newer private surfaces ──────────────────────────

LOCKED_GETS = [
    "/api/agents",
    "/api/agent-approvals",
    "/api/life",
    "/api/conversations",
]


@pytest.mark.parametrize("path", LOCKED_GETS)
def test_locked_client_fails_closed(monkeypatch, path):
    from tests.test_api import TOKEN, _client

    async def locked():
        raise PermissionError("Team access key required.")

    monkeypatch.setattr(team, "current_owner_id", locked)

    response = _client().get(path, headers={"X-Orrery-Token": TOKEN})

    assert response.status_code == 403, f"{path} must fail closed for a locked client"


def test_locked_client_cannot_start_agent_runs(monkeypatch):
    from tests.test_api import TOKEN, _client

    async def locked():
        raise PermissionError("Team access key required.")

    monkeypatch.setattr(team, "current_owner_id", locked)

    response = _client().post(
        f"/api/agents/{uuid.uuid4()}/runs",
        headers={"X-Orrery-Token": TOKEN},
        json={"input": "do work"},
    )

    assert response.status_code == 403


# -- team role must outrank the legacy solo-admin token ---------------------

def test_team_member_cannot_change_feature_flags_with_legacy_admin_token(monkeypatch):
    """Team mode is role-authorized; knowing the old solo token must not elevate a member."""
    from backend.features import admin
    from tests.test_api import TOKEN, _client

    async def team_mode_on():
        return True

    async def member():
        return False

    token_fallback_calls = []

    async def legacy_token_would_accept(flags, token):
        token_fallback_calls.append((flags, token))
        return True

    monkeypatch.setattr(team, "team_mode", team_mode_on)
    monkeypatch.setattr(team, "is_admin", member)
    monkeypatch.setattr(admin, "set_flags", legacy_token_would_accept)

    response = _client().put(
        "/api/admin/features",
        headers={"X-Orrery-Token": TOKEN},
        json={"flags": {"agents": False}, "token": "known-legacy-token"},
    )

    assert response.status_code == 403
    assert token_fallback_calls == []


def test_team_member_cannot_rotate_legacy_admin_token(monkeypatch):
    from backend.features import admin
    from tests.test_api import TOKEN, _client

    async def team_mode_on():
        return True

    async def member():
        return False

    token_change_calls = []

    def legacy_token_would_accept(new_token, current):
        token_change_calls.append((new_token, current))
        return True

    monkeypatch.setattr(team, "team_mode", team_mode_on)
    monkeypatch.setattr(team, "is_admin", member)
    monkeypatch.setattr(admin, "set_admin_token", legacy_token_would_accept)

    response = _client().post(
        "/api/admin/token",
        headers={"X-Orrery-Token": TOKEN},
        json={"token": "replacement", "current": "known-legacy-token"},
    )

    assert response.status_code == 403
    assert token_change_calls == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/team/users", None),
        ("post", "/api/models/active", {
            "id": "openai/test", "label": "Test", "provider": "openai", "active": True,
        }),
        ("put", "/api/branding", {"enabled": False}),
    ],
)
def test_team_member_is_forbidden_from_admin_routes(monkeypatch, method, path, body):
    from tests.test_api import TOKEN, _client

    async def member():
        return False

    monkeypatch.setattr(team, "is_admin", member)
    request = getattr(_client(), method)
    response = request(path, headers={"X-Orrery-Token": TOKEN}, json=body) if body is not None else request(
        path, headers={"X-Orrery-Token": TOKEN}
    )

    assert response.status_code == 403


# ── cross-owner isolation on agents/runs/approvals ─────────────────────────────

def _config(name="Scoped"):
    return agents.AgentConfig.model_validate({
        "name": name,
        "goal": "Stay in your lane.",
        "model": "openai/test",
    })


async def _as_owner(monkeypatch, owner_id):
    async def fixed():
        return owner_id
    monkeypatch.setattr(team, "current_owner_id", fixed)


@pytest.mark.anyio
async def test_member_cannot_see_or_run_another_members_agent(monkeypatch):
    from backend.core.database import get_sessionmaker
    from backend.core.migrations import run_migrations
    from backend.core.models import Agent

    await run_migrations()
    owner_a, owner_b = f"user-{uuid.uuid4().hex[:8]}", f"user-{uuid.uuid4().hex[:8]}"

    await _as_owner(monkeypatch, owner_a)
    created = await agents.create_agent(_config())
    agent_id = created["id"]
    try:
        await _as_owner(monkeypatch, owner_b)
        listed = await agents.list_agents()
        assert agent_id not in {a["id"] for a in listed["agents"]}
        assert await agents.get_agent(agent_id) is None
        assert await agents.set_agent_status(agent_id, "paused") is None
        with pytest.raises(ValueError, match="not found"):
            await agent_runs.start_run(agent_id, owner_id=owner_b)

        # runs/approvals listings are owner-scoped too
        assert await agent_runs.list_runs(agent_id, owner_id=owner_b) == []
        assert await agent_runs.get_run(str(uuid.uuid4()), owner_id=owner_b) is None
    finally:
        async with get_sessionmaker()() as s:
            row = await s.get(Agent, uuid.UUID(agent_id))
            if row is not None:
                await s.delete(row)
                await s.commit()


@pytest.mark.anyio
async def test_approvals_are_owner_scoped(monkeypatch):
    from backend.core.database import get_sessionmaker
    from backend.core.migrations import run_migrations
    from backend.core.models import Agent, AgentApproval, AgentRun, AgentVersion

    await run_migrations()
    owner_a, owner_b = f"user-{uuid.uuid4().hex[:8]}", f"user-{uuid.uuid4().hex[:8]}"

    await _as_owner(monkeypatch, owner_a)
    created = await agents.create_agent(_config("Approval scope"))
    agent_id = uuid.UUID(created["id"])
    try:
        import datetime
        import json as _json

        async with get_sessionmaker()() as s:
            version = (await s.execute(
                __import__("sqlalchemy").select(AgentVersion).where(AgentVersion.agent_id == agent_id)
            )).scalars().first()
            run = AgentRun(
                agent_id=agent_id, agent_version_id=version.id, owner_id=owner_a,
                trigger_type="manual", input_text="", input_digest="0" * 64,
                config_snapshot=version.config, status="awaiting_approval",
            )
            s.add(run)
            await s.flush()
            approval = AgentApproval(
                run_id=run.id, owner_id=owner_a, tool_key="web_search", risk="network",
                action_digest="0" * 64, action=_json.dumps({"tool": "web_search", "args": {}}),
                status="pending",
                expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
            )
            s.add(approval)
            await s.commit()
            approval_id = str(approval.id)

        # the other member can neither list nor decide it
        pending_b = await agent_runs.list_pending_approvals(owner_id=owner_b)
        assert approval_id not in {p["id"] for p in pending_b}
        assert await agent_runs.decide_approval(approval_id, approve=True, owner_id=owner_b) is None

        # the owner can
        pending_a = await agent_runs.list_pending_approvals(owner_id=owner_a)
        assert approval_id in {p["id"] for p in pending_a}
    finally:
        async with get_sessionmaker()() as s:
            row = await s.get(Agent, agent_id)
            if row is not None:
                await s.delete(row)
                await s.commit()
