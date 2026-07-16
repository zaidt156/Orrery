"""/mcp API routes (split from the api.py monolith; same behavior)."""

from fastapi import APIRouter, HTTPException

from backend.api.schemas import *  # noqa: F401,F403 — request models
from backend.features import mcp, team

router = APIRouter()

@router.get("/mcp")
async def mcp_list() -> dict:
    return {"servers": await mcp.list_servers()}

@router.post("/mcp")
async def mcp_create(body: McpBody) -> dict:
    return await mcp.create_server(body.name, body.transport, body.command, body.url, body.enabled, env=body.env)

@router.patch("/mcp/{sid}")
async def mcp_update(sid: str, body: McpUpdate) -> dict:
    if not await mcp.update_server(sid, **body.model_dump(exclude_unset=True)):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"updated": True}

@router.delete("/mcp/{sid}")
async def mcp_delete(sid: str) -> dict:
    if not await mcp.delete_server(sid):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"deleted": True}

@router.post("/mcp/{sid}/test")
async def mcp_test(sid: str) -> dict:
    """Connect to the server and cache its tool list (the UI 'Test connection' action)."""
    return await mcp.refresh_tools(sid)

@router.post("/mcp/{sid}/approve")
async def mcp_approve(sid: str) -> dict:
    if not await team.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required.")
    if not await mcp.set_status(sid, "approved"):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"approved": True}

# --- admin: global feature flags (gated by an admin token once one is set) ---
