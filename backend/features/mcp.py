"""MCP (Model Context Protocol) servers the user connects as tool/context sources.

Covers configuration + storage (add, list, edit, enable/disable, remove) AND the live connection: a
minimal stdio JSON-RPC client lists a server's tools (cached on "Test connection") and calls them from
the chat tool loop. Per security.md, every server is opt-in (enabled), the launch command is
admin-owned, and tool output is treated as untrusted context when fed back to the model.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid

from sqlalchemy import select

from backend.core import proc
from backend.core.database import get_sessionmaker
from backend.core.models import McpServer
from backend.features import team
from backend.security import secrets

_ALLOWED_TRANSPORTS = {"stdio", "http"}
_MCP_TIMEOUT = 45  # seconds for a whole stdio session (first npx run can be slow)


# --- per-server environment variables (many servers need an API key/token) -----------------------
# Values are secrets: they live ONLY in the OS keychain (security.md §1), keyed per server, and are
# injected into the server process at launch. The UI ever only sees the variable NAMES.

def _env_secret(sid: str) -> str:
    return f"mcp_env:{sid}"


def _load_env(sid: str) -> dict[str, str]:
    raw = secrets.get_secret(_env_secret(sid))
    if not raw:
        return {}
    try:
        env = json.loads(raw)
        return {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}
    except (ValueError, TypeError):
        return {}


def set_env(sid: str, env: dict[str, str]) -> None:
    """Replace a server's env vars. Empty dict clears them."""
    clean = {str(k).strip(): str(v) for k, v in (env or {}).items() if str(k).strip()}
    if clean:
        secrets.set_secret(_env_secret(sid), json.dumps(clean))
    else:
        secrets.delete_secret(_env_secret(sid))


# --- minimal MCP stdio client (JSON-RPC over a plain subprocess) ---------------------------------
# We avoid the official `mcp` asyncio client because its stdio transport needs subprocess support
# that Windows only offers on the Proactor loop, while the app runs on the Selector loop (psycopg).
# A blocking subprocess + newline-delimited JSON-RPC, run off the event loop via to_thread, sidesteps
# that entirely. The configured command is admin-owned and runs only when a server is enabled.

def _stdio_session(command: str, ops: list[dict], env: dict[str, str] | None = None) -> list:
    """Initialize an MCP stdio server, run each op (method/params), return their results."""
    p = proc.popen(
        command, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", bufsize=1,
        env={**os.environ, **env} if env else None,
    )
    try:
        def send(obj: dict) -> None:
            p.stdin.write(json.dumps(obj) + "\n")
            p.stdin.flush()

        def read_id(target: int) -> dict:
            while True:
                line = p.stdout.readline()
                if not line:
                    raise RuntimeError("MCP server closed the connection before responding.")
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue  # skip non-JSON log noise
                if msg.get("id") == target:
                    return msg

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "orrery", "version": "1.0"}}})
        read_id(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        results = []
        for i, op in enumerate(ops, start=2):
            send({"jsonrpc": "2.0", "id": i, "method": op["method"], "params": op.get("params", {})})
            resp = read_id(i)
            if "error" in resp:
                raise RuntimeError(str(resp["error"].get("message", "MCP error"))[:300])
            results.append(resp.get("result"))
        return results
    finally:
        for closer in (lambda: p.stdin.close(), p.terminate):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass


async def _run_stdio(command: str, ops: list[dict], env: dict[str, str] | None = None) -> list:
    return await asyncio.wait_for(asyncio.to_thread(_stdio_session, command, ops, env), timeout=_MCP_TIMEOUT)


def _server_env(server: dict) -> dict[str, str]:
    sid = server.get("id") or ""
    return _load_env(sid) if sid else {}


async def list_tools(server: dict) -> list[dict]:
    """Connect to a server and return its tools [{name, description, input_schema}]. [] on failure."""
    if server.get("transport") != "stdio" or not server.get("command"):
        return []  # http/sse transport not supported by this minimal client yet
    try:
        (res,) = await _run_stdio(server["command"], [{"method": "tools/list"}], _server_env(server))
        tools = res.get("tools", []) if isinstance(res, dict) else []
        return [{"name": t.get("name"), "description": t.get("description", ""),
                 "input_schema": t.get("inputSchema", {})} for t in tools if t.get("name")]
    except Exception:  # noqa: BLE001
        return []


async def call_tool(server: dict, tool: str, args: dict) -> dict:
    """Call a tool on a server; returns {ok, text|error}. Output is untrusted context."""
    if server.get("transport") != "stdio" or not server.get("command"):
        return {"ok": False, "error": "Only stdio MCP servers are supported right now."}
    try:
        (res,) = await _run_stdio(server["command"], [{"method": "tools/call", "params": {"name": tool, "arguments": args or {}}}],
                                  _server_env(server))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}
    parts: list[str] = []
    for block in (res.get("content") or []) if isinstance(res, dict) else []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return {"ok": not (isinstance(res, dict) and res.get("isError")), "text": "\n".join(parts) or json.dumps(res)[:2000]}


def _dict(s: McpServer) -> dict:
    try:
        tools = json.loads(s.tools) if s.tools else []
    except (ValueError, TypeError):
        tools = []
    return {
        "id": str(s.id), "name": s.name, "transport": s.transport,
        "command": s.command or "", "url": s.url or "", "enabled": bool(s.enabled), "tools": tools,
        "status": getattr(s, "status", "approved") or "approved", "owner_id": getattr(s, "owner_id", None),
        "env_names": sorted(_load_env(str(s.id)).keys()),  # names only — values never leave the keychain
    }


async def _all_servers() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(McpServer).order_by(McpServer.created_at))).scalars().all()
        return [_dict(r) for r in rows]


async def list_servers() -> list[dict]:
    """For the UI: approved servers (everyone) + pending ones owned by the current user or visible to admins."""
    owner = await team.current_owner_id()
    is_admin = await team.is_admin()
    out = []
    for d in await _all_servers():
        mine = owner is None or d["owner_id"] == owner
        if d["status"] == "approved" or mine or is_admin:
            d["mine"] = mine
            out.append(d)
    return out


async def create_server(name: str, transport: str, command: str = "", url: str = "", enabled: bool = False,
                        env: dict[str, str] | None = None) -> dict:
    transport = transport if transport in _ALLOWED_TRANSPORTS else "stdio"
    async with get_sessionmaker()() as s:
        row = McpServer(
            name=(name.strip() or "MCP server")[:120], transport=transport,
            command=(command.strip() or None), url=(url.strip() or None), enabled=bool(enabled),
            owner_id=await team.current_owner_id(), status=await team.creation_status(),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        if env:
            set_env(str(row.id), env)
        return _dict(row)


async def update_server(server_id: str, **fields) -> bool:
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, uuid.UUID(server_id))
        if row is None:
            return False
        if fields.get("name") is not None:
            row.name = (fields["name"].strip() or row.name)[:120]
        if fields.get("transport") is not None and fields["transport"] in _ALLOWED_TRANSPORTS:
            row.transport = fields["transport"]
        if fields.get("command") is not None:
            row.command = fields["command"].strip() or None
        if fields.get("url") is not None:
            row.url = fields["url"].strip() or None
        if fields.get("enabled") is not None:
            row.enabled = bool(fields["enabled"])
        await s.commit()
    if fields.get("env") is not None:
        set_env(server_id, fields["env"] or {})
    return True


async def delete_server(server_id: str) -> bool:
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, uuid.UUID(server_id))
        if row is None:
            return False
        await s.delete(row)
        await s.commit()
    secrets.delete_secret(_env_secret(server_id))  # remove the server's env secrets with it
    return True


async def refresh_tools(server_id: str) -> dict:
    """Connect to a server, list its tools, cache them, and return {ok, tools|error}."""
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, uuid.UUID(server_id))
        if row is None:
            return {"ok": False, "error": "Server not found"}
        server = _dict(row)
    tools = await list_tools(server)
    if not tools:
        return {"ok": False, "error": "No tools returned — check the command/URL and that the server runs."}
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, uuid.UUID(server_id))
        if row is not None:
            row.tools = json.dumps(tools)
            await s.commit()
    return {"ok": True, "tools": tools}


async def enabled_servers() -> list[dict]:
    """Approved + enabled servers (with cached tools) — what chat advertises to the model, team-wide."""
    return [s for s in await _all_servers() if s["enabled"] and s.get("tools") and s.get("status", "approved") == "approved"]


async def set_status(server_id: str, status: str) -> bool:
    """Approve (or send back to pending) an MCP server. Caller authorizes (admin)."""
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, uuid.UUID(server_id))
        if row is None:
            return False
        row.status = "approved" if status == "approved" else "pending"
        await s.commit()
        return True


async def call_tool_by_id(server_id: str, tool: str, args: dict) -> dict:
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, uuid.UUID(server_id))
        if row is None:
            return {"ok": False, "error": "Server not found"}
        server = _dict(row)
    return await call_tool(server, tool, args)
