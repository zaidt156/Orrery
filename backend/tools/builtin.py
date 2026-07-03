"""Built-in tools: existing Orrery capabilities exposed through the shared registry.

Each wraps a feature module the app already trusts — the registry adds the uniform scope check,
validation, and error shape. Feature imports happen inside execute() so importing the registry never
drags in heavy modules (or cycles) at startup. Outputs that come from the outside world (web pages,
MCP servers, database rows) are DATA, never instructions (security.md §6) — callers must keep them
in untrusted context.
"""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from backend.tools.registry import Tool, register_tool


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
        return {
            "exit_code": result.exit_code, "timed_out": result.timed_out,
            "stdout": result.stdout[:8000], "stderr": result.stderr[:4000],
            "files": [f.name for f in result.files],
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
        return {
            "exit_code": result.exit_code, "timed_out": result.timed_out,
            "stdout": result.stdout[:8000], "stderr": result.stderr[:4000],
            "files": [f.name for f in result.files],
        }


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
