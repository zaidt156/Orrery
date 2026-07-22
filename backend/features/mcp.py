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
import shlex
import signal
import subprocess
import threading
import uuid
from functools import wraps

from sqlalchemy import select

from backend.core import proc
from backend.core.database import get_sessionmaker
from backend.core.models import McpServer
from backend.features import team
from backend.security import secrets

_ALLOWED_TRANSPORTS = {"stdio", "http"}
_MCP_TIMEOUT = 45  # seconds for a whole stdio session (first npx run can be slow)
_INHERITED_ENV_NAMES = {
    "APPDATA", "COMSPEC", "HOME", "LANG", "LC_ALL", "LOCALAPPDATA", "PATH", "PATHEXT",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "SYSTEMDRIVE",
    "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "USERPROFILE", "WINDIR", "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME",
}


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


def _clean_env(env: dict[str, str] | None) -> dict[str, str]:
    clean: dict[str, str] = {}
    for raw_key, raw_value in (env or {}).items():
        key = str(raw_key).strip()
        value = str(raw_value)
        if not key or "=" in key or "\x00" in key or "\x00" in value or key.upper().startswith("ORRERY_"):
            continue
        clean[key] = value
    return clean


def _write_env(sid: str, env: dict[str, str]) -> None:
    """Replace a server's env vars. Empty dict clears them."""
    clean = _clean_env(env)
    if clean:
        secrets.set_secret(_env_secret(sid), json.dumps(clean))
    else:
        secrets.delete_secret(_env_secret(sid))


# --- minimal MCP stdio client (JSON-RPC over a plain subprocess) ---------------------------------
# We avoid the official `mcp` asyncio client because its stdio transport needs subprocess support
# that Windows only offers on the Proactor loop, while the app runs on the Selector loop (psycopg).
# A blocking subprocess + newline-delimited JSON-RPC, run off the event loop via to_thread, sidesteps
# that entirely. Commands are parsed to argv and launched without a shell; child processes receive
# only a small OS-runtime environment plus the secrets explicitly configured for that MCP server.

def _command_argv(command: str) -> list[str]:
    cleaned = (command or "").strip()
    if not cleaned or "\x00" in cleaned:
        raise ValueError("The MCP launch command is empty or invalid.")
    if os.name == "nt":
        # CommandLineToArgvW implements the quoting rules Windows users expect when they paste a
        # command into the UI. shlex(posix=True) corrupts unquoted backslashes in Windows paths.
        import ctypes

        argc = ctypes.c_int()
        parse = ctypes.windll.shell32.CommandLineToArgvW
        parse.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int))
        parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
        parsed = parse(cleaned, ctypes.byref(argc))
        if not parsed:
            raise ValueError("The MCP launch command could not be parsed.")
        try:
            argv = [parsed[index] for index in range(argc.value)]
        finally:
            free = ctypes.windll.kernel32.LocalFree
            free.argtypes = (ctypes.c_void_p,)
            free.restype = ctypes.c_void_p
            free(ctypes.cast(parsed, ctypes.c_void_p))
    else:
        argv = shlex.split(cleaned, posix=True)
    if not argv or any(not arg or "\x00" in arg for arg in argv):
        raise ValueError("The MCP launch command is empty or invalid.")
    resolved = proc.find_executable(argv[0])
    if resolved:
        argv[0] = resolved
    return argv


def _child_env(server_env: dict[str, str] | None) -> dict[str, str]:
    inherited = {
        key: value
        for key, value in os.environ.items()
        if (key.upper() in _INHERITED_ENV_NAMES if os.name == "nt" else key in _INHERITED_ENV_NAMES)
    }
    for key, value in _clean_env(server_env).items():
        inherited[key] = value
    return inherited


def _availability_error(server: dict) -> str | None:
    if server.get("status") != "approved":
        return "The MCP server is awaiting administrator approval."
    if not server.get("enabled"):
        return "The MCP server is disabled."
    return None

def _terminate_process_tree(process, *, force: bool = False) -> None:
    """Stop an MCP process, force-killing its process group/tree after a timed-out session."""
    if not force:
        try:
            process.terminate()
            process.wait(timeout=1)
            return
        except Exception:  # noqa: BLE001 - fall through to the process-tree kill
            pass
    try:
        if os.name == "nt":
            taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
            proc.run([taskkill, "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=5)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except Exception:  # noqa: BLE001 - direct kill is the final portable fallback
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass
    try:
        process.wait(timeout=2)
    except Exception:  # noqa: BLE001
        pass


def _stdio_session(
    command: str,
    ops: list[dict],
    env: dict[str, str] | None = None,
    on_start=None,
) -> list:
    """Initialize an MCP stdio server, run each op (method/params), return their results."""
    group_options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    p = proc.popen(
        _command_argv(command), shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", bufsize=1,
        env=_child_env(env),
        **group_options,
    )
    if on_start is not None:
        on_start(p)
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
        try:
            p.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        _terminate_process_tree(p)


async def _run_stdio(command: str, ops: list[dict], env: dict[str, str] | None = None) -> list:
    holder: dict[str, object] = {}
    timed_out = threading.Event()

    def on_start(process) -> None:
        holder["process"] = process
        if timed_out.is_set():
            _terminate_process_tree(process, force=True)

    task = asyncio.create_task(asyncio.to_thread(_stdio_session, command, ops, env, on_start))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=_MCP_TIMEOUT)
    except TimeoutError:
        timed_out.set()
        process = holder.get("process")
        if process is not None:
            await asyncio.to_thread(_terminate_process_tree, process, force=True)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2)
        except Exception:  # noqa: BLE001 - the timeout remains the public failure
            task.cancel()
        raise


def _server_env(server: dict) -> dict[str, str]:
    sid = server.get("id") or ""
    return _load_env(sid) if sid else {}


async def list_tools(server: dict) -> list[dict]:
    """Connect to a server and return its tools [{name, description, input_schema}]. [] on failure."""
    if _availability_error(server):
        return []
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
    unavailable = _availability_error(server)
    if unavailable:
        return {"ok": False, "error": unavailable}
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
        "status": getattr(s, "status", None) or "pending", "owner_id": getattr(s, "owner_id", None),
        "env_names": sorted(_load_env(str(s.id)).keys()),  # names only — values never leave the keychain
    }


async def _actor() -> tuple[dict, bool]:
    """Return (current actor, team mode), rejecting locked team clients at the feature boundary."""
    in_team = await team.team_mode()
    if not in_team:
        return team.SOLO_USER, False
    user = await team.current_user()
    if not user:
        raise PermissionError("Team access key required.")
    return user, True


def _require_server_access(
    row: McpServer,
    actor: dict,
    *,
    in_team: bool,
    admin_only: bool = False,
) -> None:
    if not in_team:
        return
    if actor.get("role") == "admin":
        return
    if admin_only:
        raise PermissionError("MCP server approval requires an administrator.")
    if not row.owner_id or str(row.owner_id) != str(actor.get("id") or ""):
        raise PermissionError("Only the MCP server owner or an administrator can manage it.")


async def _all_servers() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(McpServer).order_by(McpServer.created_at))).scalars().all()
        return [_dict(r) for r in rows]


def _server_uuid(server_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(server_id)
    except (ValueError, TypeError, AttributeError):
        return None


_SERVER_LOCKS: dict[str, asyncio.Lock] = {}


def _serialized_server_operation(func):
    """Serialize each server's config transitions and launches inside the local backend process."""
    @wraps(func)
    async def wrapped(server_id: str, *args, **kwargs):
        parsed_id = _server_uuid(server_id)
        if parsed_id is None:
            return await func(server_id, *args, **kwargs)
        lock = _SERVER_LOCKS.setdefault(str(parsed_id), asyncio.Lock())
        async with lock:
            return await func(server_id, *args, **kwargs)
    return wrapped


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
    actor, in_team = await _actor()
    transport = transport if transport in _ALLOWED_TRANSPORTS else "stdio"
    status = "approved" if not in_team or actor.get("role") == "admin" else "pending"
    async with get_sessionmaker()() as s:
        row = McpServer(
            name=(name.strip() or "MCP server")[:120], transport=transport,
            command=(command.strip() or None), url=(url.strip() or None),
            enabled=bool(enabled) if status == "approved" else False,
            owner_id=str(actor["id"]) if in_team else None, status=status,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        if env:
            _write_env(str(row.id), env)
        return _dict(row)


@_serialized_server_operation
async def update_server(server_id: str, **fields) -> bool:
    actor, in_team = await _actor()
    parsed_id = _server_uuid(server_id)
    if parsed_id is None:
        return False
    replacement_env = _clean_env(fields.get("env")) if fields.get("env") is not None else None
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, parsed_id)
        if row is None:
            return False
        _require_server_access(row, actor, in_team=in_team)
        connection_changed = False
        if fields.get("name") is not None:
            row.name = (fields["name"].strip() or row.name)[:120]
        if fields.get("transport") is not None and fields["transport"] in _ALLOWED_TRANSPORTS:
            if row.transport != fields["transport"]:
                row.transport = fields["transport"]
                connection_changed = True
        if fields.get("command") is not None:
            command = fields["command"].strip() or None
            if row.command != command:
                row.command = command
                connection_changed = True
        if fields.get("url") is not None:
            url = fields["url"].strip() or None
            if row.url != url:
                row.url = url
                connection_changed = True
        if replacement_env is not None and replacement_env != _load_env(server_id):
            connection_changed = True
        if fields.get("enabled") is not None:
            row.enabled = bool(fields["enabled"])
        if connection_changed:
            row.tools = None
            if in_team:
                row.status = "pending"
                row.enabled = False
        if row.status != "approved":
            row.enabled = False
        await s.commit()
    if replacement_env is not None:
        _write_env(server_id, replacement_env)
    return True


@_serialized_server_operation
async def delete_server(server_id: str) -> bool:
    actor, in_team = await _actor()
    parsed_id = _server_uuid(server_id)
    if parsed_id is None:
        return False
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, parsed_id)
        if row is None:
            return False
        _require_server_access(row, actor, in_team=in_team)
        await s.delete(row)
        await s.commit()
    secrets.delete_secret(_env_secret(server_id))  # remove the server's env secrets with it
    return True


@_serialized_server_operation
async def refresh_tools(server_id: str) -> dict:
    """Connect to a server, list its tools, cache them, and return {ok, tools|error}."""
    actor, in_team = await _actor()
    parsed_id = _server_uuid(server_id)
    if parsed_id is None:
        return {"ok": False, "error": "Server not found"}
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, parsed_id)
        if row is None:
            return {"ok": False, "error": "Server not found"}
        _require_server_access(row, actor, in_team=in_team)
        server = _dict(row)
    unavailable = _availability_error(server)
    if unavailable:
        return {"ok": False, "error": unavailable}
    tools = await list_tools(server)
    if not tools:
        return {"ok": False, "error": "No tools returned — check the command/URL and that the server runs."}
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, parsed_id)
        if row is not None:
            row.tools = json.dumps(tools)
            await s.commit()
    return {"ok": True, "tools": tools}


async def enabled_servers() -> list[dict]:
    """Approved + enabled servers (with cached tools) — what chat advertises to the model, team-wide."""
    return [s for s in await _all_servers() if s["enabled"] and s.get("tools") and s.get("status") == "approved"]


@_serialized_server_operation
async def set_status(server_id: str, status: str) -> bool:
    """Approve (or send back to pending) an MCP server. Team approval is admin-only."""
    actor, in_team = await _actor()
    parsed_id = _server_uuid(server_id)
    if parsed_id is None:
        return False
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, parsed_id)
        if row is None:
            return False
        _require_server_access(row, actor, in_team=in_team, admin_only=True)
        row.status = "approved" if status == "approved" else "pending"
        if row.status != "approved":
            row.enabled = False
            row.tools = None
        await s.commit()
        return True


@_serialized_server_operation
async def call_tool_by_id(server_id: str, tool: str, args: dict) -> dict:
    parsed_id = _server_uuid(server_id)
    if parsed_id is None:
        return {"ok": False, "error": "Server not found"}
    async with get_sessionmaker()() as s:
        row = await s.get(McpServer, parsed_id)
        if row is None:
            return {"ok": False, "error": "Server not found"}
        server = _dict(row)
    unavailable = _availability_error(server)
    if unavailable:
        return {"ok": False, "error": unavailable}
    return await call_tool(server, tool, args)
