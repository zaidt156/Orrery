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
    risk: str = "read"            # read | sensitive_read | local_write | external_write | destructive | credential_use | network
    feature_flag: str | None = None  # admin feature gate checked before approval/execution
    resource_fields: tuple[str, ...] = ()  # config fields an agent grant must constrain
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
        out.append({
            "key": key,
            "label": tool.label or key,
            "category": tool.category,
            "writes": bool(tool.writes),
            "risk": tool.risk,
            "resource_fields": list(tool.resource_fields),
            "schema": schema,
        })
    return out


async def run_tool(
    key: str,
    args: dict | None = None,
    *,
    allowed: set[str] | None = None,
    grant: dict | None = None,
    approval_id: str | None = None,
) -> dict:
    """Execute one tool call. Returns {"ok": bool, ...} — never raises to the caller.

    `allowed` is the caller's scope allow-list (an agent's granted tools, a workflow's node set).
    Enforcement lives HERE, in code, not in any prompt (security.md §4). Non-Agent callers
    (grant is None) additionally pass the central approval gate for external/destructive tools:
    the result then carries "approval" for the caller to surface, and a granted `approval_id`
    (digest-bound, single-use) authorizes exactly one retry of the same arguments.
    """
    if allowed is not None and key not in allowed:
        return {"ok": False, "error": f"Tool '{key}' is not in this scope's allow-list."}
    tool = _TOOLS.get(key)
    if tool is None:
        return {"ok": False, "error": f"Unknown tool '{key}'."}
    if tool.feature_flag:  # cheap deterministic refusal BEFORE asking a human for approval
        from backend.features import admin
        if not await admin.feature_enabled(tool.feature_flag):
            return {"ok": False, "error": f"Tool '{key}' is disabled by the current feature gates."}
    values = args or {}
    if grant is not None:
        actions = set(grant.get("actions") or [])
        if "execute" not in actions:
            return {"ok": False, "error": f"Tool '{key}' is not granted the execute action."}
        constraints = grant.get("resources") or {}
        for field in tool.resource_fields:
            permitted = {str(value) for value in constraints.get(field, [])}
            actual = values.get(field)
            if not permitted:
                return {"ok": False, "error": f"Tool '{key}' has no grant for resource '{field}'."}
            if isinstance(actual, list):
                accepted = all(str(value) in permitted for value in actual)
            else:
                accepted = str(actual) in permitted
            if not accepted:
                return {"ok": False, "error": f"Tool '{key}' cannot access that {field}."}
    try:
        config = tool.config_model.model_validate(values) if tool.config_model else None
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
        return {"ok": False, "error": f"Invalid arguments for '{key}': {problems}"}
    if grant is None:  # Chat/Automations: the central approval gate. Agent runs have their own.
        from backend.features import approvals
        verdict = await approvals.gate(tool, config.model_dump() if config else {}, approval_id)
        if not verdict["allowed"]:
            out = {"ok": False, "error": verdict.get("error") or "This action needs your approval."}
            if verdict.get("approval"):
                out["approval"] = verdict["approval"]
            return out
    try:
        result = await tool.execute(config)
    except Exception as exc:  # noqa: BLE001 — tool failures surface as data, sanitized
        from backend.security.secrets import redact_url
        log.warning("tool %s failed: %s", key, type(exc).__name__)
        return {"ok": False, "error": redact_url(str(exc))[:300]}
    out = {"ok": True}
    out.update(result or {})
    return out
