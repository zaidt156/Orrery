"""The shared tool registry: registration, discovery, scope enforcement, validation, error shape."""
import uuid

import pytest
from pydantic import BaseModel

from backend import tools
from backend.tools import lifecycle
from backend.tools.registry import Tool, register_tool, run_tool


class EchoConfig(BaseModel):
    text: str


@register_tool("_test_echo")
class EchoTool(Tool):
    label = "Echo (test)"
    category = "tools"
    config_model = EchoConfig

    async def execute(self, config: EchoConfig) -> dict:
        if config.text == "boom":
            raise RuntimeError("exploded with secret postgres://user:hunter2@db/x inside")
        return {"echo": config.text}


def test_builtin_tools_are_discoverable():
    catalog = {t["key"]: t for t in tools.list_tools()}
    for key in ("web_search", "doc_search", "db_query", "run_python", "dashboard_refresh", "mcp_call", "file_generate", "crabbox_run"):
        assert key in catalog, f"missing built-in tool {key}"
        assert catalog[key]["schema"].get("properties"), f"{key} exposes no config schema"
    assert catalog["mcp_call"]["writes"] is True  # external side effects → approval-gated
    assert catalog["db_query"]["writes"] is False
    assert catalog["crabbox_run"]["writes"] is True
    assert catalog["file_generate"]["writes"] is True
    assert catalog["db_query"]["risk"] == "sensitive_read"
    assert catalog["db_query"]["resource_fields"] == ["connection_id"]


@pytest.mark.anyio
async def test_scope_allowlist_is_enforced_in_code():
    out = await run_tool("_test_echo", {"text": "hi"}, allowed={"web_search"})
    assert out["ok"] is False and "allow-list" in out["error"]
    ok = await run_tool("_test_echo", {"text": "hi"}, allowed={"_test_echo"})
    assert ok == {"ok": True, "echo": "hi"}


@pytest.mark.anyio
async def test_resource_grant_is_enforced_below_agent_prompt():
    missing = await run_tool(
        "db_query",
        {"connection_id": "a" * 36, "sql": "SELECT 1"},
        allowed={"db_query"},
        grant={"actions": ["execute"], "resources": {}},
    )
    wrong = await run_tool(
        "db_query",
        {"connection_id": "a" * 36, "sql": "SELECT 1"},
        allowed={"db_query"},
        grant={"actions": ["execute"], "resources": {"connection_id": ["b" * 36]}},
    )

    assert missing["ok"] is False and "no grant" in missing["error"]
    assert wrong["ok"] is False and "cannot access" in wrong["error"]


@pytest.mark.anyio
async def test_unknown_tool_and_invalid_args_return_errors():
    assert (await run_tool("no_such_tool", {}))["ok"] is False
    bad = await run_tool("_test_echo", {})
    assert bad["ok"] is False and "text" in bad["error"]


@pytest.mark.anyio
async def test_tool_exceptions_are_sanitized():
    out = await run_tool("_test_echo", {"text": "boom"})
    assert out["ok"] is False
    assert "hunter2" not in out["error"], "secret leaked through a tool error"


@pytest.mark.anyio
async def test_db_query_rejects_non_select_before_touching_a_connection():
    out = await run_tool("db_query", {"connection_id": "0" * 36, "sql": "DELETE FROM users"})
    assert out["ok"] is False and "SELECT" in out["error"]


@pytest.mark.anyio
async def test_crabbox_run_refuses_when_feature_gate_is_disabled(monkeypatch):
    from backend.features import admin

    async def disabled(_name):
        return False

    monkeypatch.setattr(admin, "feature_enabled", disabled)
    out = await run_tool("crabbox_run", {"command": ["echo", "hi"]}, allowed={"crabbox_run"})
    assert out["ok"] is False
    assert "disabled" in out["error"].lower()


def test_duplicate_keys_are_a_bug():
    with pytest.raises(ValueError):
        @register_tool("_test_echo")
        class Duplicate(Tool):  # noqa: N801
            pass


class _RecordingLifecycle:
    def __init__(self, events, *, warning=None, fail_at=None):
        self.events = events
        self.warning = warning
        self.fail_at = fail_at

    async def admit(self):
        self.events.append("admitted")
        if self.fail_at == "admitted":
            raise RuntimeError("database unavailable")

    async def reject(self, outcome, presentation):
        self.events.append(("rejected", outcome.code, presentation.text))

    async def repeated_call_warning(self):
        self.events.append("repeat_checked")
        return self.warning

    async def body_started(self):
        self.events.append("body_started")

    async def complete(self, outcome, presentation):
        self.events.append(("completed", outcome.code, presentation.text))
        if self.fail_at == "completed":
            raise RuntimeError("database unavailable")

    async def cancelled(self):
        self.events.append("cancelled")


def _chat_execution():
    return lifecycle.ToolExecutionIdentity(
        surface="chat",
        owner_id=None,
        conversation_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
    )


@pytest.mark.anyio
async def test_evidenced_call_commits_admission_and_body_start_before_execute(monkeypatch):
    events = []

    def start(*_args, **_kwargs):
        return _RecordingLifecycle(events)

    original = EchoTool.execute

    async def observed_execute(self, config):
        events.append("tool_body")
        return await original(self, config)

    monkeypatch.setattr(lifecycle, "start", start)
    monkeypatch.setattr(EchoTool, "execute", observed_execute)

    out = await run_tool("_test_echo", {"text": "hi"}, execution=_chat_execution())

    assert out == {"ok": True, "echo": "hi"}
    assert events[:4] == ["admitted", "repeat_checked", "body_started", "tool_body"]
    assert events[4][0] == "completed"
    assert events[4][1] == "succeeded"


@pytest.mark.anyio
async def test_evidence_failure_before_body_fails_closed(monkeypatch):
    events = []
    monkeypatch.setattr(
        lifecycle,
        "start",
        lambda *_args, **_kwargs: _RecordingLifecycle(events, fail_at="admitted"),
    )

    out = await run_tool("_test_echo", {"text": "hi"}, execution=_chat_execution())

    assert out["ok"] is False
    assert out["code"] == "evidence_unavailable"
    assert out["retry_safe"] is True
    assert events == ["admitted"]


@pytest.mark.anyio
async def test_evidence_failure_after_body_returns_unknown_outcome(monkeypatch):
    events = []
    monkeypatch.setattr(
        lifecycle,
        "start",
        lambda *_args, **_kwargs: _RecordingLifecycle(events, fail_at="completed"),
    )

    out = await run_tool("_test_echo", {"text": "hi"}, execution=_chat_execution())

    assert out["ok"] is False
    assert out["code"] == "unknown_outcome"
    assert out["retry_safe"] is False
    assert "do not retry" in out["error"].lower()


@pytest.mark.anyio
async def test_repeat_warning_is_additive_and_model_visible(monkeypatch):
    events = []
    warning = "You have made this identical call 3 times; inspect the result before repeating it."
    monkeypatch.setattr(
        lifecycle,
        "start",
        lambda *_args, **_kwargs: _RecordingLifecycle(events, warning=warning),
    )

    out = await run_tool("_test_echo", {"text": "hi"}, execution=_chat_execution())

    assert out["ok"] is True
    assert out["loop_warning"] == warning


@pytest.mark.anyio
async def test_evidenced_rejections_have_stable_structured_outcomes(monkeypatch):
    events = []
    monkeypatch.setattr(lifecycle, "start", lambda *_a, **_k: _RecordingLifecycle(events))

    unknown = await run_tool("no_such_tool", {}, execution=_chat_execution())
    invalid = await run_tool("_test_echo", {}, execution=_chat_execution())

    assert (unknown["code"], unknown["retry_safe"]) == ("unknown_tool", True)
    assert (invalid["code"], invalid["retry_safe"]) == ("validation_failed", True)
    assert [event[1] for event in events if isinstance(event, tuple)] == [
        "unknown_tool",
        "validation_failed",
    ]


@pytest.mark.anyio
async def test_file_generate_tool_stores_app_as_one_bundle(monkeypatch):
    from backend.features import filegen, files, sandbox

    async def fake_run(*args, **kwargs):
        yield {
            "result": {
                "ok": True,
                "kind": "app",
                "bundle_name": "tiny.zip",
                "summary": "Built the app.",
                "files": [sandbox.SandboxFile("index.html", b"<html></html>")],
                "manifest": [],
                "sandbox_runs": [],
            }
        }

    def fake_store(result):
        assert result["kind"] == "app"
        return [{
            "kind": "file",
            "id": "b" * 32,
            "name": "tiny.zip",
            "mime": "application/zip",
            "artifact_type": "app_bundle",
        }]

    monkeypatch.setattr(filegen, "run", fake_run)
    monkeypatch.setattr(files, "store_filegen_output", fake_store)

    out = await run_tool(
        "file_generate",
        {"request": "Build me a small app", "model": "openai/gpt-test"},
        allowed={"file_generate"},
    )

    assert out["ok"] is True
    assert out["files"] == ["tiny.zip"]
    assert len(out["artifacts"]) == 1
    assert out["artifacts"][0]["artifact_type"] == "app_bundle"
