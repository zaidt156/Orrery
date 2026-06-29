"""MCP (Model Context Protocol) servers the user connects as tool/context sources.

This module covers configuration + storage: add, list, edit, enable/disable, and remove MCP servers
from the UI. Actually connecting to a server and exposing its tools to the chat tool loop is the next
increment (it needs a live server to verify). Per security.md, any connected server is opt-in
(enabled) and its output must be treated as untrusted when wired in.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import McpServer

_ALLOWED_TRANSPORTS = {"stdio", "http"}


def _dict(s: McpServer) -> dict:
    return {
        "id": str(s.id), "name": s.name, "transport": s.transport,
        "command": s.command or "", "url": s.url or "", "enabled": bool(s.enabled),
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
