"""MCP (Model Context Protocol) servers the user connects as tool/context sources.

Covers configuration + storage (add, list, edit, enable/disable, remove) AND the live connection: a
minimal stdio JSON-RPC client lists a server's tools (cached on "Test connection") and calls them from
the chat tool loop. Per security.md, every server is opt-in (enabled), the launch command is
admin-owned, and tool output is treated as untrusted context when fed back to the model.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid

from sqlalchemy import select

from backend.core import proc
from backend.core.database import get_sessionmaker
from backend.core.models import McpServer

_ALLOWED_TRANSPORTS = {"stdio", "http"}
_MCP_TIMEOUT = 45  # seconds for a whole stdio session (first npx run can be slow)


# --- minimal MCP stdio client (JSON-RPC over a plain subprocess) ---------------------------------
# We avoid the official `mcp` asyncio client because its stdio transport needs subprocess support
# that Windows only offers on the Proactor loop, while the app runs on the Selector loop (psycopg).
# A blocking subprocess + newline-delimited JSON-RPC, run off the event loop via to_thread, sidesteps
# that entirely. The configured command is admin-owned and runs only when a server is enabled.

def _stdio_session(command: str, ops: list[dict]) -> list:
    """Initialize an MCP stdio server, run each op (method/params), return their results."""
    p = proc.popen(
        command, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", bufsize=1,
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


async def _run_stdio(command: str, ops: list[dict]) -> list:
    return await asyncio.wait_for(asyncio.to_thread(_stdio_session, command, ops), timeout=_MCP_TIMEOUT)


async def list_tools(server: dict) -> list[dict]:
    """Connect to a server and return its tools [{name, description, input_schema}]. [] on failure."""
    if server.get("transport") != "stdio" or not server.get("command"):
        return []  # http/sse transport not supported by this minimal client yet
    try:
        (res,) = await _run_stdio(server["command"], [{"method": "tools/list"}])
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
        (res,) = await _run_stdio(server["command"], [{"method": "tools/call", "params": {"name": tool, "arguments": args or {}}}])
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
    }


async def list_servers() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(McpServer).order_by(McpServer.created_at))).scalars().all()
        return [_dict(r) for r in rows]


async def create_server(name: str, transport: str, command: str = "", url: str = "", enabled: bool = False) -> dict:
    transport = transport if transport in _ALLOWED_TRANSPORTS else "stdio"
    async with get_sessionmaker()() as s:
        row = McpServer(
            name=(name.strip() or "MCP server")[:120], transport=transport,
            command=(command.strip() or None), url=(url.strip() or None), enabled=bool(enabled),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
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
        return True


async def delete_server(server_id: str) -> bool:
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, uuid.UUID(server_id))
        if row is None:
            return False
        await s.delete(row)
        await s.commit()
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
    """Enabled servers (with their cached tools) — what chat advertises to the model."""
    return [s for s in await list_servers() if s["enabled"] and s.get("tools")]


async def call_tool_by_id(server_id: str, tool: str, args: dict) -> dict:
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, uuid.UUID(server_id))
        if row is None:
            return {"ok": False, "error": "Server not found"}
        server = _dict(row)
    return await call_tool(server, tool, args)
