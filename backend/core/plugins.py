"""Mounting local plugins (ADR-004).

A plugin is an importable Python module the user has deliberately installed, named in a
configuration layer (`backend.core.profiles`). Mounting calls its ``setup(ctx)``, and everything it
registers through that context is recorded so unmounting takes it all back off - the reversible
effect that makes a plugin something you can turn off rather than something you have to uninstall.

What a plugin may do is deliberately narrow, and follows the rule in ADR-004: **deny, observe, or
annotate - never grant.** The context exposes the two hook seams and nothing else. It cannot widen a
grant, register an authorization decision, or replace the approval gate; those are the floor a
plugin runs on top of, not services it can swap. Every hook it registers still runs after the
built-in guards in ``run_tool()``.

Nothing here fetches code. A plugin name is a module path that must already be importable; there is
no URL, no download, and no install step hidden inside mounting.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from collections.abc import Callable

from backend.tools import hooks

log = logging.getLogger("orrery.plugins")


class PluginError(RuntimeError):
    """A declared plugin could not be mounted."""


@dataclass
class PluginContext:
    """What a plugin is handed. Every registration made through it is reversible."""

    name: str
    _unloaders: list[Callable[[], None]] = field(default_factory=list)

    def register_pre_execute(self, label: str, hook: hooks.ToolHook) -> None:
        """Object to a tool call before it executes. Returning None is not approval."""
        self._unloaders.append(hooks.register_pre_execute(f"{self.name}:{label}", hook))

    def register_pre_step(self, label: str, hook: hooks.StepHook) -> None:
        """Object to an agent run's next model request."""
        self._unloaders.append(hooks.register_pre_step(f"{self.name}:{label}", hook))

    def _unload(self) -> None:
        while self._unloaders:
            self._unloaders.pop()()


@dataclass(frozen=True)
class Mounted:
    name: str
    context: PluginContext


_mounted: list[Mounted] = []


def mount(name: str) -> Mounted:
    """Import a plugin module and run its ``setup(ctx)``.

    Failure raises. A plugin the user declared is a policy they asked for, and quietly running
    without it would be the least safe outcome available.
    """
    unsafe = ("/", "\\", ":", "..")
    if not isinstance(name, str) or not name or any(bit in name for bit in unsafe):
        raise PluginError(f"{name!r} is not a module path. Plugins are imported, never fetched.")
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001
        raise PluginError(f"Could not import plugin {name!r}: {exc}") from None

    setup = getattr(module, "setup", None)
    if not callable(setup):
        raise PluginError(f"Plugin {name!r} has no setup(ctx) function.")

    ctx = PluginContext(name=name)
    try:
        setup(ctx)
    except Exception as exc:  # noqa: BLE001
        ctx._unload()  # a half-mounted plugin leaves nothing behind
        raise PluginError(f"Plugin {name!r} failed during setup: {exc}") from None

    entry = Mounted(name=name, context=ctx)
    _mounted.append(entry)
    log.info("mounted plugin %s", name)
    return entry


def mount_all(names: list[str] | None = None) -> list[str]:
    """Mount every declared plugin. Called once at startup."""
    if names is None:
        from backend.core.config import settings
        names = list(settings.plugins or [])
    for name in names:
        mount(name)
    return [m.name for m in _mounted]


def unmount_all() -> None:
    """Reverse every registration made by every mounted plugin."""
    while _mounted:
        entry = _mounted.pop()
        entry.context._unload()
        log.info("unmounted plugin %s", entry.name)


def mounted() -> list[str]:
    return [m.name for m in _mounted]
