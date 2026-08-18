"""Fork and replay over the durable run log (ADR-004).

The invariant these rest on already existed: `_transcript()` rebuilds the model-bound conversation
from `agent_run_steps`, not from memory. That is what makes a branch reproducible.
"""
import asyncio
import sys
import uuid

import pytest

from backend.features import agent_runs, agents

# Marked at module scope: these exercise real persistence, so they need the PostgreSQL that
# `docker compose up -d` provides. The cross-platform CI job runs `-m "not db"`; the Linux
# job provides a pgvector service and requires them.
pytestmark = pytest.mark.db

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _config(**overrides):
    base = {
        "name": "Forker",
        "goal": "Answer the input.",
        "model": "openai/test",
        "tool_grants": [{"tool": "web_search", "actions": ["execute"]}],
        "budgets": {"max_steps_per_run": 4, "max_runtime_seconds": 300},
    }
    base.update(overrides)
    return agents.AgentConfig.model_validate(base)


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
async def test_replay_rebuilds_what_the_model_saw_from_the_log(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        _inline_dispatch(monkeypatch)
        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Done: 42."]))
        started = await agent_runs.start_run(agent_id, owner_id=None, input_text="Find the answer")

        out = await agent_runs.replay(started["run_id"], owner_id=None)

        assert out is not None
        assert out["messages"][0] == {"role": "user", "content": "Find the answer"}
        assert any(m["role"] == "assistant" and "42" in m["content"] for m in out["messages"])
        assert out["steps_used"] == out["steps_total"]
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_replay_can_be_truncated_to_a_step(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        _inline_dispatch(monkeypatch)
        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Done: 42."]))
        started = await agent_runs.start_run(agent_id, owner_id=None, input_text="Find it")

        whole = await agent_runs.replay(started["run_id"], owner_id=None)
        clipped = await agent_runs.replay(started["run_id"], owner_id=None, upto=0)

        assert clipped["steps_used"] <= whole["steps_used"]
        assert clipped["steps_total"] == whole["steps_total"]
        # the seed request is always there; it comes from the run, not from a step
        assert clipped["messages"][0]["content"] == "Find it"
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_fork_carries_the_log_and_runs_the_source_config(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        _inline_dispatch(monkeypatch)
        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Done: first."]))
        started = await agent_runs.start_run(agent_id, owner_id=None, input_text="Original")
        source = await agent_runs.get_run(started["run_id"], owner_id=None)

        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Done: branched."]))
        fork = await agent_runs.fork_run(started["run_id"], owner_id=None)

        assert fork["forked_from"] == started["run_id"]
        assert fork["run_id"] != started["run_id"]
        assert fork["steps_carried"] == len(source["steps"])

        branched = await agent_runs.get_run(fork["run_id"], owner_id=None)
        assert branched["status"] == "succeeded"
        # the branch reuses the source's frozen config snapshot, not whatever the agent is now
        assert branched["steps"][0]["kind"] == source["steps"][0]["kind"]
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_fork_can_replace_the_input(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        _inline_dispatch(monkeypatch)
        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Done: first."]))
        started = await agent_runs.start_run(agent_id, owner_id=None, input_text="Original")

        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Done: rephrased."]))
        fork = await agent_runs.fork_run(started["run_id"], owner_id=None, at_step=0,
                                         input_text="Ask it differently")

        replayed = await agent_runs.replay(fork["run_id"], owner_id=None)
        assert replayed["messages"][0]["content"] == "Ask it differently"
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_fork_and_replay_are_owner_scoped(monkeypatch):
    """Another owner's run must be invisible, not forkable."""
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        _inline_dispatch(monkeypatch)
        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Done."]))
        started = await agent_runs.start_run(agent_id, owner_id=None, input_text="Mine")

        assert await agent_runs.replay(started["run_id"], owner_id="someone-else") is None
        with pytest.raises(ValueError, match="Run not found"):
            await agent_runs.fork_run(started["run_id"], owner_id="someone-else")
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_forking_an_unknown_run_is_refused():
    with pytest.raises(ValueError, match="Run not found"):
        await agent_runs.fork_run("not-a-uuid", owner_id=None)
    with pytest.raises(ValueError, match="Run not found"):
        await agent_runs.fork_run(str(uuid.uuid4()), owner_id=None)


@pytest.mark.anyio
async def test_replay_of_an_unknown_run_is_none():
    assert await agent_runs.replay("not-a-uuid", owner_id=None) is None
    assert await agent_runs.replay(str(uuid.uuid4()), owner_id=None) is None
