import sys
import types
from types import SimpleNamespace

import pytest

from backend.features import chat, code_interpreter, research, websearch
from backend.features.reasoning_trace import ReasoningTrace
from backend.features.taskrouter import TaskPlan
from backend.tools.registry import run_tool


class _FakeDDGS:
    rows: list[object] = []

    def __init__(self, *args, **kwargs):
        self.options = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def text(self, _query, **_kwargs):
        return list(self.rows)


def test_search_filters_malformed_and_unsafe_results(monkeypatch):
    _FakeDDGS.rows = [
        {
            "title": "  Useful\n result  ",
            "href": "https://example.com/article",
            "body": "  A useful\t summary  ",
        },
        {"title": "Unsafe", "href": "javascript:alert(1)", "body": "ignore"},
        "not a result mapping",
        {
            "title": "Duplicate",
            "href": "https://example.com/article",
            "body": "duplicate",
        },
        {"title": "", "url": "http://example.org/news", "snippet": "  Other result  "},
    ]
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=_FakeDDGS))

    results = websearch._search_sync("query", 10)

    assert results == [
        {
            "title": "Useful result",
            "url": "https://example.com/article",
            "snippet": "A useful summary",
        },
        {
            "title": "http://example.org/news",
            "url": "http://example.org/news",
            "snippet": "Other result",
        },
    ]


def test_format_results_keeps_only_safe_bounded_rows():
    formatted = websearch.format_results(
        [
            {"title": " Good\nsource ", "url": "https://example.com", "snippet": " Useful\ttext "},
            {"title": "Bad", "url": "javascript:alert(1)", "snippet": "ignore"},
            "malformed",
        ]
    )

    assert formatted == "[1] Good source — https://example.com\nUseful text"


@pytest.mark.anyio
async def test_search_bounds_direct_call_inputs(monkeypatch):
    seen = {}

    def fake_search_sync(query, max_results):
        seen.update(query=query, max_results=max_results)
        return []

    monkeypatch.setattr(websearch, "_search_sync", fake_search_sync)

    await websearch.search("  " + "x" * 1_000 + "  ", max_results=1_000)

    assert seen == {"query": "x" * 400, "max_results": 10}


@pytest.mark.anyio
async def test_search_redacts_pii_and_secrets_before_network_call(monkeypatch):
    seen = {}

    def fake_search_sync(query, max_results):
        seen.update(query=query, max_results=max_results)
        return []

    monkeypatch.setattr(websearch, "_search_sync", fake_search_sync)

    await websearch.search(
        "Find alice@example.com using sk-proj-verysecret12345",
        max_results=2,
    )

    assert seen == {
        "query": "Find [email] using [redacted]",
        "max_results": 2,
    }


@pytest.mark.anyio
async def test_search_detailed_reports_provider_failure(monkeypatch):
    class FailingDDGS(_FakeDDGS):
        def text(self, _query, **_kwargs):
            raise TimeoutError("provider leaked detail")

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FailingDDGS))

    outcome = await websearch.search_detailed("current events", max_results=2)

    assert outcome == {
        "status": "error",
        "results": [],
        "error": "The web-search provider did not respond. Try again later.",
    }


@pytest.mark.anyio
async def test_search_detailed_contains_unexpected_provider_shapes(monkeypatch):
    def malformed_provider(*_args, **_kwargs):
        raise TypeError("provider leaked implementation detail")

    monkeypatch.setattr(websearch, "_search_sync", malformed_provider)

    outcome = await websearch.search_detailed("current events", max_results=2)

    assert outcome == {
        "status": "error",
        "results": [],
        "error": "The web-search provider did not respond. Try again later.",
    }


@pytest.mark.anyio
async def test_web_search_tool_enforces_feature_gate(monkeypatch):
    from backend.features import admin

    called = False

    async def disabled(_name):
        return False

    async def fake_search(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(admin, "feature_enabled", disabled)
    monkeypatch.setattr(websearch, "search", fake_search)

    result = await run_tool("web_search", {"query": "latest news"}, allowed={"web_search"})

    assert result["ok"] is False
    assert "disabled" in result["error"].lower()
    assert called is False


@pytest.mark.anyio
async def test_web_search_tool_reports_missing_dependency(monkeypatch):
    from backend.features import admin

    async def enabled(_name):
        return True

    async def should_not_search(*_args, **_kwargs):
        raise AssertionError("search should not run without its dependency")

    monkeypatch.setattr(admin, "feature_enabled", enabled)
    monkeypatch.setattr(websearch, "available", lambda: False)
    monkeypatch.setattr(websearch, "search", should_not_search)

    result = await run_tool("web_search", {"query": "latest news"}, allowed={"web_search"})

    assert result["ok"] is False
    assert "unavailable" in result["error"].lower()


@pytest.mark.anyio
async def test_web_search_tool_surfaces_provider_failure(monkeypatch):
    from backend.features import admin

    async def enabled(_name):
        return True

    async def failed_search(*_args, **_kwargs):
        return {
            "status": "error",
            "results": [],
            "error": "The web-search provider did not respond. Try again later.",
        }

    monkeypatch.setattr(admin, "feature_enabled", enabled)
    monkeypatch.setattr(websearch, "available", lambda: True)
    monkeypatch.setattr(websearch, "search_detailed", failed_search, raising=False)

    result = await run_tool("web_search", {"query": "latest news"}, allowed={"web_search"})

    assert result["ok"] is False
    assert "did not respond" in result["error"].lower()


@pytest.mark.anyio
async def test_chat_tool_trace_distinguishes_web_failure_from_zero_results(monkeypatch):
    async def fake_stream_chat(_model, work, *_args, **_kwargs):
        if len(work) == 1:
            yield "```orrery-search\ncurrent events\n```"
        else:
            yield "I could not retrieve current results."

    async def failed_tool(*_args, **_kwargs):
        return {
            "ok": False,
            "error": "The web-search provider did not respond. Try again later.",
        }

    async def fake_persist(_text, _artifacts):
        return "message-1"

    monkeypatch.setattr(code_interpreter.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(code_interpreter.tool_registry, "run_tool", failed_tool)

    events = [
        event
        async for event in code_interpreter.run(
            "openai/test",
            "system",
            [{"role": "user", "content": "What happened today?"}],
            None,
            trace=ReasoningTrace(),
            persist=fake_persist,
            allowed_tools={"web_search"},
        )
    ]

    failure = next(
        event["reasoning_step"]
        for event in events
        if event.get("reasoning_step", {}).get("stage") == "Web search failed"
    )
    assert failure["status"] == "warning"
    assert "did not respond" in failure["detail"]


def test_web_search_turn_gate_requires_workspace_and_turn_permission():
    gate = chat.router._web_search_for_turn

    assert gate({"web_search": True}, True) is True
    assert gate({"web_search": True}, False) is False
    assert gate({"web_search": False}, True) is False
    assert gate({"web_search": True}, None) is False


def test_http_message_schema_requires_web_opt_in_by_default():
    from backend.api.schemas import NewMessage

    assert NewMessage(content="hello").web_search is False
    assert NewMessage(content="hello", web_search=True).web_search is True


@pytest.mark.anyio
async def test_research_reports_web_failure_once_and_continues(monkeypatch):
    searched = []

    async def fake_plan(*_args, **_kwargs):
        return ["first question", "second question"]

    async def failed_search(query, **_kwargs):
        searched.append(query)
        return {
            "status": "error",
            "results": [],
            "error": "The web-search provider did not respond. Try again later.",
        }

    async def fake_stream_chat(*_args, **_kwargs):
        yield "Report from general knowledge."

    async def fake_persist(_text, _artifacts):
        return "message-1"

    monkeypatch.setattr(research, "_plan", fake_plan)
    monkeypatch.setattr(research.websearch, "search_detailed", failed_search)
    monkeypatch.setattr(research.ai, "stream_chat", fake_stream_chat)

    events = [
        event
        async for event in research.run(
            "openai/test",
            "question",
            collection_id=None,
            effort=None,
            trusted_context=None,
            trace=ReasoningTrace(),
            persist=fake_persist,
            web_search=True,
        )
    ]

    failure_steps = [
        event["reasoning_step"]
        for event in events
        if event.get("reasoning_step", {}).get("stage") == "Web search unavailable"
    ]
    assert searched == ["first question"]
    assert len(failure_steps) == 1
    assert failure_steps[0]["status"] == "warning"
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_chat_web_search_works_without_code_sandbox(monkeypatch):
    captured = {}

    async def fake_tool_loop(*args, **kwargs):
        captured["prompt"] = args[1]
        captured["allowed_tools"] = kwargs["allowed_tools"]
        yield {"done": True}

    async def direct_generation_should_not_run(*_args, **_kwargs):
        raise AssertionError("web-enabled chat should use the bounded tool loop")
        yield

    async def fake_record_outcome(*_args, **_kwargs):
        return None

    monkeypatch.setattr(chat.router.sandbox, "image_ready", lambda: False)
    monkeypatch.setattr(chat.router.code_interpreter, "run", fake_tool_loop)
    monkeypatch.setattr(chat.router.generation, "_generate", direct_generation_should_not_run)
    monkeypatch.setattr(chat.router.route_telemetry, "record_outcome", fake_record_outcome)

    events = [
        event
        async for event in chat.router._route_model_reply(
            SimpleNamespace(),
            "openai/test",
            None,
            [{"role": "user", "content": "What happened today?"}],
            None,
            32_768,
            None,
            None,
            TaskPlan("chat", "Chat", "Answer", 1.0),
            ReasoningTrace(),
            None,
            allow_code=True,
            allow_web=True,
            allow_mcp=False,
            flags={},
        )
    ]

    assert captured["allowed_tools"] == {"web_search"}
    assert "```orrery-search" in captured["prompt"]
    assert "```orrery-run" not in captured["prompt"]
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_chat_code_prompt_does_not_advertise_disabled_web_search(monkeypatch):
    captured = {}

    async def fake_tool_loop(*args, **kwargs):
        captured["prompt"] = args[1]
        captured["allowed_tools"] = kwargs["allowed_tools"]
        yield {"done": True}

    async def fake_record_outcome(*_args, **_kwargs):
        return None

    monkeypatch.setattr(chat.router.sandbox, "image_ready", lambda: True)
    monkeypatch.setattr(chat.router.code_interpreter, "run", fake_tool_loop)
    monkeypatch.setattr(chat.router.route_telemetry, "record_outcome", fake_record_outcome)

    events = [
        event
        async for event in chat.router._route_model_reply(
            SimpleNamespace(),
            "openai/test",
            None,
            [{"role": "user", "content": "Calculate 2 + 2"}],
            None,
            32_768,
            None,
            None,
            TaskPlan("chat", "Chat", "Answer", 1.0),
            ReasoningTrace(),
            None,
            allow_code=True,
            allow_web=False,
            allow_mcp=False,
            flags={},
        )
    ]

    assert captured["allowed_tools"] == {"run_python", "run_shell"}
    assert "```orrery-run" in captured["prompt"]
    assert "```orrery-search" not in captured["prompt"]
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_research_route_receives_effective_web_gate(monkeypatch):
    seen = {}

    async def fake_prepare_turn(*_args, **_kwargs):
        return SimpleNamespace(
            model="openai/test",
            system_prompt=None,
            effort=None,
            project_id=None,
            context_window=32_768,
            messages=[{"role": "user", "content": "/research current events"}],
            title="Research",
        )

    async def fake_flags():
        return {"deep_research": True, "web_search": False}

    async def fake_route_research(*_args, **kwargs):
        seen["web_search_enabled"] = kwargs["web_search_enabled"]
        yield {"done": True}

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.router.admin, "effective_flags", fake_flags)
    monkeypatch.setattr(chat.router, "_route_research", fake_route_research)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "/research current events",
        )
    ]

    assert seen["web_search_enabled"] is False
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_research_route_passes_web_gate_to_workflow(monkeypatch):
    seen = {}

    async def no_collection(_project_id):
        return None

    async def no_trusted_context(_project_id):
        return None

    async def fake_research_run(*_args, **kwargs):
        seen["web_search"] = kwargs["web_search"]
        yield {"done": True}

    monkeypatch.setattr(chat.project_store, "collection_id_for", no_collection)
    monkeypatch.setattr(chat.project_store, "trusted_context", no_trusted_context)
    monkeypatch.setattr(chat.router.research, "run", fake_research_run)

    events = [
        event
        async for event in chat.router._route_research(
            SimpleNamespace(),
            "openai/test",
            "current events",
            None,
            None,
            None,
            ReasoningTrace(),
            web_search_enabled=False,
        )
    ]

    assert seen["web_search"] is False
    assert events[-1] == {"done": True}
