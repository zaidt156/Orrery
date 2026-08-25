"""Orrery Work's read tools: look at the attached folder, and only at the attached folder.

These are registered rather than called directly, and that is the whole design decision. Routing
them through the registry means scope allow-lists, the ADR-004 deny hook, the approval gate and
ADR-005 evidence apply to Orrery Work exactly as they apply to everything else — Orrery Work adds
capability, not a second execution path (ADR-007 §3).

Two rules, and neither is negotiable:

**Every path goes through `workspace.resolve_in_root`.** No tool here does its own path arithmetic.
A second, weaker check written later is precisely how the hole gets made.

**The root comes from `workspace_roots`, never from the caller.** A tool that accepted a folder in
its arguments would let anything that could reach the registry name its own boundary, which is not
a boundary. What the caller may name is a *root id*, which is then checked for ownership.

Reads are marked `sensitive_read` because an attached folder is the user's real project — source,
config, and whatever else happens to live there — not Orrery's own data.
"""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from backend.features import workspace, workspace_roots, workspace_run
from backend.tools.registry import Tool, register_tool

FEATURE_FLAG = "orrery_work"


class _RootedConfig(BaseModel):
    """Every workspace tool names which attached folder it means, or accepts the current one."""

    root_id: str = Field(default="", max_length=64)


class WorkReadConfig(_RootedConfig):
    path: str = Field(min_length=1, max_length=4_000)
    max_bytes: int = Field(default=workspace.MAX_READ_BYTES, ge=1, le=workspace.MAX_READ_BYTES)


class WorkGlobConfig(_RootedConfig):
    pattern: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=workspace.MAX_FIND_RESULTS, ge=1, le=workspace.MAX_FIND_RESULTS)


class WorkGrepConfig(_RootedConfig):
    expression: str = Field(min_length=1, max_length=1_000)
    glob: str = Field(default="**/*", max_length=500)
    limit: int = Field(default=workspace.MAX_GREP_MATCHES, ge=1, le=workspace.MAX_GREP_MATCHES)


class _WorkspaceTool(Tool):
    category = "code"
    writes = False
    risk = "sensitive_read"          # the user's real project, not Orrery's own data
    feature_flag = FEATURE_FLAG
    resource_fields = ("root_id",)   # an agent grant constrains which folder, not which path

    async def _root(self, config: _RootedConfig) -> str:
        return await workspace_roots.root_path(config.root_id or None)


@register_tool("work_read")
class WorkReadTool(_WorkspaceTool):
    label = "Read a file in the attached folder"
    config_model = WorkReadConfig

    async def execute(self, config: WorkReadConfig) -> dict:
        root = await self._root(config)
        # Filesystem work is blocking; a large file on a slow disk would otherwise stall the loop.
        return await asyncio.to_thread(
            workspace.read_file, root, config.path, max_bytes=config.max_bytes
        )


@register_tool("work_glob")
class WorkGlobTool(_WorkspaceTool):
    label = "Find files in the attached folder"
    config_model = WorkGlobConfig

    async def execute(self, config: WorkGlobConfig) -> dict:
        root = await self._root(config)
        return await asyncio.to_thread(workspace.find, root, config.pattern, limit=config.limit)


@register_tool("work_grep")
class WorkGrepTool(_WorkspaceTool):
    label = "Search the attached folder"
    config_model = WorkGrepConfig

    async def execute(self, config: WorkGrepConfig) -> dict:
        root = await self._root(config)
        return await asyncio.to_thread(
            workspace.grep, root, config.expression, glob=config.glob, limit=config.limit
        )


class WorkRunConfig(BaseModel):
    """`root_id` is required here, unlike the read tools.

    Approval for running commands is remembered *per folder* (see `approvals._remember_key`), and a
    remembered approval must not survive the user attaching a different folder. Accepting "whatever
    is currently attached" would make that impossible to guarantee, so the dangerous tool is made to
    name its boundary explicitly.
    """

    root_id: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=10_000)
    timeout: int = Field(default=workspace_run.DEFAULT_TIMEOUT, ge=1, le=workspace_run.MAX_TIMEOUT)


@register_tool("work_run")
class WorkRunTool(_WorkspaceTool):
    """Run a command on the host, in the attached folder.

    `writes` and the `external_write` risk are both deliberate. This is the tool that can change the
    user's machine, so it goes through the approval gate every time it is not already approved for
    that folder — and `external_write` rather than `destructive` because `destructive` can never be
    remembered at all, which would mean approving every single step of a build. The folder is the
    unit a user can actually reason about.
    """

    label = "Run a command in the attached folder"
    writes = True
    risk = "external_write"
    config_model = WorkRunConfig

    async def execute(self, config: WorkRunConfig) -> dict:
        root = await self._root(config)
        return await workspace_run.run_command(root, config.command, timeout=config.timeout)
