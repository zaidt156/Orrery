from __future__ import annotations

import json
import threading
import uuid

import pytest

from backend.features import mcp
from backend.core.models import McpServer


class _InputPipe:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, value: str) -> None:
        self.writes.append(value)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _OutputPipe:
    def __init__(self) -> None:
        self.lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}) + "\n",
        ]

    def readline(self) -> str:
        return self.lines.pop(0) if self.lines else ""


class _Process:
    def __init__(self) -> None:
        self.stdin = _InputPipe()
        self.stdout = _OutputPipe()
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True


class _Session:
    def __init__(self, rows: dict[str, McpServer]) -> None:
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _model, key):
        return self.rows.get(str(key))

    def add(self, row: McpServer) -> None:
        if row.id is None:
            row.id = uuid.uuid4()
        self.rows[str(row.id)] = row

    async def commit(self) -> None:
        pass

    async def refresh(self, _row) -> None:
        pass

    async def delete(self, row: McpServer) -> None:
        self.rows.pop(str(row.id), None)


def _server(*, owner_id: str = "owner-a", status: str = "approved", enabled: bool = True) -> McpServer:
    return McpServer(
        id=uuid.uuid4(),
        name="Filesystem",
        transport="stdio",
        command="python -m example.server",
        enabled=enabled,
        tools=json.dumps([{"name": "read"}]),
        owner_id=owner_id,
        status=status,
    )


def _install_store(monkeypatch, *servers: McpServer) -> dict[str, McpServer]:
    rows = {str(server.id): server for server in servers}
    monkeypatch.setattr(mcp, "get_sessionmaker", lambda: lambda: _Session(rows))
    return rows


def _set_team_actor(monkeypatch, *, user_id: str | None, role: str = "member") -> None:
    actor = None if user_id is None else {"id": user_id, "name": user_id, "role": role, "team_mode": True}

    async def team_mode() -> bool:
        return True

    async def current_user():
        return actor

    async def is_admin() -> bool:
        return bool(actor and actor["role"] == "admin")

    monkeypatch.setattr(mcp.team, "team_mode", team_mode)
    monkeypatch.setattr(mcp.team, "current_user", current_user)
    monkeypatch.setattr(mcp.team, "is_admin", is_admin)


def test_stdio_launch_uses_argv_without_inheriting_application_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "safe-path")
    monkeypatch.setenv("ORRERY_SESSION_TOKEN", "desktop-session-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example.invalid/db")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    observed = {}

    def fake_popen(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return _Process()

    monkeypatch.setattr(mcp.proc, "popen", fake_popen)
    monkeypatch.setattr(mcp.proc, "find_executable", lambda name: name)

    result = mcp._stdio_session(
        'python -m example.server --label "two words"',
        [{"method": "tools/list"}],
        {"MCP_API_KEY": "server-scoped-secret", "ORRERY_SESSION_TOKEN": "must-not-pass"},
    )

    assert result == [{"tools": []}]
    assert observed["argv"] == ["python", "-m", "example.server", "--label", "two words"]
    assert observed["kwargs"]["shell"] is False
    child_env = {key.upper(): value for key, value in observed["kwargs"]["env"].items()}
    assert child_env["PATH"] == "safe-path"
    assert child_env["MCP_API_KEY"] == "server-scoped-secret"
    assert "ORRERY_SESSION_TOKEN" not in child_env
    assert "DATABASE_URL" not in child_env
    assert "OPENAI_API_KEY" not in child_env


def test_bare_windows_style_launcher_is_resolved_before_spawn(monkeypatch):
    monkeypatch.setattr(mcp.proc, "find_executable", lambda name: r"C:\Program Files\nodejs\npx.cmd")

    argv = mcp._command_argv("npx -y @modelcontextprotocol/server-filesystem")

    assert argv[0] == r"C:\Program Files\nodejs\npx.cmd"
    assert argv[1:] == ["-y", "@modelcontextprotocol/server-filesystem"]


def test_posix_child_environment_does_not_inherit_mixed_case_lookalikes(monkeypatch):
    monkeypatch.setattr(mcp.os, "name", "posix")
    monkeypatch.setattr(mcp.os, "environ", {"PATH": "/safe/bin", "Path": "/leaked/bin", "Home": "/leaked"})

    child_env = mcp._child_env(None)

    assert child_env == {"PATH": "/safe/bin"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "enabled"),
    [("pending", True), ("approved", False)],
)
async def test_direct_mcp_operations_refuse_pending_or_disabled_servers(monkeypatch, status, enabled):
    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("an unavailable MCP server must not launch")

    monkeypatch.setattr(mcp, "_run_stdio", must_not_run)
    server = {
        "id": "server-id",
        "transport": "stdio",
        "command": "python -m example.server",
        "status": status,
        "enabled": enabled,
    }

    assert await mcp.list_tools(server) == []
    result = await mcp.call_tool(server, "read", {})
    assert result["ok"] is False
    assert "approval" in result["error"].lower() or "disabled" in result["error"].lower()


@pytest.mark.anyio
async def test_missing_status_fails_closed_without_launching(monkeypatch):
    launched = False

    async def must_not_run(*_args, **_kwargs):
        nonlocal launched
        launched = True
        return [{"tools": []}]

    monkeypatch.setattr(mcp, "_run_stdio", must_not_run)
    server = {
        "id": "server-id",
        "transport": "stdio",
        "command": "python -m example.server",
        "enabled": True,
    }

    assert await mcp.list_tools(server) == []
    assert (await mcp.call_tool(server, "read", {}))["ok"] is False
    assert launched is False


@pytest.mark.anyio
async def test_stdio_timeout_terminates_the_spawned_process_tree(monkeypatch):
    stopped = threading.Event()

    def blocked_session(_command, _ops, _env, on_start):
        process = object()
        on_start(process)
        stopped.wait(0.5)
        return []

    def terminate(process, *, force=False):
        assert process is not None
        assert force is True
        stopped.set()

    monkeypatch.setattr(mcp, "_stdio_session", blocked_session)
    monkeypatch.setattr(mcp, "_terminate_process_tree", terminate, raising=False)
    monkeypatch.setattr(mcp, "_MCP_TIMEOUT", 0.01)

    with pytest.raises(TimeoutError):
        await mcp._run_stdio("python -m example.server", [])

    assert stopped.is_set()


@pytest.mark.anyio
async def test_malformed_server_ids_return_not_found(monkeypatch):
    _install_store(monkeypatch)

    assert await mcp.update_server("not-a-uuid", name="Nope") is False
    assert await mcp.delete_server("not-a-uuid") is False
    assert (await mcp.refresh_tools("not-a-uuid"))["ok"] is False
    assert await mcp.set_status("not-a-uuid", "approved") is False
    assert (await mcp.call_tool_by_id("not-a-uuid", "read", {}))["ok"] is False


@pytest.mark.anyio
async def test_team_member_cannot_update_another_owners_server(monkeypatch):
    server = _server(owner_id="owner-a")
    _install_store(monkeypatch, server)
    _set_team_actor(monkeypatch, user_id="owner-b")

    with pytest.raises(PermissionError, match="owner|admin"):
        await mcp.update_server(str(server.id), name="Hijacked")

    assert server.name == "Filesystem"


@pytest.mark.anyio
async def test_team_member_cannot_delete_another_owners_server(monkeypatch):
    server = _server(owner_id="owner-a")
    rows = _install_store(monkeypatch, server)
    _set_team_actor(monkeypatch, user_id="owner-b")

    with pytest.raises(PermissionError, match="owner|admin"):
        await mcp.delete_server(str(server.id))

    assert str(server.id) in rows


@pytest.mark.anyio
async def test_team_member_cannot_test_another_owners_server(monkeypatch):
    server = _server(owner_id="owner-a")
    _install_store(monkeypatch, server)
    _set_team_actor(monkeypatch, user_id="owner-b")

    async def must_not_list(_server):
        raise AssertionError("an unauthorized test must not launch the server")

    monkeypatch.setattr(mcp, "list_tools", must_not_list)

    with pytest.raises(PermissionError, match="owner|admin"):
        await mcp.refresh_tools(str(server.id))


@pytest.mark.anyio
async def test_team_member_cannot_approve_mcp_server(monkeypatch):
    server = _server(owner_id="owner-a", status="pending", enabled=False)
    _install_store(monkeypatch, server)
    _set_team_actor(monkeypatch, user_id="owner-a")

    with pytest.raises(PermissionError, match="admin"):
        await mcp.set_status(str(server.id), "approved")

    assert server.status == "pending"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fields",
    [
        {"command": "python -m replacement.server"},
        {"env": {"MCP_API_KEY": "replacement-secret"}},
    ],
)
async def test_sensitive_owner_update_returns_approved_server_to_pending(monkeypatch, fields):
    server = _server(owner_id="owner-a", status="approved", enabled=True)
    _install_store(monkeypatch, server)
    _set_team_actor(monkeypatch, user_id="owner-a")

    assert await mcp.update_server(str(server.id), **fields) is True

    assert server.status == "pending"
    assert server.enabled is False
    assert server.tools is None


@pytest.mark.anyio
async def test_team_member_created_server_is_owned_pending_and_disabled(monkeypatch):
    rows = _install_store(monkeypatch)
    _set_team_actor(monkeypatch, user_id="owner-a")

    created = await mcp.create_server(
        "Member server",
        "stdio",
        "python -m example.server",
        enabled=True,
    )

    assert created["owner_id"] == "owner-a"
    assert created["status"] == "pending"
    assert created["enabled"] is False
    assert str(created["id"]) in rows


@pytest.mark.anyio
async def test_locked_team_client_cannot_create_mcp_server(monkeypatch):
    _install_store(monkeypatch)
    _set_team_actor(monkeypatch, user_id=None)

    with pytest.raises(PermissionError, match="access key"):
        await mcp.create_server("Blocked", "stdio", "python -m example.server")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "enabled"),
    [("pending", True), ("approved", False)],
)
async def test_stored_pending_or_disabled_server_never_executes(monkeypatch, status, enabled):
    server = _server(owner_id="owner-a", status=status, enabled=enabled)
    _install_store(monkeypatch, server)
    _set_team_actor(monkeypatch, user_id="owner-a")

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("an unavailable MCP server must not launch")

    monkeypatch.setattr(mcp, "_run_stdio", must_not_run)

    refreshed = await mcp.refresh_tools(str(server.id))
    called = await mcp.call_tool_by_id(str(server.id), "read", {})

    assert refreshed["ok"] is False
    assert called["ok"] is False


@pytest.mark.anyio
async def test_owner_can_test_and_delete_an_approved_enabled_server(monkeypatch):
    server = _server(owner_id="owner-a", status="approved", enabled=True)
    rows = _install_store(monkeypatch, server)
    _set_team_actor(monkeypatch, user_id="owner-a")

    async def list_one_tool(_server):
        return [{"name": "read", "description": "Read a file", "input_schema": {}}]

    monkeypatch.setattr(mcp, "list_tools", list_one_tool)

    result = await mcp.refresh_tools(str(server.id))
    assert result["ok"] is True
    assert result["tools"][0]["name"] == "read"
    assert await mcp.delete_server(str(server.id)) is True
    assert str(server.id) not in rows


@pytest.mark.anyio
async def test_admin_can_manage_and_approve_another_owners_server(monkeypatch):
    server = _server(owner_id="owner-a", status="pending", enabled=False)
    rows = _install_store(monkeypatch, server)
    _set_team_actor(monkeypatch, user_id="admin-a", role="admin")

    assert await mcp.update_server(str(server.id), name="Reviewed") is True
    assert await mcp.set_status(str(server.id), "approved") is True
    assert server.name == "Reviewed"
    assert server.status == "approved"
    assert await mcp.delete_server(str(server.id)) is True
    assert str(server.id) not in rows
