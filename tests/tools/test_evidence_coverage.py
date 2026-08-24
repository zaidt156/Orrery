"""ADR-005 slice 1: every guarded tool call leaves evidence.

Slice 1's claim is not "some calls are recorded" but that the durable record answers *what did this
surface do*. That claim decays one call site at a time: a new branch calls `run_tool` without an
identity, the registry takes its `writer=None` path, and the gap is invisible because nothing fails.

Two kinds of test here. The behavioural ones drive the real chat tool loop and assert the identity
reaches the registry. The structural one walks the backend's syntax tree and refuses a `run_tool`
call that passes no execution identity at all — it is the cheap guard that catches the next omission
whether or not anyone writes a test for that branch.
"""
import ast
import pathlib

import pytest

from backend.features import code_interpreter

BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"

# Call sites that legitimately record nothing, each with the reason it is exempt.
_UNWIRED = {
    # tools/registry.py re-dispatches internally; the identity is already bound to the writer.
    "registry.py",
}


class FakeTrace:
    def step(self, stage, detail, **kwargs):
        return {"trace": {"stage": stage, "detail": detail, **kwargs}}

    def error(self, stage, detail):
        return {"trace": {"stage": stage, "detail": detail, "status": "error"}}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _run_tool_calls_without_execution() -> list[str]:
    """Every `run_tool(...)` in the backend that passes no `execution=` keyword."""
    offenders: list[str] = []
    for path in sorted(BACKEND.rglob("*.py")):
        if path.name in _UNWIRED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "run_tool":
                continue
            keywords = {kw.arg for kw in node.keywords}
            if "execution" not in keywords and None not in keywords:
                offenders.append(f"{path.relative_to(BACKEND.parent)}:{node.lineno}")
    return offenders


def test_every_backend_run_tool_call_carries_an_execution_identity():
    """The structural half of "evidence around every guarded tool call".

    A call site that omits `execution=` is not a lint nit: it is a tool call the durable record will
    never mention, and the registry will run it happily.
    """
    offenders = _run_tool_calls_without_execution()

    assert offenders == [], (
        "these run_tool call sites record no evidence: " + ", ".join(offenders)
    )


async def _drive_chat(monkeypatch, block: str):
    """Run one chat turn whose model emits `block`, returning the execution identities seen."""
    seen: list = []

    async def fake_stream_chat(model, work, formatted_prompt=None, effort=None, usage_out=None):
        if len(work) == 1:
            yield block
        else:
            yield "Done."

    async def fake_run_tool(key, args=None, *, allowed=None, approval_id=None, execution=None):
        seen.append((key, execution))
        return {"ok": True, "results": [], "exit_code": 0}

    async def persist(text, artifacts):
        return "m1"

    monkeypatch.setattr(code_interpreter.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(code_interpreter.tool_registry, "run_tool", fake_run_tool)

    async for _ in code_interpreter.run(
        "openai/test",
        "system",
        [{"role": "user", "content": "go"}],
        None,
        trace=FakeTrace(),
        persist=persist,
        allowed_tools={"run_python", "run_shell", "web_search"},
        conversation_id="c-1",
        owner_id="solo",
    ):
        pass
    return seen


@pytest.mark.anyio
async def test_sandboxed_python_from_chat_is_recorded(monkeypatch):
    seen = await _drive_chat(monkeypatch, "```orrery-run\nprint(1)\n```")

    assert seen, "the tool never ran"
    key, execution = seen[0]
    assert key == "run_python"
    assert execution is not None, "run_python left no evidence identity"
    assert execution.surface == "chat"
    assert execution.conversation_id == "c-1"


@pytest.mark.anyio
async def test_sandboxed_shell_from_chat_is_recorded(monkeypatch):
    seen = await _drive_chat(monkeypatch, "```orrery-shell\nls\n```")

    key, execution = seen[0]
    assert key == "run_shell"
    assert execution is not None, "run_shell left no evidence identity"
    assert execution.surface == "chat"


@pytest.mark.anyio
async def test_web_search_from_chat_is_recorded(monkeypatch):
    seen = await _drive_chat(monkeypatch, "```orrery-search\norrery workspace\n```")

    key, execution = seen[0]
    assert key == "web_search"
    assert execution is not None, "web_search left no evidence identity"
    assert execution.surface == "chat"


@pytest.mark.anyio
async def test_every_chat_tool_in_one_turn_shares_the_same_turn_id(monkeypatch):
    """A turn is one user message and everything it causes, so the id must not change mid-turn."""
    seen = await _drive_chat(
        monkeypatch,
        "```orrery-run\nprint(1)\n```\n\n```orrery-search\nwhat is orrery\n```",
    )

    assert len(seen) == 2, "both blocks should have run"
    turn_ids = {execution.turn_id for _, execution in seen}
    assert len(turn_ids) == 1, "one turn must mint exactly one turn id"


@pytest.mark.anyio
async def test_a_chat_caller_without_a_conversation_still_records_nothing(monkeypatch):
    """The opt-in stays opt-in: an unwired caller must not get an invented parent."""
    seen: list = []

    async def fake_stream_chat(model, work, formatted_prompt=None, effort=None, usage_out=None):
        if len(work) == 1:
            yield "```orrery-run\nprint(1)\n```"
        else:
            yield "Done."

    async def fake_run_tool(key, args=None, *, allowed=None, approval_id=None, execution=None):
        seen.append(execution)
        return {"ok": True, "exit_code": 0}

    async def persist(text, artifacts):
        return "m1"

    monkeypatch.setattr(code_interpreter.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(code_interpreter.tool_registry, "run_tool", fake_run_tool)

    async for _ in code_interpreter.run(
        "openai/test", "system", [{"role": "user", "content": "go"}], None,
        trace=FakeTrace(), persist=persist, allowed_tools={"run_python"},
    ):
        pass

    assert seen == [None], "a caller with no conversation must not invent a record parent"
