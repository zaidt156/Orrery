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

from backend.features import (
    workspace, workspace_log, workspace_roots, workspace_run, workspace_write,
)
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


# --- changing files ---------------------------------------------------------------------------
#
# The irreversible half. ADR-007 gave up diff-then-apply, so the compensating control is the write
# log — and these tools are the only place it gets written. The shape is always the same:
#
#     open the record  →  touch the file  →  complete the record
#
# in that order, because a mutation with no row is invisible forever while a row with no mutation
# is self-evident. `_recorded` below is the one implementation of that sequence; a second one
# written later is how the log starts missing changes.
#
# Like `work_run`, these require a `root_id` rather than inheriting the current folder: approval is
# remembered per folder, and a remembered approval must not survive the user attaching another one.


class WorkWriteConfig(BaseModel):
    root_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=4_000)
    content: str = Field(default="", max_length=workspace_write.MAX_WRITE_BYTES)


class WorkEditConfig(WorkWriteConfig):
    # The digest of the content the caller actually read. Not optional: an edit that cannot say what
    # it saw is a blind overwrite, which is the failure `edit` exists to prevent.
    observed_digest: str = Field(min_length=32, max_length=64)


class WorkDeleteConfig(BaseModel):
    root_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=4_000)


class WorkChangesConfig(_RootedConfig):
    limit: int = Field(default=50, ge=1, le=500)


class _MutatingTool(_WorkspaceTool):
    """Every file change, recorded either side of itself."""

    writes = True
    risk = "external_write"

    async def _recorded(self, root_id: str, root: str, planned: dict, operation) -> dict:
        """Open the record, run the operation, complete the record. Failures are recorded too.

        `planned` is what is known before touching the file — path, action, and the digest of what
        is there now. It is deliberately written down first: if this process dies mid-write, the row
        already says a change to that path was under way.
        """
        entry = await workspace_log.begin(root_id, planned)
        try:
            done = await asyncio.to_thread(operation)
        except Exception as exc:
            # Recorded, not erased: an attempt that failed is not the same as one that never
            # happened, and an attempt to overwrite a file is worth knowing about either way.
            await workspace_log.fail(entry, f"{type(exc).__name__}: {exc}")
            raise
        await workspace_log.finish(entry, done)
        return done

    async def _planned(self, root: str, path: str, action: str) -> dict:
        """What is true before the change, with the boundary already enforced.

        `resolve_in_root` runs here, before the record is opened, so a path outside the folder never
        appears in the log — it was never a change to this folder to begin with.
        """
        resolved = workspace.resolve_in_root(root, path)
        existing = None
        if resolved.is_file():
            existing = workspace_write.digest_of(resolved.read_bytes())
        # The canonical path, so the row opened before the write names the same file as the row
        # completed after it — two spellings of one path would read as two changes.
        return {"path": workspace.relative_in_root(root, resolved), "action": action,
                "digest_before": existing, "digest_after": None, "bytes_after": 0}


@register_tool("work_write")
class WorkWriteTool(_MutatingTool):
    label = "Write a file in the attached folder"
    config_model = WorkWriteConfig

    async def execute(self, config: WorkWriteConfig) -> dict:
        root = await self._root(config)
        planned = await self._planned(root, config.path, "created")
        if planned["digest_before"] is not None:
            planned["action"] = "modified"
        return await self._recorded(
            config.root_id, root, planned,
            lambda: workspace_write.write_file(root, config.path, config.content),
        )


@register_tool("work_edit")
class WorkEditTool(_MutatingTool):
    label = "Edit a file in the attached folder"
    config_model = WorkEditConfig

    async def execute(self, config: WorkEditConfig) -> dict:
        root = await self._root(config)
        planned = await self._planned(root, config.path, "modified")
        return await self._recorded(
            config.root_id, root, planned,
            lambda: workspace_write.edit_file(
                root, config.path, config.observed_digest, config.content
            ),
        )


@register_tool("work_delete")
class WorkDeleteTool(_MutatingTool):
    """Deleting is `destructive`, which the approval gate never remembers.

    security.md §4 names deletes as the canonical case for a gate that asks every time, and
    `approvals.gate` already refuses to remember a destructive tool. Marking the risk correctly is
    what opts this into that — there is no separate rule to write.
    """

    label = "Delete a file in the attached folder"
    risk = "destructive"
    config_model = WorkDeleteConfig

    async def execute(self, config: WorkDeleteConfig) -> dict:
        root = await self._root(config)
        planned = await self._planned(root, config.path, "deleted")
        return await self._recorded(
            config.root_id, root, planned,
            lambda: workspace_write.delete_file(root, config.path),
        )


@register_tool("work_changes")
class WorkChangesTool(_WorkspaceTool):
    """What has been changed in this folder, newest first.

    A log nobody can read is not a compensating control, and ADR-007 traded diff review for exactly
    this. Reading it is a read: no approval, no write flag.
    """

    label = "See what changed in the attached folder"
    config_model = WorkChangesConfig

    async def execute(self, config: WorkChangesConfig) -> dict:
        root_id = config.root_id or (await workspace_roots.active_root() or {}).get("id")
        return {"changes": await workspace_log.history(root_id, limit=config.limit)}
