import asyncio
import sys
import uuid

import pytest

from backend.features import agent_runs, agents

# psycopg async needs the SelectorEventLoop on Windows (same as the app itself)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _config(**overrides):
    base = {
        "name": "Runner",
        "goal": "Answer the input.",
        "model": "openai/test",
        "tool_grants": [{"tool": "web_search", "actions": ["execute"]}],
        "budgets": {"max_steps_per_run": 4, "max_runtime_seconds": 300},
    }
    base.update(overrides)
    return agents.AgentConfig.model_validate(base)


def test_parse_tool_call_variants():
    assert agent_runs.parse_tool_call("Final answer, no tools.") is None
    call = agent_runs.parse_tool_call('Working…\n```orrery-tool\n{"tool": "web_search", "args": {"query": "x"}}\n```')
    assert call == {"tool": "web_search", "args": {"query": "x"}}
    assert agent_runs.parse_tool_call("```orrery-tool\nnot json\n```")["malformed"] is True
    assert agent_runs.parse_tool_call('```orrery-tool\n{"args": {}}\n```')["malformed"] is True


def test_needs_approval_matrix():
    risks = ["local_write", "destructive"]
    assert agent_runs._needs_approval({"approval": "always"}, "read", risks)
    assert not agent_runs._needs_approval({"approval": "preapproved"}, "local_write", risks)
    assert agent_runs._needs_approval({"approval": "risk_based"}, "local_write", risks)
    assert not agent_runs._needs_approval({"approval": "risk_based"}, "network", risks)


def test_system_prompt_lists_only_granted_tools():
    config = _config().model_dump(mode="json")
    prompt = agent_runs._system_prompt(config)
    assert "web_search" in prompt
    assert "db_query" not in prompt
    assert "orrery-tool" in prompt


async def _make_agent(**overrides):
    from backend.core.migrations import run_migrations

    await run_migrations()
    created = await agents.create_agent(_config(**overrides))
    return created["id"]


async def _delete_agent(agent_id):
    from backend.core.database import get_sessionmaker
    from backend.core.models import Agent

    async with get_sessionmaker()() as s:
        row = await s.get(Agent, uuid.UUID(agent_id))
        if row is not None:
            await s.delete(row)
            await s.commit()


def _inline_dispatch(monkeypatch):
    async def dispatch(run_id):
        await agent_runs.execute_run(run_id)
    monkeypatch.setattr(agent_runs, "_dispatch", dispatch)


def _fake_model(replies):
    replies = iter(replies)

    async def stream(model, messages, system_prompt=None, effort=None, usage_out=None):
        yield next(replies)
    return stream


@pytest.mark.anyio
async def test_run_executes_tool_then_finishes(monkeypatch):
    from backend import tools as tool_registry
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        _inline_dispatch(monkeypatch)
        calls = []

        async def fake_run_tool(key, args=None, *, allowed=None, grant=None):
            calls.append((key, args, grant))
            return {"ok": True, "results": ["fact"]}

        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            'Searching.\n```orrery-tool\n{"tool": "web_search", "args": {"query": "orrery"}}\n```',
            "Done: the answer is 42.",
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None, input_text="Find the answer")
        run = await agent_runs.get_run(started["run_id"], owner_id=None)

        assert run["status"] == "succeeded"
        assert run["output_text"] == "Done: the answer is 42."
        assert calls and calls[0][0] == "web_search"
        kinds = [step["kind"] for step in run["steps"]]
        assert kinds == ["model", "tool", "model"]
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_risky_call_suspends_then_owner_approval_resumes(monkeypatch):
    from backend import tools as tool_registry
    from backend.providers import ai

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
    )
    try:
        _inline_dispatch(monkeypatch)
        executed = []

        async def fake_run_tool(key, args=None, *, allowed=None, grant=None):
            executed.append(key)
            return {"ok": True, "results": []}

        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
            "Finished after approval.",
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None)
        suspended = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert suspended["status"] == "awaiting_approval"
        assert executed == []  # nothing ran before the owner decided

        pending = await agent_runs.list_pending_approvals(owner_id=None)
        mine = [p for p in pending if p["run_id"] == started["run_id"]]
        assert len(mine) == 1
        decided = await agent_runs.decide_approval(mine[0]["id"], approve=True, owner_id=None)
        assert decided["status"] == "approved"

        resumed = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert resumed["status"] == "succeeded"
        assert executed == ["web_search"]
        assert resumed["output_text"] == "Finished after approval."
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_step_budget_stops_a_looping_agent(monkeypatch):
    from backend import tools as tool_registry
    from backend.providers import ai

    agent_id = await _make_agent(budgets={"max_steps_per_run": 2, "max_runtime_seconds": 300})
    try:
        _inline_dispatch(monkeypatch)

        async def fake_run_tool(key, args=None, *, allowed=None, grant=None):
            return {"ok": True}

        async def looping(model, messages, system_prompt=None, effort=None, usage_out=None):
            yield '```orrery-tool\n{"tool": "web_search", "args": {"query": "again"}}\n```'

        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", looping)

        started = await agent_runs.start_run(agent_id, owner_id=None)
        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "failed"
        assert "step budget" in run["error"].lower() or "2-step" in run["error"]
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_runs_per_day_budget_refuses_new_runs(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent(budgets={"max_runs_per_day": 1})
    try:
        _inline_dispatch(monkeypatch)
        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Instant answer."]))

        await agent_runs.start_run(agent_id, owner_id=None)
        with pytest.raises(ValueError, match="runs-per-day"):
            await agent_runs.start_run(agent_id, owner_id=None)
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_ungranted_tool_is_refused_in_run(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        _inline_dispatch(monkeypatch)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "crabbox_run", "args": {"command": "rm -rf /"}}\n```',
            "Understood — finishing without it.",
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None)
        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "succeeded"
        tool_steps = [s for s in run["steps"] if s["kind"] == "tool"]
        assert tool_steps and tool_steps[0]["status"] == "failed"
        assert "not granted" in (tool_steps[0]["detail"] or "")
    finally:
        await _delete_agent(agent_id)
