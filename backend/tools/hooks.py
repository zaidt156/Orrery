"""Deny-only seams around tool execution and agent steps (ADR-004).

Borrowed from harness designs where policy attaches at a named extension point instead of as
another branch inside the loop. One rule differs deliberately, and it is the whole reason this is
safe to have: **a hook may deny, observe, or annotate. It may never grant.**

The built-in guards in `registry.run_tool()` - scope allow-list, feature gate, grant actions and
resources, argument validation, the central approval gate - still run, and still have the final
say. A hook returning None does not approve anything; it only declines to object. Removing every
hook therefore leaves behavior at least as strict as it was, never looser.

Registration returns an unregister callable, so a caller that mounted a hook can take it back off
(the reversible-effect property harnesses rely on for unloading).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("orrery.tools.hooks")


@dataclass(frozen=True)
class ToolCall:
    """What a pre-execute hook is allowed to see. Arguments are already validated by this point."""

    key: str
    args: dict[str, Any] = field(default_factory=dict)
    risk: str = "read"
    writes: bool = False
    # An agent run passes its grant; Chat and Automations pass None and go through the approval gate.
    grant: dict[str, Any] | None = None

    @property
    def caller(self) -> str:
        return "agent" if self.grant is not None else "gate"


@dataclass(frozen=True)
class AgentStep:
    """What a pre-step hook is allowed to see, before an agent run makes its next model request."""

    run_id: str
    agent_id: str
    step_index: int
    model: str = ""


# A hook returns a denial reason, or None to raise no objection.
ToolHook = Callable[[ToolCall], Awaitable[str | None]]
StepHook = Callable[[AgentStep], Awaitable[str | None]]

_pre_execute: list[tuple[str, ToolHook]] = []
_pre_step: list[tuple[str, StepHook]] = []


def register_pre_execute(name: str, hook: ToolHook) -> Callable[[], None]:
    """Attach a hook that runs after every built-in guard and before the tool executes."""
    entry = (name, hook)
    _pre_execute.append(entry)

    def unregister() -> None:
        if entry in _pre_execute:
            _pre_execute.remove(entry)

    return unregister


def register_pre_step(name: str, hook: StepHook) -> Callable[[], None]:
    """Attach a hook that runs before each model request in an agent run."""
    entry = (name, hook)
    _pre_step.append(entry)

    def unregister() -> None:
        if entry in _pre_step:
            _pre_step.remove(entry)

    return unregister


def _clear() -> None:
    """Tests only: drop every registered hook."""
    _pre_execute.clear()
    _pre_step.clear()


async def deny_reason_for_tool(call: ToolCall) -> tuple[str, str] | None:
    """First (hook name, reason) that objects to this call, or None if none does."""
    return await _first_objection(_pre_execute, call, "pre-execute")


async def deny_reason_for_step(step: AgentStep) -> tuple[str, str] | None:
    """First (hook name, reason) that objects to this step, or None if none does."""
    return await _first_objection(_pre_step, step, "pre-step")


async def _first_objection(hooks, subject, label: str) -> tuple[str, str] | None:
    for name, hook in list(hooks):
        try:
            reason = await hook(subject)
        except Exception as exc:  # noqa: BLE001
            # Fail closed: a hook that breaks is treated as an objection, never as consent. A
            # broken policy must not become an open door.
            log.warning("%s hook %r failed: %s", label, name, type(exc).__name__)
            return name, "A policy check failed, so this action was not run."
        if reason:
            log.info("%s hook %r denied: %s", label, name, reason)
            return name, reason
    return None
