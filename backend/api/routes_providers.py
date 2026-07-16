"""/providers API routes (split from the api.py monolith; same behavior)."""
import asyncio

from fastapi import APIRouter, HTTPException

from backend.api.deps import _activate_provider, _require_admin_access
from backend.api.schemas import *  # noqa: F401,F403 — request models
from backend.providers import accounts, ai, catalog
from backend.security import secrets

router = APIRouter()

@router.get("/providers")
async def providers() -> dict:
    return await asyncio.to_thread(accounts.providers_status, ai.PROVIDERS)

@router.put("/providers/{provider}/key")
async def set_key(provider: str, body: ProviderKey) -> dict:
    await _require_admin_access()
    if provider not in ai.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if not body.key.strip():
        raise HTTPException(status_code=400, detail="Key is empty")
    secrets.set_provider_key(provider, body.key.strip())
    await _activate_provider(provider)  # so the new models show up in Chat right away
    return secrets.provider_key_status(provider)  # masked, never the raw key

@router.delete("/providers/{provider}/key")
async def clear_key(provider: str) -> dict:
    await _require_admin_access()
    if provider not in ai.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    secrets.clear_provider_key(provider)
    return secrets.provider_key_status(provider)

@router.post("/providers/anthropic/claude-plan/connect")
async def connect_claude_plan() -> dict:
    await _require_admin_access()
    try:
        status = await asyncio.to_thread(accounts.connect_claude_plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:  # auto-activate the plan's models; a seeding failure must not break connect
        await catalog.activate_many(
            [{"id": m["id"], "label": m["label"], "provider": m["provider"]}
             for m in await asyncio.to_thread(accounts.claude_plan_models)]
        )
    except Exception:  # noqa: BLE001
        pass
    return status

@router.delete("/providers/anthropic/claude-plan")
async def disconnect_claude_plan() -> dict:
    await _require_admin_access()
    return await asyncio.to_thread(accounts.disconnect_claude_plan)

@router.post("/providers/anthropic/claude-plan/install")
async def install_claude_cli(body: PlanConnection) -> dict:
    await _require_admin_access()
    try:
        return await asyncio.to_thread(accounts.install_plan_cli, "claude_plan", body.acknowledged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/providers/anthropic/claude-plan/login")
async def login_claude_cli() -> dict:
    await _require_admin_access()
    try:
        return await asyncio.to_thread(accounts.launch_plan_login, "claude_plan")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/providers/anthropic/claude-plan/refresh")
async def refresh_claude_cli() -> dict:
    await _require_admin_access()
    return await asyncio.to_thread(accounts.refresh_plan_mode, "claude_plan")

async def _activate_cli_plan(models_fn) -> None:
    try:
        await catalog.activate_many(
            [{"id": m["id"], "label": m["label"], "provider": m["provider"]}
             for m in await asyncio.to_thread(models_fn)]
        )
    except Exception:  # noqa: BLE001 — activation is best-effort, never blocks connect
        pass

@router.post("/providers/openai/chatgpt-plan/connect")
async def connect_chatgpt_plan(body: PlanConnection) -> dict:
    await _require_admin_access()
    try:
        status = await asyncio.to_thread(accounts.connect_chatgpt_plan, body.acknowledged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _activate_cli_plan(accounts.chatgpt_plan_models)
    return status

@router.delete("/providers/openai/chatgpt-plan")
async def disconnect_chatgpt_plan() -> dict:
    await _require_admin_access()
    return await asyncio.to_thread(accounts.disconnect_chatgpt_plan)

@router.post("/providers/openai/chatgpt-plan/install")
async def install_codex_cli(body: PlanConnection) -> dict:
    await _require_admin_access()
    try:
        return await asyncio.to_thread(accounts.install_plan_cli, "chatgpt_plan", body.acknowledged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/providers/openai/chatgpt-plan/login")
async def login_codex_cli() -> dict:
    await _require_admin_access()
    try:
        return await asyncio.to_thread(accounts.launch_plan_login, "chatgpt_plan")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/providers/openai/chatgpt-plan/refresh")
async def refresh_codex_cli() -> dict:
    await _require_admin_access()
    return await asyncio.to_thread(accounts.refresh_plan_mode, "chatgpt_plan")

@router.post("/providers/google/gemini-plan/connect")
async def connect_gemini_plan(body: PlanConnection) -> dict:
    await _require_admin_access()
    try:
        status = await asyncio.to_thread(accounts.connect_gemini_plan, body.acknowledged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _activate_cli_plan(accounts.gemini_plan_models)
    return status

@router.delete("/providers/google/gemini-plan")
async def disconnect_gemini_plan() -> dict:
    await _require_admin_access()
    return await asyncio.to_thread(accounts.disconnect_gemini_plan)

# --- local models (official Ollama service) ---
