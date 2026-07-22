"""The central tool-approval gate (TODO P0): risk-tiered policy, digest binding, replay and
expiry protection, the remembered allowlist, registry enforcement, and the chat wait flow."""
import asyncio
import sys

import pytest

from backend import tools as tool_registry
from backend.features import approvals, code_interpreter
from backend.tools.registry import get_tool

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

MCP_ARGS = {"server_id": "server-abc123", "tool": "send_message", "args": {"to": "x"}}


@pytest.fixture(autouse=True)
def clean_store():
    approvals._STORE.clear()
    yield
    approvals._STORE.clear()


@pytest.fixture(autouse=True)
def memory_appconfig(monkeypatch):
    """Allowlist reads/writes stay in memory — tests never touch real app settings."""
    from backend.core import appconfig
    settings: dict = {}

    async def get_setting(key, default=None):
        return settings.get(key, default)

    async def set_setting(key, value):
        settings[key] = value
        return value

    monkeypatch.setattr(appconfig, "get_setting", get_setting)
    monkeypatch.setattr(appconfig, "set_setting", set_setting)
    return settings


# ── policy ─────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_read_and_sandboxed_tools_never_prompt():
    for key in ("web_search", "doc_search", "db_query", "run_python", "run_shell",
                "file_generate", "dashboard_refresh"):
        verdict = await approvals.gate(get_tool(key), {})
        assert verdict["allowed"] is True, f"{key} must not require approval"


@pytest.mark.anyio
async def test_external_and_destructive_tools_require_approval():
    for key in ("mcp_call", "crabbox_run"):
        verdict = await approvals.gate(get_tool(key), dict(MCP_ARGS))
        assert verdict["allowed"] is False
        assert verdict["approval"]["id"] in approvals._STORE


# ── digest binding, replay, expiry ─────────────────────────────────────────────

@pytest.mark.anyio
async def test_approved_id_authorizes_exactly_once():
    tool = get_tool("mcp_call")
    request = (await approvals.gate(tool, dict(MCP_ARGS)))["approval"]
    await approvals.decide(request["id"], approve=True)

    first = await approvals.gate(tool, dict(MCP_ARGS), approval_id=request["id"])
    assert first["allowed"] is True
    replay = await approvals.gate(tool, dict(MCP_ARGS), approval_id=request["id"])
    assert replay["allowed"] is False  # single-use: the id can never authorize twice


@pytest.mark.anyio
async def test_tampered_arguments_invalidate_the_approval():
    tool = get_tool("mcp_call")
    request = (await approvals.gate(tool, dict(MCP_ARGS)))["approval"]
    await approvals.decide(request["id"], approve=True)

    tampered = dict(MCP_ARGS, args={"to": "attacker"})
    verdict = await approvals.gate(tool, tampered, approval_id=request["id"])
    assert verdict["allowed"] is False


@pytest.mark.anyio
async def test_expired_approval_is_refused():
    tool = get_tool("mcp_call")
    request = (await approvals.gate(tool, dict(MCP_ARGS)))["approval"]
    approvals._STORE[request["id"]].created -= approvals.PENDING_TTL_SECONDS + 1

    decided = await approvals.decide(request["id"], approve=True)
    assert decided["status"] == "expired"
    verdict = await approvals.gate(tool, dict(MCP_ARGS), approval_id=request["id"])
    assert verdict["allowed"] is False


@pytest.mark.anyio
async def test_denied_approval_never_executes():
    tool = get_tool("mcp_call")
    request = (await approvals.gate(tool, dict(MCP_ARGS)))["approval"]
    await approvals.decide(request["id"], approve=False)
    verdict = await approvals.gate(tool, dict(MCP_ARGS), approval_id=request["id"])
    assert verdict["allowed"] is False


# ── remembered allowlist ───────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_always_allow_remembers_per_server_and_tool(memory_appconfig):
    tool = get_tool("mcp_call")
    request = (await approvals.gate(tool, dict(MCP_ARGS)))["approval"]
    await approvals.decide(request["id"], approve=True, remember=True)

    again = await approvals.gate(tool, dict(MCP_ARGS))
    assert again["allowed"] is True  # asks once, not per call

    other_tool = dict(MCP_ARGS, tool="delete_everything")
    verdict = await approvals.gate(tool, other_tool)
    assert verdict["allowed"] is False  # the grant is per server+tool, not blanket MCP


# ── enforcement lives in the registry ──────────────────────────────────────────

@pytest.mark.anyio
async def test_run_tool_blocks_then_executes_with_approval(monkeypatch):
    from backend.features import mcp
    called = []

    async def fake_call(server_id, tool, args):
        called.append((server_id, tool))
        return {"ok": True, "text": "done"}

    monkeypatch.setattr(mcp, "call_tool_by_id", fake_call)

    blocked = await tool_registry.run_tool("mcp_call", dict(MCP_ARGS), allowed={"mcp_call"})
    assert blocked["ok"] is False
    assert blocked.get("approval")
    assert called == []  # nothing executed before the user decided

    await approvals.decide(blocked["approval"]["id"], approve=True)
    result = await tool_registry.run_tool(
        "mcp_call", dict(MCP_ARGS), allowed={"mcp_call"}, approval_id=blocked["approval"]["id"],
    )
    assert result["ok"] is True
    assert called == [("server-abc123", "send_message")]


@pytest.mark.anyio
async def test_agent_grant_path_keeps_its_own_gate(monkeypatch):
    """Agent runs pass a grant and use the durable AgentApproval flow — the registry gate
    must not double-prompt them."""
    from backend.features import mcp

    async def fake_call(server_id, tool, args):
        return {"ok": True, "text": "done"}

    monkeypatch.setattr(mcp, "call_tool_by_id", fake_call)
    grant = {"actions": ["execute"], "resources": {"server_id": ["server-abc123"]}}
    result = await tool_registry.run_tool("mcp_call", dict(MCP_ARGS), grant=grant)
    assert result["ok"] is True


# ── the chat loop pauses, surfaces the card, and resumes ───────────────────────

class FakeTrace:
    def step(self, stage, detail, **kwargs):
        return {"trace": {"stage": stage, "detail": detail, **kwargs}}

    def error(self, stage, detail):
        return {"trace": {"stage": stage, "detail": detail, "status": "error"}}


@pytest.mark.anyio
async def test_chat_turn_waits_for_approval_then_runs_the_tool(monkeypatch):
    from backend.features import admin, crabbox
    executed = []

    async def fake_stream_chat(model, work, formatted_prompt=None, effort=None, usage_out=None):
        if len(work) == 1:
            yield '```orrery-tool\n{"tool":"crabbox_run","args":{"shell":"echo hi"}}\n```'
        else:
            yield "Done after approval."

    async def fake_crabbox(command, shell, label, timeout_seconds):
        executed.append(shell)
        return {"stdout": "hi"}

    async def enabled(name):
        return True

    async def persist(text, artifacts):
        return "m1"

    monkeypatch.setattr(code_interpreter.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(crabbox, "run_command", fake_crabbox)
    monkeypatch.setattr(admin, "feature_enabled", enabled)

    async def approve_when_asked():
        for _ in range(500):
            pending = [e for e in approvals._STORE.values() if e.status == "pending"]
            if pending:
                await approvals.decide(pending[0].id, approve=True)
                return
            await asyncio.sleep(0.01)
        raise AssertionError("no approval was requested")

    approver = asyncio.ensure_future(approve_when_asked())
    events = [
        event
        async for event in code_interpreter.run(
            "openai/test", "system", [{"role": "user", "content": "run it"}], None,
            trace=FakeTrace(), persist=persist, allowed_tools={"crabbox_run"},
        )
    ]
    await approver

    assert executed == ["echo hi"]
    assert any("approval" in event for event in events)
    resolved = [event["approval_resolved"] for event in events if "approval_resolved" in event]
    assert resolved and resolved[0]["status"] == "approved"


@pytest.mark.anyio
async def test_chat_turn_continues_without_the_tool_when_denied(monkeypatch):
    from backend.features import admin, crabbox
    executed = []
    observations = []

    async def enabled(name):
        return True

    monkeypatch.setattr(admin, "feature_enabled", enabled)

    async def fake_stream_chat(model, work, formatted_prompt=None, effort=None, usage_out=None):
        if len(work) == 1:
            yield '```orrery-tool\n{"tool":"crabbox_run","args":{"shell":"rm -rf /"}}\n```'
        else:
            observations.append(work[-1]["content"])
            yield "I could not run that."

    async def fake_crabbox(command, shell, label, timeout_seconds):
        executed.append(shell)
        return {"stdout": ""}

    async def persist(text, artifacts):
        return "m1"

    monkeypatch.setattr(code_interpreter.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(crabbox, "run_command", fake_crabbox)

    async def deny_when_asked():
        for _ in range(500):
            pending = [e for e in approvals._STORE.values() if e.status == "pending"]
            if pending:
                await approvals.decide(pending[0].id, approve=False)
                return
            await asyncio.sleep(0.01)
        raise AssertionError("no approval was requested")

    denier = asyncio.ensure_future(deny_when_asked())
    events = [
        event
        async for event in code_interpreter.run(
            "openai/test", "system", [{"role": "user", "content": "run it"}], None,
            trace=FakeTrace(), persist=persist, allowed_tools={"crabbox_run"},
        )
    ]
    await denier

    assert executed == []  # denied means it never ran
    resolved = [event["approval_resolved"] for event in events if "approval_resolved" in event]
    assert resolved and resolved[0]["status"] == "denied"
    assert observations and "denied" in observations[0]


@pytest.mark.anyio
async def test_destructive_tools_are_never_remembered(memory_appconfig):
    """One benign approval of the remote executor must not become standing permission for
    arbitrary future commands."""
    tool = get_tool("crabbox_run")
    args = {"shell": "echo hi", "command": [], "label": "", "timeout_seconds": None}

    request = (await approvals.gate(tool, dict(args)))["approval"]
    assert request["rememberable"] is False

    await approvals.decide(request["id"], approve=True, remember=True)
    assert not memory_appconfig.get(approvals._ALLOWLIST_KEY)  # nothing was persisted

    again = await approvals.gate(tool, dict(args))
    assert again["allowed"] is False  # still asks next time
