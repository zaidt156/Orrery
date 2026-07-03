"""Shared route helpers: SSE streaming and conversation access checks."""
from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from backend.features import chat
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


async def _activate_provider(provider: str) -> None:
    """Turn on a provider's curated models when it's first configured (best-effort)."""
    try:
        models = await ai.provider_models(provider)
        await catalog.activate_many(
            [{"id": m["id"], "label": m["label"], "provider": m["provider"]} for m in models]
        )
    except Exception:  # noqa: BLE001 — activation is a convenience, never blocks key save
        pass
