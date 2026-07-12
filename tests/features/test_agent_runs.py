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


def test_usage_parser_normalizes_nonnegative_finite_numeric_fields():
    usage = agent_runs._usage_dict(
        '{"tokens_in": "9", "tokens_out": -4, "cost": NaN, "active_seconds": Infinity}'
    )

    assert usage["tokens_in"] == 9
    assert usage["tokens_out"] == 0
    assert usage["cost"] == 0.0
    assert usage["active_seconds"] == 0.0


def test_daily_cost_buckets_events_by_timestamp_across_midnight():
    import datetime
    import json
    from types import SimpleNamespace

    before_midnight = datetime.datetime(2026, 7, 12, 23, 59, 59, tzinfo=datetime.timezone.utc)
    after_midnight = datetime.datetime(2026, 7, 13, 0, 0, 1, tzinfo=datetime.timezone.utc)
    runs = [
        SimpleNamespace(
            created_at=after_midnight,
            usage=json.dumps({
                "cost": 0.7,
                "cost_events": [{"at": before_midnight.isoformat(), "cost": 0.7}],
            }),
        ),
        SimpleNamespace(
            created_at=before_midnight,
            usage=json.dumps({
                "cost": 0.3,
                "cost_events": [{"at": after_midnight.isoformat(), "cost": 0.3}],
                "cost_reservation": {"day": "2026-07-13", "amount": 0.4},
            }),
        ),
    ]

    actual, reserved = agent_runs._daily_cost_totals(runs, "2026-07-13")

    assert actual == pytest.approx(0.3)
    assert reserved == pytest.approx(0.4)


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


def _pause_after_model_step(monkeypatch):
    """Pause the worker after its model trace is durable, at the action/cancel race boundary."""
    original = agent_runs._record_step
    model_recorded = asyncio.Event()
    release = asyncio.Event()

    async def record(*args, **kwargs):
        await original(*args, **kwargs)
        if len(args) > 1 and args[1] == "model":
            model_recorded.set()
            await release.wait()

    monkeypatch.setattr(agent_runs, "_record_step", record)
    return model_recorded, release


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
async def test_cancelling_suspended_run_rejects_approval_and_prevents_tool_execution(monkeypatch):
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
            return {"ok": True}

        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None)
        pending = [
            item for item in await agent_runs.list_pending_approvals(owner_id=None)
            if item["run_id"] == started["run_id"]
        ]
        assert len(pending) == 1

        assert await agent_runs.cancel_run(started["run_id"], owner_id=None)
        cancelled = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert cancelled["status"] == "cancelled"
        assert pending[0]["id"] not in {
            item["id"] for item in await agent_runs.list_pending_approvals(owner_id=None)
        }

        decided = await agent_runs.decide_approval(
            pending[0]["id"], approve=True, owner_id=None
        )
        assert decided["status"] == "rejected"
        assert executed == []
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_cancel_after_model_prevents_direct_tool_from_starting(monkeypatch):
    from backend import tools as tool_registry
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        async def leave_queued(_run_id):
            return None

        executed = []

        async def fake_run_tool(key, args=None, *, allowed=None, grant=None):
            executed.append(key)
            return {"ok": True}

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))
        model_recorded, release = _pause_after_model_step(monkeypatch)

        started = await agent_runs.start_run(agent_id, owner_id=None)
        worker = asyncio.create_task(agent_runs.execute_run(started["run_id"]))
        await asyncio.wait_for(model_recorded.wait(), timeout=2)
        assert await agent_runs.cancel_run(started["run_id"], owner_id=None)
        release.set()
        await asyncio.wait_for(worker, timeout=2)

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "cancelled"
        assert executed == []
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_cancel_after_model_prevents_pending_approval_creation(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
    )
    try:
        async def leave_queued(_run_id):
            return None

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))
        model_recorded, release = _pause_after_model_step(monkeypatch)

        started = await agent_runs.start_run(agent_id, owner_id=None)
        worker = asyncio.create_task(agent_runs.execute_run(started["run_id"]))
        await asyncio.wait_for(model_recorded.wait(), timeout=2)
        assert await agent_runs.cancel_run(started["run_id"], owner_id=None)
        release.set()
        await asyncio.wait_for(worker, timeout=2)

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "cancelled"
        assert not [
            item for item in await agent_runs.list_pending_approvals(owner_id=None)
            if item["run_id"] == started["run_id"]
        ]
        assert not [step for step in run["steps"] if step["kind"] == "approval"]
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_schedule_replace_cancels_waiting_run_and_rejects_approval(monkeypatch):
    import datetime

    from backend import tools as tool_registry
    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentSchedule
    from backend.providers import ai
    from sqlalchemy import select

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
        trigger_modes=["manual", "schedule"],
        schedule={
            "enabled": True,
            "cron": "* * * * *",
            "timezone": "UTC",
            "concurrency_policy": "replace",
        },
    )
    executed = []
    try:
        async def leave_queued(_run_id):
            return None

        async def fake_run_tool(key, args=None, *, allowed=None, grant=None):
            executed.append(key)
            return {"ok": True}

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))
        started = await agent_runs.start_run(agent_id, owner_id=None)
        await agent_runs.execute_run(started["run_id"])
        pending = [
            item for item in await agent_runs.list_pending_approvals(owner_id=None)
            if item["run_id"] == started["run_id"]
        ]
        assert len(pending) == 1

        async with get_sessionmaker()() as s:
            schedule = (await s.execute(
                select(AgentSchedule).where(
                    AgentSchedule.agent_id == uuid.UUID(agent_id)
                )
            )).scalar_one()
            schedule.next_fire_at = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
            )
            await s.commit()

        scheduled = []

        async def capture_scheduled(agent_id, **kwargs):
            scheduled.append(agent_id)
            return {"run_id": "replacement"}

        monkeypatch.setattr(agent_runs, "start_run", capture_scheduled)
        await agent_runs.schedule_tick()

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        decision = await agent_runs.decide_approval(
            pending[0]["id"], approve=True, owner_id=None,
        )
        assert scheduled == [agent_id]
        assert run["status"] == "cancelled"
        assert decision["status"] == "rejected"
        assert executed == []
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_approval_state_and_trace_commit_atomically(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
    )
    try:
        async def leave_queued(_run_id):
            return None

        original = agent_runs._record_step

        async def fail_separate_approval_trace(*args, **kwargs):
            if len(args) > 1 and args[1] == "approval":
                raise RuntimeError("approval trace must share the state transaction")
            await original(*args, **kwargs)

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(agent_runs, "_record_step", fail_separate_approval_trace)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None)
        await agent_runs.execute_run(started["run_id"])

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        approval_steps = [step for step in run["steps"] if step["kind"] == "approval"]
        assert run["status"] == "awaiting_approval"
        assert len(approval_steps) == 1
        assert approval_steps[0]["status"] == "pending"
        assert approval_steps[0]["approval_id"]
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_approved_action_is_claimed_then_cooperatively_cancelled(monkeypatch):
    from backend import tools as tool_registry
    from backend.providers import ai

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
    )
    tool_started = asyncio.Event()
    release_tool = asyncio.Event()
    executed = []
    cancel_task = None
    try:
        async def leave_queued(_run_id):
            return None

        async def gated_tool(key, args=None, *, allowed=None, grant=None):
            tool_started.set()
            await release_tool.wait()
            executed.append(key)
            return {"ok": True}

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(tool_registry, "run_tool", gated_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None)
        await agent_runs.execute_run(started["run_id"])
        pending = [
            item for item in await agent_runs.list_pending_approvals(owner_id=None)
            if item["run_id"] == started["run_id"]
        ]
        assert len(pending) == 1

        approval_task = asyncio.create_task(agent_runs.decide_approval(
            pending[0]["id"], approve=True, owner_id=None,
        ))
        await asyncio.wait_for(tool_started.wait(), timeout=2)
        cancel_task = asyncio.create_task(agent_runs.cancel_run(
            started["run_id"], owner_id=None,
        ))
        assert await asyncio.wait_for(cancel_task, timeout=0.3)
        decision = await asyncio.wait_for(approval_task, timeout=2)

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert decision["status"] == "approved"
        assert run["status"] == "cancelled"
        assert executed == []
        claim = run["usage"]["action_claims"][pending[0]["id"]]
        assert claim["status"] == "unknown"
    finally:
        release_tool.set()
        if cancel_task is not None and not cancel_task.done():
            await cancel_task
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_approved_action_claim_prevents_replay_after_recording_commit_failure(monkeypatch):
    from backend import tools as tool_registry
    from backend.providers import ai
    from sqlalchemy.ext.asyncio import AsyncSession

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
    )
    executions = []
    try:
        async def leave_queued(_run_id):
            return None

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))
        started = await agent_runs.start_run(agent_id, owner_id=None)
        await agent_runs.execute_run(started["run_id"])
        pending = [
            item for item in await agent_runs.list_pending_approvals(owner_id=None)
            if item["run_id"] == started["run_id"]
        ]
        assert len(pending) == 1

        tool_finished = False

        async def side_effect(key, args=None, *, allowed=None, grant=None):
            nonlocal tool_finished
            executions.append(key)
            tool_finished = True
            return {"ok": True}

        original_commit = AsyncSession.commit
        failed_recording_commit = False

        async def fail_once_after_side_effect(session):
            nonlocal failed_recording_commit
            if tool_finished and not failed_recording_commit:
                failed_recording_commit = True
                raise RuntimeError("simulated crash before result commit")
            await original_commit(session)

        monkeypatch.setattr(tool_registry, "run_tool", side_effect)
        monkeypatch.setattr(AsyncSession, "commit", fail_once_after_side_effect)

        try:
            await agent_runs.decide_approval(pending[0]["id"], approve=True, owner_id=None)
        except RuntimeError:
            pass
        second = await agent_runs.decide_approval(
            pending[0]["id"], approve=True, owner_id=None,
        )

        assert second["status"] == "approved"
        assert executions == ["web_search"]
        claimed = await agent_runs.get_run(started["run_id"], owner_id=None)
        claim = claimed["usage"]["action_claims"][pending[0]["id"]]
        assert claim["execution_id"]
        assert claim["status"] == "claimed"

        await agent_runs.reconcile_orphans()
        recovered = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert recovered["status"] == "interrupted"
        assert recovered["usage"]["action_claims"][pending[0]["id"]]["status"] == "unknown"
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_expired_approval_resumes_without_executing_tool(monkeypatch):
    import datetime

    from backend import tools as tool_registry
    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentApproval
    from backend.providers import ai

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
    )
    try:
        _inline_dispatch(monkeypatch)
        executed = []

        async def fake_run_tool(key, args=None, *, allowed=None, grant=None):
            executed.append(key)
            return {"ok": True}

        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
            "Finished safely without the expired action.",
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None)
        pending = [
            item for item in await agent_runs.list_pending_approvals(owner_id=None)
            if item["run_id"] == started["run_id"]
        ]
        assert len(pending) == 1
        async with get_sessionmaker()() as s:
            approval = await s.get(AgentApproval, uuid.UUID(pending[0]["id"]))
            approval.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
            await s.commit()

        decided = await agent_runs.decide_approval(pending[0]["id"], approve=True, owner_id=None)

        assert decided["status"] == "expired"
        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "succeeded"
        assert run["output_text"] == "Finished safely without the expired action."
        assert executed == []
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_listing_approvals_expires_stale_action_and_resumes_run(monkeypatch):
    import datetime

    from backend import tools as tool_registry
    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentApproval
    from backend.providers import ai

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
    )
    try:
        _inline_dispatch(monkeypatch)
        executed = []

        async def fake_run_tool(key, args=None, *, allowed=None, grant=None):
            executed.append(key)
            return {"ok": True}

        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
            "Continued after automatic expiry.",
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None)
        pending = [
            item for item in await agent_runs.list_pending_approvals(owner_id=None)
            if item["run_id"] == started["run_id"]
        ]
        assert len(pending) == 1
        async with get_sessionmaker()() as s:
            approval = await s.get(AgentApproval, uuid.UUID(pending[0]["id"]))
            approval.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
            await s.commit()

        listed = await agent_runs.list_pending_approvals(owner_id=None)

        assert pending[0]["id"] not in {item["id"] for item in listed}
        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "succeeded"
        assert run["output_text"] == "Continued after automatic expiry."
        assert executed == []
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_approved_tool_cannot_start_after_runtime_budget_is_spent(monkeypatch):
    from backend import tools as tool_registry
    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentRun
    from backend.providers import ai

    agent_id = await _make_agent(
        tool_grants=[{"tool": "web_search", "actions": ["execute"], "approval": "always"}],
        budgets={"max_steps_per_run": 4, "max_runtime_seconds": 15},
    )
    try:
        _inline_dispatch(monkeypatch)
        executed = []

        async def fake_run_tool(key, args=None, *, allowed=None, grant=None):
            executed.append(key)
            return {"ok": True}

        monkeypatch.setattr(tool_registry, "run_tool", fake_run_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))

        started = await agent_runs.start_run(agent_id, owner_id=None)
        pending = [
            item for item in await agent_runs.list_pending_approvals(owner_id=None)
            if item["run_id"] == started["run_id"]
        ]
        async with get_sessionmaker()() as s:
            run_row = await s.get(AgentRun, uuid.UUID(started["run_id"]))
            run_row.usage = '{"active_seconds": 15}'
            await s.commit()

        decided = await agent_runs.decide_approval(pending[0]["id"], approve=True, owner_id=None)

        assert decided["status"] == "rejected"
        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "failed"
        assert "runtime budget" in run["error"]
        assert executed == []
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
async def test_runs_per_day_budget_serializes_concurrent_starts(monkeypatch):
    agent_id = await _make_agent(budgets={"max_runs_per_day": 1})
    try:
        async def leave_queued(_run_id):
            return None

        original_runs_today = agent_runs._runs_today
        both_counting = asyncio.Event()
        arrivals = 0

        async def synchronized_count(session, parsed_agent_id):
            nonlocal arrivals
            count = await original_runs_today(session, parsed_agent_id)
            arrivals += 1
            if arrivals >= 2:
                both_counting.set()
            try:
                await asyncio.wait_for(both_counting.wait(), timeout=0.1)
            except TimeoutError:
                pass  # the Agent row lock correctly kept the other starter outside
            return count

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(agent_runs, "_runs_today", synchronized_count)
        results = await asyncio.gather(
            agent_runs.start_run(agent_id, owner_id=None),
            agent_runs.start_run(agent_id, owner_id=None),
            return_exceptions=True,
        )

        started = [item for item in results if isinstance(item, dict)]
        refused = [item for item in results if isinstance(item, ValueError)]
        assert len(started) == 1
        assert len(refused) == 1
        assert "runs-per-day" in str(refused[0])
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_daily_cost_budget_counts_previous_runs(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent(budgets={
        "max_steps_per_run": 4,
        "max_runtime_seconds": 300,
        "max_runs_per_day": 4,
        "max_cost_usd_per_day": 1.0,
    })
    try:
        _inline_dispatch(monkeypatch)
        model_calls = 0

        async def costly_reply(model, messages, system_prompt=None, effort=None, usage_out=None):
            nonlocal model_calls
            model_calls += 1
            usage_out["cost"] = 1.1
            yield "Finished."

        monkeypatch.setattr(ai, "stream_chat", costly_reply)

        first = await agent_runs.start_run(agent_id, owner_id=None)
        first_run = await agent_runs.get_run(first["run_id"], owner_id=None)
        assert first_run["status"] == "failed"
        assert "reported cost" in first_run["error"]

        second = await agent_runs.start_run(agent_id, owner_id=None)
        second_run = await agent_runs.get_run(second["run_id"], owner_id=None)
        assert second_run["status"] == "failed"
        assert "daily API cost budget" in second_run["error"]
        assert model_calls == 1
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_daily_cost_reservation_serializes_concurrent_model_calls(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent(budgets={
        "max_steps_per_run": 4,
        "max_runtime_seconds": 300,
        "max_runs_per_day": 4,
        "max_cost_usd_per_day": 1.0,
    })
    model_started = asyncio.Event()
    release_model = asyncio.Event()
    model_calls = 0
    try:
        async def leave_queued(_run_id):
            return None

        async def gated_cost(model, messages, system_prompt=None, effort=None, usage_out=None):
            nonlocal model_calls
            model_calls += 1
            model_started.set()
            await release_model.wait()
            usage_out["cost"] = 0.4
            yield "Finished."

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(ai, "stream_chat", gated_cost)
        first = await agent_runs.start_run(agent_id, owner_id=None)
        second = await agent_runs.start_run(agent_id, owner_id=None)
        workers = [
            asyncio.create_task(agent_runs.execute_run(first["run_id"])),
            asyncio.create_task(agent_runs.execute_run(second["run_id"])),
        ]
        await asyncio.wait_for(model_started.wait(), timeout=2)
        await asyncio.sleep(0.1)

        assert model_calls == 1
        release_model.set()
        await asyncio.wait_for(asyncio.gather(*workers), timeout=2)
        runs = [
            await agent_runs.get_run(first["run_id"], owner_id=None),
            await agent_runs.get_run(second["run_id"], owner_id=None),
        ]
        assert sorted(run["status"] for run in runs) == ["failed", "succeeded"]
        assert any("daily API cost budget" in (run["error"] or "") for run in runs)
    finally:
        release_model.set()
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_provider_reported_cost_overrun_is_recorded_and_fails_run(monkeypatch):
    import datetime
    import json

    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentRun
    from backend.providers import ai

    agent_id = await _make_agent(budgets={
        "max_steps_per_run": 4,
        "max_runtime_seconds": 300,
        "max_runs_per_day": 4,
        "max_cost_usd_per_day": 1.0,
    })
    try:
        async def leave_queued(_run_id):
            return None

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        previous = await agent_runs.start_run(agent_id, owner_id=None)
        now = datetime.datetime.now(datetime.timezone.utc)
        async with get_sessionmaker()() as s:
            row = await s.get(AgentRun, uuid.UUID(previous["run_id"]))
            row.status = "succeeded"
            row.usage = json.dumps({
                "cost": 0.9,
                "cost_events": [{"at": now.isoformat(), "cost": 0.9}],
            })
            await s.commit()

        async def over_budget(model, messages, system_prompt=None, effort=None, usage_out=None):
            usage_out["cost"] = 0.2
            yield "Should not be accepted as success."

        monkeypatch.setattr(ai, "stream_chat", over_budget)
        started = await agent_runs.start_run(agent_id, owner_id=None)
        await agent_runs.execute_run(started["run_id"])

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "failed"
        assert "reported cost" in run["error"]
        assert run["output_text"] is None
        assert run["usage"]["cost"] == pytest.approx(0.2)
        assert run["usage"]["cost_events"][0]["cost"] == pytest.approx(0.2)
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_malformed_historical_usage_does_not_disable_cost_capped_agent(monkeypatch):
    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentRun
    from backend.providers import ai

    agent_id = await _make_agent(budgets={
        "max_steps_per_run": 4,
        "max_runtime_seconds": 300,
        "max_runs_per_day": 4,
        "max_cost_usd_per_day": 1.0,
    })
    try:
        async def leave_queued(_run_id):
            return None

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        old = await agent_runs.start_run(agent_id, owner_id=None)
        async with get_sessionmaker()() as s:
            old_row = await s.get(AgentRun, uuid.UUID(old["run_id"]))
            old_row.status = "succeeded"
            old_row.usage = "[1]"
            await s.commit()

        _inline_dispatch(monkeypatch)
        monkeypatch.setattr(ai, "stream_chat", _fake_model(["Still works."]))
        started = await agent_runs.start_run(agent_id, owner_id=None)
        run = await agent_runs.get_run(started["run_id"], owner_id=None)

        assert run["status"] == "succeeded"
        assert run["output_text"] == "Still works."
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_runtime_budget_is_a_hard_deadline_during_model_call(monkeypatch):
    import datetime

    from backend.providers import ai

    agent_id = await _make_agent(budgets={
        "max_steps_per_run": 4,
        "max_runtime_seconds": 15,
    })
    try:
        _inline_dispatch(monkeypatch)
        base = datetime.datetime.now(datetime.timezone.utc)
        now_calls = 0

        def almost_expired_now():
            nonlocal now_calls
            now_calls += 1
            # _runs_today reads the clock before execute_run stamps started_at.
            return base if now_calls <= 2 else base + datetime.timedelta(seconds=14.99)

        async def slow_reply(model, messages, system_prompt=None, effort=None, usage_out=None):
            usage_out["cost"] = 0.25
            await asyncio.sleep(0.1)
            yield "Too late."

        monkeypatch.setattr(agent_runs, "_now", almost_expired_now)
        monkeypatch.setattr(ai, "stream_chat", slow_reply)

        started = await agent_runs.start_run(agent_id, owner_id=None)
        run = await agent_runs.get_run(started["run_id"], owner_id=None)

        assert run["status"] == "failed"
        assert "runtime budget" in run["error"]
        assert run["output_text"] is None
        assert run["usage"]["cost"] == 0.25
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_runtime_budget_cancels_a_slow_direct_tool(monkeypatch):
    import datetime

    from backend import tools as tool_registry
    from backend.providers import ai

    agent_id = await _make_agent(budgets={
        "max_steps_per_run": 4,
        "max_runtime_seconds": 15,
    })
    try:
        _inline_dispatch(monkeypatch)
        base = datetime.datetime.now(datetime.timezone.utc)
        now_calls = 0
        completed = []

        def almost_expired_before_tool():
            nonlocal now_calls
            now_calls += 1
            return base if now_calls <= 3 else base + datetime.timedelta(seconds=14.99)

        async def one_tool_call(model, messages, system_prompt=None, effort=None, usage_out=None):
            yield '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```'

        async def slow_tool(key, args=None, *, allowed=None, grant=None):
            await asyncio.sleep(0.1)
            completed.append(key)
            return {"ok": True}

        monkeypatch.setattr(agent_runs, "_now", almost_expired_before_tool)
        monkeypatch.setattr(ai, "stream_chat", one_tool_call)
        monkeypatch.setattr(tool_registry, "run_tool", slow_tool)

        started = await agent_runs.start_run(agent_id, owner_id=None)
        run = await agent_runs.get_run(started["run_id"], owner_id=None)

        assert run["status"] == "failed"
        assert "runtime budget" in run["error"]
        assert completed == []
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_cancel_interrupts_inflight_model_without_waiting_for_provider(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent()
    model_started = asyncio.Event()
    release_model = asyncio.Event()
    worker = None
    try:
        async def leave_queued(_run_id):
            return None

        async def hanging_model(model, messages, system_prompt=None, effort=None, usage_out=None):
            model_started.set()
            await release_model.wait()
            yield "late"

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(ai, "stream_chat", hanging_model)
        started = await agent_runs.start_run(agent_id, owner_id=None)
        worker = asyncio.create_task(agent_runs.execute_run(started["run_id"]))
        await asyncio.wait_for(model_started.wait(), timeout=2)

        assert await agent_runs.cancel_run(started["run_id"], owner_id=None)
        done, _ = await asyncio.wait({worker}, timeout=0.3)

        assert worker in done
        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "cancelled"
    finally:
        release_model.set()
        if worker is not None and not worker.done():
            await worker
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_cancel_interrupts_inflight_tool_without_waiting_for_tool(monkeypatch):
    from backend import tools as tool_registry
    from backend.providers import ai

    agent_id = await _make_agent()
    tool_started = asyncio.Event()
    release_tool = asyncio.Event()
    worker = None
    cancel_task = None
    try:
        async def leave_queued(_run_id):
            return None

        async def hanging_tool(key, args=None, *, allowed=None, grant=None):
            tool_started.set()
            await release_tool.wait()
            return {"ok": True}

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(tool_registry, "run_tool", hanging_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))
        started = await agent_runs.start_run(agent_id, owner_id=None)
        worker = asyncio.create_task(agent_runs.execute_run(started["run_id"]))
        await asyncio.wait_for(tool_started.wait(), timeout=2)

        cancel_task = asyncio.create_task(agent_runs.cancel_run(
            started["run_id"], owner_id=None,
        ))
        done, _ = await asyncio.wait({worker, cancel_task}, timeout=0.3)

        assert worker in done
        assert cancel_task in done
        assert cancel_task.result() is True
        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "cancelled"
    finally:
        release_tool.set()
        for task in (worker, cancel_task):
            if task is not None and not task.done():
                await task
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_model_timeout_persists_tokens_in_without_other_usage_fields(monkeypatch):
    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentRun
    from backend.providers import ai

    agent_id = await _make_agent(budgets={
        "max_steps_per_run": 4,
        "max_runtime_seconds": 15,
    })
    try:
        async def leave_queued(_run_id):
            return None

        async def tokens_then_stall(model, messages, system_prompt=None, effort=None, usage_out=None):
            usage_out["tokens_in"] = 23
            await asyncio.sleep(0.3)
            yield "Too late."

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(ai, "stream_chat", tokens_then_stall)
        started = await agent_runs.start_run(agent_id, owner_id=None)
        async with get_sessionmaker()() as s:
            row = await s.get(AgentRun, uuid.UUID(started["run_id"]))
            row.usage = '{"active_seconds": 14.9}'
            await s.commit()

        await agent_runs.execute_run(started["run_id"])

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "failed"
        assert "runtime budget" in run["error"]
        assert run["usage"]["tokens_in"] == 23
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_direct_tool_timeout_subtracts_accumulated_active_seconds(monkeypatch):
    from backend import tools as tool_registry
    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentRun
    from backend.providers import ai

    agent_id = await _make_agent(budgets={
        "max_steps_per_run": 4,
        "max_runtime_seconds": 15,
    })
    completed = []
    try:
        async def leave_queued(_run_id):
            return None

        async def slow_tool(key, args=None, *, allowed=None, grant=None):
            await asyncio.sleep(0.3)
            completed.append(key)
            return {"ok": True}

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(tool_registry, "run_tool", slow_tool)
        monkeypatch.setattr(ai, "stream_chat", _fake_model([
            '```orrery-tool\n{"tool": "web_search", "args": {"query": "q"}}\n```',
        ]))
        started = await agent_runs.start_run(agent_id, owner_id=None)
        async with get_sessionmaker()() as s:
            row = await s.get(AgentRun, uuid.UUID(started["run_id"]))
            row.usage = '{"active_seconds": 14.9}'
            await s.commit()

        await agent_runs.execute_run(started["run_id"])

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "failed"
        assert "runtime budget" in run["error"]
        assert completed == []
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_second_worker_does_not_reexecute_an_already_running_run(monkeypatch):
    from backend.core.database import get_sessionmaker
    from backend.core.models import AgentRun
    from backend.providers import ai

    agent_id = await _make_agent()
    try:
        async def leave_queued(_run_id):
            return None

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        started = await agent_runs.start_run(agent_id, owner_id=None)
        async with get_sessionmaker()() as s:
            row = await s.get(AgentRun, uuid.UUID(started["run_id"]))
            row.status = "running"
            await s.commit()

        model_calls = 0

        async def must_not_run(model, messages, system_prompt=None, effort=None, usage_out=None):
            nonlocal model_calls
            model_calls += 1
            yield "Duplicate execution."

        monkeypatch.setattr(ai, "stream_chat", must_not_run)

        await agent_runs.execute_run(started["run_id"])

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "running"
        assert run["steps"] == []
        assert model_calls == 0
    finally:
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_two_concurrent_workers_claim_a_queued_run_exactly_once(monkeypatch):
    from backend.providers import ai

    agent_id = await _make_agent()
    model_entered = asyncio.Event()
    release_model = asyncio.Event()
    model_calls = 0
    try:
        async def leave_queued(_run_id):
            return None

        async def gated_model(model, messages, system_prompt=None, effort=None, usage_out=None):
            nonlocal model_calls
            model_calls += 1
            model_entered.set()
            await release_model.wait()
            yield "Exactly once."

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        monkeypatch.setattr(ai, "stream_chat", gated_model)
        started = await agent_runs.start_run(agent_id, owner_id=None)

        first = asyncio.create_task(agent_runs.execute_run(started["run_id"]))
        second = asyncio.create_task(agent_runs.execute_run(started["run_id"]))
        await asyncio.wait_for(model_entered.wait(), timeout=2)
        await asyncio.sleep(0.05)
        release_model.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=2)

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert model_calls == 1
        assert run["status"] == "succeeded"
        assert [step["kind"] for step in run["steps"]] == ["model"]
    finally:
        release_model.set()
        await _delete_agent(agent_id)


@pytest.mark.anyio
async def test_boot_reconcile_redispatches_stranded_queued_run(monkeypatch):
    agent_id = await _make_agent()
    try:
        async def leave_queued(_run_id):
            return None

        monkeypatch.setattr(agent_runs, "_dispatch", leave_queued)
        started = await agent_runs.start_run(agent_id, owner_id=None)
        dispatched = []

        async def capture_dispatch(run_id):
            dispatched.append(run_id)

        monkeypatch.setattr(agent_runs, "_dispatch", capture_dispatch)
        await agent_runs.reconcile_orphans()

        run = await agent_runs.get_run(started["run_id"], owner_id=None)
        assert run["status"] == "queued"
        assert started["run_id"] in dispatched
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
