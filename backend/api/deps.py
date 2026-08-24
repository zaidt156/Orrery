"""Shared route helpers: SSE streaming and conversation access checks."""
from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from backend.features import chat
from backend.features import team
from backend.providers import ai, catalog


def _sse(source) -> StreamingResponse:
    async def event_stream():
        async for event in source:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse_run(conv_id: str, source) -> StreamingResponse:
    """Stream a conversation generation that keeps running on the backend even if the
    client disconnects (navigates away), so the reply always completes and is saved."""
    queue = chat.start_detached(conv_id, source)
    return _sse(chat.observe(queue))


async def _require_conversation_access(conv_id: str) -> None:
    if not await chat.can_access_conversation(conv_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


async def _require_admin_access() -> None:
    """Require admin privileges in team mode; solo mode is treated as the local admin."""
    if not await team.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required.")


def require_feature(name: str):
    """Router dependency: refuse a whole surface when its admin feature flag is off.

    Hiding a React tab is a courtesy, not a control. Anything that can reach loopback with the
    session — a script, a tool, another local process — never saw the navigation bar, so the gate
    has to live on the server (security.md §4).

    `admin.feature_enabled` already fails closed on an unreadable flag state; this re-raises that
    decision as a 403 and re-checks it here so an exception from the lookup cannot read as allowed.
    Routes that administer the workspace or report its configuration are deliberately never gated —
    gating them would make "turn everything off" unrecoverable.
    """
    async def _gate() -> None:
        from backend.features import admin

        try:
            allowed = await admin.feature_enabled(name)
        except Exception:  # noqa: BLE001 — an undecidable gate is a closed gate
            allowed = False
        if not allowed:
            label = admin.FEATURES.get(name, (name, True))[0]
            raise HTTPException(
                status_code=403,
                detail=f"{label} is turned off for this workspace.",
            )

    return _gate


async def _activate_provider(provider: str) -> None:
    """Turn on a provider's curated models when it's first configured (best-effort)."""
    try:
        models = await ai.provider_models(provider)
        await catalog.activate_many(
            [{"id": m["id"], "label": m["label"], "provider": m["provider"]} for m in models]
        )
    except Exception:  # noqa: BLE001 — activation is a convenience, never blocks key save
        pass
