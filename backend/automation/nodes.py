"""Built-in workflow nodes. Wherever a shared tool exists, the node calls it through the tool
registry with an explicit allow-list — scope, validation, and sanitized errors enforced once at
the tool layer (security.md §4). Node outputs are DATA for later nodes, never instructions.

Templating: string config fields may reference earlier outputs as {{node_id.key}} (or {{node_id}}
for the whole output as JSON); the engine substitutes values before execution.
"""
from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel, Field

from backend.automation.registry import Node, register_node
from backend.tools import run_tool


class LlmPromptConfig(BaseModel):
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1, max_length=20_000)


@register_node("llm_prompt")
class LlmPromptNode(Node):
    label = "LLM prompt"
    category = "ai"
    config_model = LlmPromptConfig

    async def execute(self, inputs: dict, config: LlmPromptConfig) -> dict:
        from backend.providers import ai
        parts: list[str] = []
        async for delta in ai.stream_chat(config.model, [{"role": "user", "content": config.prompt}], None, None):
            if not isinstance(delta, ai.ReasoningDelta):
                parts.append(str(delta))
        from backend.features.prompting import strip_think
        return {"text": strip_think("".join(parts)).strip()}


class SearchDocsConfig(BaseModel):
    collection_id: str = Field(min_length=8)
    query: str = Field(min_length=1, max_length=400)


@register_node("search_docs")
class SearchDocsNode(Node):
    label = "Search my documents"
    category = "ai"
    config_model = SearchDocsConfig

    async def execute(self, inputs: dict, config: SearchDocsConfig) -> dict:
        return await run_tool("doc_search", {"collection_id": config.collection_id, "query": config.query},
                              allowed={"doc_search"})


class DbQueryConfig(BaseModel):
    connection_id: str = Field(min_length=8)
    sql: str = Field(min_length=1, max_length=8000)


@register_node("db_query")
class DbQueryNode(Node):
    label = "Database query (read-only)"
    category = "data"
    config_model = DbQueryConfig

    async def execute(self, inputs: dict, config: DbQueryConfig) -> dict:
        return await run_tool("db_query", {"connection_id": config.connection_id, "sql": config.sql},
                              allowed={"db_query"})


class HttpRequestConfig(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    method: str = "GET"


@register_node("http_request")
class HttpRequestNode(Node):
    label = "HTTP request"
    category = "net"
    config_model = HttpRequestConfig

    async def execute(self, inputs: dict, config: HttpRequestConfig) -> dict:
        import httpx

        from backend.features import team
        from backend.security import netguard
        url = netguard.validate_fetch_url(config.url, allow_private=not await team.team_mode())
        method = config.method.upper() if config.method.upper() in ("GET", "HEAD") else "GET"
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.request(method, url)
        body = resp.text[:20_000]
        try:
            data = resp.json()
        except ValueError:
            data = None
        return {"status": resp.status_code, "body": body, "json": data}


class RunPythonConfig(BaseModel):
    code: str = Field(min_length=1, max_length=60_000)


@register_node("run_python")
class RunPythonNode(Node):
    label = "Run Python (sandbox)"
    category = "code"
    config_model = RunPythonConfig

    async def execute(self, inputs: dict, config: RunPythonConfig) -> dict:
        return await run_tool("run_python", {"code": config.code}, allowed={"run_python"})


class RunShellConfig(BaseModel):
    script: str = Field(min_length=1, max_length=60_000)


@register_node("run_shell")
class RunShellNode(Node):
    label = "Run shell (sandbox)"
    category = "code"
    config_model = RunShellConfig

    async def execute(self, inputs: dict, config: RunShellConfig) -> dict:
        return await run_tool("run_shell", {"script": config.script}, allowed={"run_shell"})


class WebSearchConfig(BaseModel):
    query: str = Field(min_length=1, max_length=400)


@register_node("web_search")
class WebSearchNode(Node):
    label = "Web search"
    category = "net"
    config_model = WebSearchConfig

    async def execute(self, inputs: dict, config: WebSearchConfig) -> dict:
        return await run_tool("web_search", {"query": config.query}, allowed={"web_search"})


class IfBranchConfig(BaseModel):
    value: str = Field(default="", max_length=2000)       # usually a {{template}}
    contains: str = Field(default="", max_length=200)     # branch condition: substring match


@register_node("if_branch")
class IfBranchNode(Node):
    label = "If / branch"
    category = "logic"
    config_model = IfBranchConfig

    async def execute(self, inputs: dict, config: IfBranchConfig) -> dict:
        matched = bool(config.contains) and config.contains.lower() in (config.value or "").lower()
        # Downstream nodes read {{this.matched}}; the engine also skips the false branch's children
        return {"matched": matched, "value": config.value}


class DelayConfig(BaseModel):
    seconds: float = Field(default=1, ge=0, le=300)


@register_node("delay")
class DelayNode(Node):
    label = "Delay"
    category = "logic"
    config_model = DelayConfig

    async def execute(self, inputs: dict, config: DelayConfig) -> dict:
        await asyncio.sleep(config.seconds)
        return {"waited": config.seconds}


class RefreshDashboardConfig(BaseModel):
    dashboard_id: str = Field(min_length=8)


@register_node("refresh_dashboard")
class RefreshDashboardNode(Node):
    label = "Refresh dashboard"
    category = "tools"
    config_model = RefreshDashboardConfig

    async def execute(self, inputs: dict, config: RefreshDashboardConfig) -> dict:
        return await run_tool("dashboard_refresh", {"dashboard_id": config.dashboard_id},
                              allowed={"dashboard_refresh"})


class McpToolConfig(BaseModel):
    server_id: str = Field(min_length=8)
    tool: str = Field(min_length=1, max_length=120)
    args_json: str = Field(default="{}", max_length=4000)


@register_node("mcp_tool")
class McpToolNode(Node):
    label = "MCP tool"
    category = "net"
    config_model = McpToolConfig

    async def execute(self, inputs: dict, config: McpToolConfig) -> dict:
        try:
            args = json.loads(config.args_json or "{}")
        except ValueError:
            return {"ok": False, "error": "args_json is not valid JSON"}
        return await run_tool("mcp_call", {"server_id": config.server_id, "tool": config.tool, "args": args},
                              allowed={"mcp_call"})
