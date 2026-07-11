"""The shared tool registry: registration, discovery, scope enforcement, validation, error shape."""
import pytest
from pydantic import BaseModel

from backend import tools
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
