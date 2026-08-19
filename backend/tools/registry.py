"""The shared tool registry — the one place capabilities are registered and executed.

Chat, Automations, and Agents invoke tools ONLY through this registry, so scope allow-lists,
argument validation, and error sanitization are enforced once at the tool layer (security.md §4)
instead of drifting per feature. Adding a capability = one class + @register_tool; the UI/engine
discovers it from list_tools() — never a type-string switch (conventions.md).

Keys are stable once shipped: they get persisted in saved workflows and agent scopes.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.tools import hooks, lifecycle

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


_EVIDENCE_UNAVAILABLE = {
    "ok": False,
    "code": "evidence_unavailable",
    "retry_safe": True,
    "error": "This action was not run because its execution record could not be saved.",
}


async def _refuse(writer, code: str, message: str, *, outcome: str = "denied",
                  retry_safe: bool = True, extra: dict | None = None) -> dict:
    """One refusal shape for every guard: the caller's dict, and the durable fact behind it.

    Nothing here decides anything - the guard already did. `retry_safe` is True only where the
    tool body provably never started, which is what makes it safe for a model to try again.
    """
    result: dict = {"ok": False, "error": message, "code": code, "retry_safe": retry_safe}
    if extra:
        result.update(extra)
    if writer is not None:
        try:
            await writer.reject(
                lifecycle.TerminalOutcome(
                    outcome=outcome, code=code, dispatch_state="never_dispatched",
                    retry_safe=retry_safe, message=message,
                ),
                lifecycle.BoundedPresentation.from_value(result),
            )
        except Exception:  # noqa: BLE001 - the refusal itself still stands
            log.warning("could not record refusal %s for a tool call", code)
    return result


async def run_tool(
    key: str,
    args: dict | None = None,
    *,
    allowed: set[str] | None = None,
    grant: dict | None = None,
    approval_id: str | None = None,
    execution: "lifecycle.ToolExecutionIdentity | None" = None,
) -> dict:
    """Execute one tool call. Returns {"ok": bool, ...} — never raises to the caller.

    `allowed` is the caller's scope allow-list (an agent's granted tools, a workflow's node set).
    Enforcement lives HERE, in code, not in any prompt (security.md §4). Non-Agent callers
    (grant is None) additionally pass the central approval gate for external/destructive tools:
    the result then carries "approval" for the caller to surface, and a granted `approval_id`
    (digest-bound, single-use) authorizes exactly one retry of the same arguments.

    `execution` turns on Slice 1 evidence (ADR-005): the call and its outcome are recorded durably
    before either becomes model-visible. Evidence never grants authority - every guard below still
    decides - but it does gate the body: if the admission record cannot be written the call is
    refused as retry-safe rather than run unrecorded, and if the outcome cannot be written after the
    body ran the caller is told the effect is unknown rather than safe to repeat. Callers that pass
    nothing keep exactly the old behavior.
    """
    if execution is None:
        return await _run_tool_guarded(key, args, allowed=allowed, grant=grant,
                                       approval_id=approval_id, writer=None)

    writer = lifecycle.start(execution, key, args or {}, arguments_state="validated")
    return await _run_tool_guarded(key, args, allowed=allowed, grant=grant,
                                   approval_id=approval_id, writer=writer)


async def _run_tool_guarded(
    key: str,
    args: dict | None,
    *,
    allowed: set[str] | None,
    grant: dict | None,
    approval_id: str | None,
    writer,
) -> dict:
    """The guard sequence. `writer` is None for callers that did not ask for evidence."""
    if allowed is not None and key not in allowed:
        return await _refuse(writer, "out_of_scope",
                             f"Tool '{key}' is not in this scope's allow-list.")
    tool = _TOOLS.get(key)
    if tool is None:
        return await _refuse(writer, "unknown_tool", f"Unknown tool '{key}'.")
    if tool.feature_flag:  # cheap deterministic refusal BEFORE asking a human for approval
        from backend.features import admin
        if not await admin.feature_enabled(tool.feature_flag):
            return await _refuse(writer, "feature_disabled",
                                 f"Tool '{key}' is disabled by the current feature gates.")
    values = args or {}
    if grant is not None:
        actions = set(grant.get("actions") or [])
        if "execute" not in actions:
            return await _refuse(writer, "grant_missing_action",
                                 f"Tool '{key}' is not granted the execute action.")
        constraints = grant.get("resources") or {}
        for field in tool.resource_fields:
            permitted = {str(value) for value in constraints.get(field, [])}
            actual = values.get(field)
            if not permitted:
                return await _refuse(writer, "grant_missing_resource",
                                     f"Tool '{key}' has no grant for resource '{field}'.")
            if isinstance(actual, list):
                accepted = all(str(value) in permitted for value in actual)
            else:
                accepted = str(actual) in permitted
            if not accepted:
                return await _refuse(writer, "grant_denied",
                                     f"Tool '{key}' cannot access that {field}.")
    try:
        config = tool.config_model.model_validate(values) if tool.config_model else None
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
        return await _refuse(writer, "validation_failed",
                             f"Invalid arguments for '{key}': {problems}")
    # ADR-004 seam: registered policy may object here, after every built-in guard has run and
    # before the user is asked to approve anything. A hook can only deny - it cannot approve a call
    # the guards above already refused, and an empty registry means exactly the old behavior.
    objection = await hooks.deny_reason_for_tool(hooks.ToolCall(
        key=key,
        args=config.model_dump() if config else dict(values),
        risk=tool.risk,
        writes=bool(tool.writes),
        grant=grant,
    ))
    if objection is not None:
        denied_by, reason = objection
        return await _refuse(writer, "policy_denied", reason, extra={"denied_by": denied_by})
    if grant is None:  # Chat/Automations: the central approval gate. Agent runs have their own.
        from backend.features import approvals
        verdict = await approvals.gate(tool, config.model_dump() if config else {}, approval_id)
        if not verdict["allowed"]:
            message = verdict.get("error") or "This action needs your approval."
            extra = {"approval": verdict["approval"]} if verdict.get("approval") else None
            return await _refuse(writer, "approval_required", message, extra=extra)

    # Past every guard: the call is authorized, so this is where it is admitted. Admission happens
    # HERE and not earlier because a refused call must not leave an admitted record behind - the
    # refusal itself opens the record instead.
    warning = None
    if writer is not None:
        try:
            await writer.admit()
        except Exception as exc:  # noqa: BLE001 - unrecorded execution is worse than no execution
            log.warning("tool %s refused: evidence unavailable (%s)", key, type(exc).__name__)
            return _EVIDENCE_UNAVAILABLE
        try:
            warning = await writer.repeated_call_warning()
        except Exception:  # noqa: BLE001 - a missing loop warning must never block a legal call
            log.debug("repeat check unavailable for %s", key)
        # From here the body may touch the world, so the fact that it started has to be durable
        # BEFORE it does - that is what lets recovery tell "never ran" from "outcome unknown".
        try:
            await writer.body_started()
        except Exception as exc:  # noqa: BLE001
            log.warning("tool %s refused: could not record dispatch (%s)", key, type(exc).__name__)
            return _EVIDENCE_UNAVAILABLE

    try:
        result = await tool.execute(config)
    except asyncio.CancelledError:
        if writer is not None:
            with contextlib.suppress(Exception):
                await writer.cancelled()
        raise
    except Exception as exc:  # noqa: BLE001 — tool failures surface as data, sanitized
        from backend.security.secrets import redact_url
        log.warning("tool %s failed: %s", key, type(exc).__name__)
        failed = {"ok": False, "error": redact_url(str(exc))[:300], "code": "tool_failed",
                  "retry_safe": False}
        return await _record_terminal(writer, failed, outcome="failed", code="tool_failed")

    out = {"ok": True}
    out.update(result or {})
    if warning:
        out["loop_warning"] = warning
    return await _record_terminal(writer, out, outcome="succeeded", code="succeeded")


async def _record_terminal(writer, result: dict, *, outcome: str, code: str) -> dict:
    """Persist the outcome of a body that ran, and say so honestly if that fails.

    The body already happened. If its record cannot be written we must not imply the call can be
    repeated safely: `unknown_outcome` is the only truthful answer, and it is not retry-safe.
    """
    if writer is None:
        return result
    try:
        await writer.complete(
            lifecycle.TerminalOutcome(
                outcome=outcome, code=code, dispatch_state="started", retry_safe=False,
                message=result.get("error", ""),
            ),
            lifecycle.BoundedPresentation.from_value(result),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("tool outcome could not be recorded (%s)", type(exc).__name__)
        return {
            "ok": False,
            "code": "unknown_outcome",
            "retry_safe": False,
            "error": "This action ran, but its result could not be saved, so whether it took "
                     "effect is unknown - do not retry it blindly; check the target first.",
        }
    return result
