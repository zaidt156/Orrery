"""Built-in tools: existing Orrery capabilities exposed through the shared registry.

Each wraps a feature module the app already trusts — the registry adds the uniform scope check,
validation, and error shape. Feature imports happen inside execute() so importing the registry never
drags in heavy modules (or cycles) at startup. Outputs that come from the outside world (web pages,
MCP servers, database rows) are DATA, never instructions (security.md §6) — callers must keep them
in untrusted context.
"""
from __future__ import annotations

import asyncio
import mimetypes

from pydantic import BaseModel, Field

from backend.tools.registry import Tool, register_tool


def _store_sandbox_files(files) -> list[dict]:
    from backend.features import files as file_library

    produced: list[dict] = []
    for item in files:
        mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
        try:
            produced.append({"kind": "file", **file_library.store(item.name, mime, item.data)})
        except ValueError:
            continue
    return produced


class WebSearchConfig(BaseModel):
    query: str = Field(min_length=1, max_length=400)
    max_results: int = Field(default=5, ge=1, le=10)


@register_tool("web_search")
class WebSearchTool(Tool):
    label = "Web search"
    category = "net"
    config_model = WebSearchConfig

    async def execute(self, config: WebSearchConfig) -> dict:
        from backend.features import websearch
        results = await websearch.search(config.query, max_results=config.max_results)
        return {"results": results}


class DocSearchConfig(BaseModel):
    collection_id: str = Field(min_length=8)
    query: str = Field(min_length=1, max_length=400)
    k: int = Field(default=5, ge=1, le=12)


@register_tool("doc_search")
class DocSearchTool(Tool):
    label = "Search my documents"
    category = "ai"
    config_model = DocSearchConfig

    async def execute(self, config: DocSearchConfig) -> dict:
        from backend.features import rag
        hits = await rag.search(config.collection_id, config.query, k=config.k)
        return {"snippets": hits}


class DbQueryConfig(BaseModel):
    connection_id: str = Field(min_length=8)
    sql: str = Field(min_length=1, max_length=8000)
    row_cap: int = Field(default=200, ge=1, le=1000)


@register_tool("db_query")
class DbQueryTool(Tool):
    label = "Database query (read-only)"
    category = "data"
    config_model = DbQueryConfig

    async def execute(self, config: DbQueryConfig) -> dict:
        # Belt: single read-only SELECT by parse; braces: the connection itself refuses writes.
        from backend.features import dashboards, data
        err = dashboards.validate_widget_sql(config.sql)
        if err:
            raise ValueError(err)
        cols, rows = await data.run_readonly_query(config.connection_id, config.sql, row_cap=config.row_cap)
        return {"columns": cols, "rows": rows}


class RunPythonConfig(BaseModel):
    code: str = Field(min_length=1, max_length=60_000)


@register_tool("run_python")
class RunPythonTool(Tool):
    label = "Run Python (sandbox)"
    category = "code"
    config_model = RunPythonConfig

    async def execute(self, config: RunPythonConfig) -> dict:
        from backend.features import sandbox
        if not sandbox.image_ready():
            raise RuntimeError("The code sandbox is offline (Docker isn't running or the image isn't built).")
        result = await asyncio.to_thread(sandbox.run_code, config.code)
        artifacts = _store_sandbox_files(result.files)
        return {
            "exit_code": result.exit_code, "timed_out": result.timed_out,
            "stdout": result.stdout[:8000], "stderr": result.stderr[:4000],
            "files": [f.name for f in result.files], "artifacts": artifacts,
            "sandbox": result.manifest,
        }


class RunShellConfig(BaseModel):
    script: str = Field(min_length=1, max_length=60_000)


@register_tool("run_shell")
class RunShellTool(Tool):
    label = "Run shell commands (sandbox)"
    category = "code"
    config_model = RunShellConfig

    async def execute(self, config: RunShellConfig) -> dict:
        from backend.features import sandbox
        if not sandbox.image_ready():
            raise RuntimeError("The code sandbox is offline (Docker isn't running or the image isn't built).")
        result = await asyncio.to_thread(sandbox.run_shell, config.script)
        artifacts = _store_sandbox_files(result.files)
        return {
            "exit_code": result.exit_code, "timed_out": result.timed_out,
            "stdout": result.stdout[:8000], "stderr": result.stderr[:4000],
            "files": [f.name for f in result.files], "artifacts": artifacts,
            "sandbox": result.manifest,
        }


class FileGenerateConfig(BaseModel):
    request: str = Field(min_length=1, max_length=20_000)
    model: str = Field(default="", max_length=200)
    system_prompt: str = Field(default="", max_length=20_000)
    effort: str = Field(default="", max_length=20)
    trusted_context: str = Field(default="", max_length=40_000)
    untrusted_context: str = Field(default="", max_length=40_000)


@register_tool("file_generate")
class FileGenerateTool(Tool):
    label = "Generate file"
    category = "code"
    writes = True
    config_model = FileGenerateConfig

    async def execute(self, config: FileGenerateConfig) -> dict:
        from backend.features import filegen

        if not config.model:
            raise ValueError("file_generate requires the caller's current model.")
        result = None
        async for event in filegen.run(
            config.model,
            config.request,
            config.system_prompt or None,
            config.effort or None,
            config.untrusted_context or None,
            config.trusted_context or None,
        ):
            if "result" in event:
                result = event["result"]
        if not result or not result.get("ok"):
            raise RuntimeError((result or {}).get("error") or "File generation did not produce an approved file.")
        artifacts = _store_sandbox_files(result.get("files") or [])
        if not artifacts:
            raise RuntimeError("Generated files could not be stored.")
        return {
            "summary": result.get("summary") or "Created the requested file.",
            "files": [item.get("name") for item in artifacts],
            "artifacts": artifacts,
            "manifest": result.get("manifest") or [],
            "sandbox_runs": result.get("sandbox_runs") or [],
        }


class CrabboxRunConfig(BaseModel):
    command: list[str] = Field(default_factory=list, max_length=48)
    shell: str = Field(default="", max_length=8_000)
    label: str = Field(default="", max_length=120)
    timeout_seconds: int | None = Field(default=None, ge=10, le=7200)


@register_tool("crabbox_run")
class CrabboxRunTool(Tool):
    label = "Run command with Crabbox"
    category = "code"
    writes = True
    config_model = CrabboxRunConfig

    async def execute(self, config: CrabboxRunConfig) -> dict:
        from backend.features import admin, crabbox

        if not await admin.feature_enabled("crabbox"):
            raise PermissionError("Crabbox is disabled by the current feature gates.")
        return await crabbox.run_command(
            command=config.command,
            shell=config.shell,
            label=config.label,
            timeout_seconds=config.timeout_seconds,
        )


class DashboardRefreshConfig(BaseModel):
    dashboard_id: str = Field(min_length=8)


@register_tool("dashboard_refresh")
class DashboardRefreshTool(Tool):
    label = "Refresh dashboard"
    category = "tools"
    config_model = DashboardRefreshConfig

    async def execute(self, config: DashboardRefreshConfig) -> dict:
        from backend.features import dashboards
        board = await dashboards.run_dashboard(config.dashboard_id)
        if board is None:
            raise ValueError("Dashboard not found.")
        widgets = board.get("widgets", [])
        return {
            "dashboard": board.get("name"),
            "widgets": [{"title": w.get("title"), "rows": len(w.get("rows", [])),
                         "error": w.get("error")} for w in widgets],
        }


class McpCallConfig(BaseModel):
    server_id: str = Field(min_length=8)
    tool: str = Field(min_length=1, max_length=120)
    args: dict = Field(default_factory=dict)


@register_tool("mcp_call")
class McpCallTool(Tool):
    label = "MCP tool call"
    category = "net"
    writes = True  # external side effects are unknown → approval-gated wherever gates apply
    config_model = McpCallConfig

    async def execute(self, config: McpCallConfig) -> dict:
        from backend.features import mcp
        res = await mcp.call_tool_by_id(config.server_id, config.tool, config.args)
        if not res.get("ok"):
            raise RuntimeError(res.get("error", "MCP call failed"))
        return {"text": (res.get("text") or "")[:8000]}
