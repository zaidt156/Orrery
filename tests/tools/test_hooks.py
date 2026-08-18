"""The ADR-004 seam: hooks may deny, observe, or annotate - never grant.

These tests exist to keep that one property true. If a hook can ever turn a refusal into an
execution, the seam has become a way to configure the security boundary away.
"""
import pytest

from backend import tools as tool_registry
from backend.tools import hooks


@pytest.fixture(autouse=True)
def _clean_hooks():
    hooks._clear()
    yield
    hooks._clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_no_hooks_registered_changes_nothing():
    """An empty registry must mean exactly the old behavior."""
    assert await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search")) is None
    assert await hooks.deny_reason_for_step(
        hooks.AgentStep(run_id="r", agent_id="a", step_index=0)
    ) is None


@pytest.mark.anyio
async def test_a_hook_can_deny_a_tool_call():
    async def refuse(call):
        return f"{call.key} is not allowed right now."

    hooks.register_pre_execute("test-policy", refuse)

    objection = await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search"))

    assert objection == ("test-policy", "web_search is not allowed right now.")


@pytest.mark.anyio
async def test_returning_none_is_not_approval_it_is_only_no_objection():
    """The guards in run_tool still refuse; a passive hook cannot revive a refused call."""
    async def no_objection(_call):
        return None

    hooks.register_pre_execute("permissive", no_objection)

    # 'web_search' is genuinely outside this scope's allow-list, so it must still be refused.
    result = await tool_registry.run_tool("web_search", {"query": "x"}, allowed=set())

    assert result["ok"] is False
    assert "allow-list" in result["error"]


@pytest.mark.anyio
async def test_unknown_tool_is_still_unknown_however_many_hooks_pass():
    async def no_objection(_call):
        return None

    hooks.register_pre_execute("permissive", no_objection)

    result = await tool_registry.run_tool("no_such_tool", {})

    assert result["ok"] is False
    assert "Unknown tool" in result["error"]


@pytest.mark.anyio
async def test_a_broken_hook_fails_closed():
    """A policy that raises must read as an objection, never as consent."""
    async def explode(_call):
        raise RuntimeError("policy backend is down")

    hooks.register_pre_execute("broken", explode)

    objection = await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search"))

    assert objection is not None
    assert objection[0] == "broken"


@pytest.mark.anyio
async def test_first_objection_wins_and_later_hooks_do_not_run():
    ran = []

    async def first(_call):
        ran.append("first")
        return "denied by the first"

    async def second(_call):
        ran.append("second")
        return None

    hooks.register_pre_execute("first", first)
    hooks.register_pre_execute("second", second)

    objection = await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search"))

    assert objection == ("first", "denied by the first")
    assert ran == ["first"]


@pytest.mark.anyio
async def test_registration_is_reversible():
    async def refuse(_call):
        return "no"

    unregister = hooks.register_pre_execute("temporary", refuse)
    assert await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search")) is not None

    unregister()

    assert await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search")) is None


@pytest.mark.anyio
async def test_a_hook_sees_who_is_calling():
    seen = []

    async def observe(call):
        seen.append(call.caller)
        return None

    hooks.register_pre_execute("observer", observe)

    await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search", grant={"actions": ["execute"]}))
    await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search", grant=None))

    assert seen == ["agent", "gate"]


@pytest.mark.anyio
async def test_a_hook_can_stop_an_agent_step():
    async def refuse(step):
        return f"stopped before step {step.step_index}"

    hooks.register_pre_step("budget-policy", refuse)

    objection = await hooks.deny_reason_for_step(
        hooks.AgentStep(run_id="r", agent_id="a", step_index=2, model="openai/gpt-4o")
    )

    assert objection == ("budget-policy", "stopped before step 2")
