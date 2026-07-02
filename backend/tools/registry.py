"""The shared tool registry — the one place capabilities are registered and executed.

Chat, Automations, and Agents invoke tools ONLY through this registry, so scope allow-lists,
argument validation, and error sanitization are enforced once at the tool layer (security.md §4)
instead of drifting per feature. Adding a capability = one class + @register_tool; the UI/engine
discovers it from list_tools() — never a type-string switch (conventions.md).

Keys are stable once shipped: they get persisted in saved workflows and agent scopes.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ValidationError

log = logging.getLogger("orrery.tools")


class Tool:
    """Base class for a registered capability. Subclass, set the class attributes, implement execute."""

    key: str = ""                 # set by @register_tool — stable forever
    label: str = ""               # human name for palettes/config panels
    category: str = "tools"       # ai | data | code | net | tools
    writes: bool = False          # affects the world outside Orrery → approval-gated in agent flows
    config_model: type[BaseModel] | None = None

    async def execute(self, config: BaseModel) -> dict:
        raise NotImplementedError


_TOOLS: dict[str, Tool] = {}


def register_tool(key: str):
    """Class decorator: instantiate + register under a stable key. Duplicate keys are a bug."""
    def deco(cls: type[Tool]) -> type[Tool]:
        if key in _TOOLS:
            raise ValueError(f"Tool key already registered: {key}")
        cls.key = key
        _TOOLS[key] = cls()
        return cls
    return deco


def get_tool(key: str) -> Tool | None:
    return _TOOLS.get(key)


def list_tools() -> list[dict]:
    """Discoverable catalog: key, label, category, writes flag, and the JSON schema of the config."""
    out = []
    for key, tool in sorted(_TOOLS.items()):
        schema: dict[str, Any] = {}
        if tool.config_model is not None:
            schema = tool.config_model.model_json_schema()
        out.append({"key": key, "label": tool.label or key, "category": tool.category,
                    "writes": bool(tool.writes), "schema": schema})
    return out


async def run_tool(key: str, args: dict | None = None, *, allowed: set[str] | None = None) -> dict:
    """Execute one tool call. Returns {"ok": bool, ...} — never raises to the caller.

    `allowed` is the caller's scope allow-list (an agent's granted tools, a workflow's node set).
    Enforcement lives HERE, in code, not in any prompt (security.md §4).
    """
    if allowed is not None and key not in allowed:
        return {"ok": False, "error": f"Tool '{key}' is not in this scope's allow-list."}
    tool = _TOOLS.get(key)
    if tool is None:
        return {"ok": False, "error": f"Unknown tool '{key}'."}
    try:
        config = tool.config_model.model_validate(args or {}) if tool.config_model else None
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
        return {"ok": False, "error": f"Invalid arguments for '{key}': {problems}"}
    try:
        result = await tool.execute(config)
    except Exception as exc:  # noqa: BLE001 — tool failures surface as data, sanitized
        from backend.security.secrets import redact_url
        log.warning("tool %s failed: %s", key, type(exc).__name__)
        return {"ok": False, "error": redact_url(str(exc))[:300]}
    out = {"ok": True}
    out.update(result or {})
    return out
