import asyncio
import sys
import uuid

import pytest
from sqlalchemy import delete

from backend.core.database import get_sessionmaker
from backend.core.migrations import run_migrations
from backend.core.models import Conversation
from backend.features import chat
from backend.features.chat import router

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.mark.anyio
async def test_message_versioning_resubmit_regenerate_and_switch(monkeypatch):
    """Disposable DB-backed smoke test for the full message-versioning flow.

    It exercises the same persistence and conversation-loading path the app uses:
    normal send, resubmit-as-user-sibling, activate an older user version, regenerate
    an assistant sibling, then activate the older assistant version.
    """
    await run_migrations()

    replies = iter(
        [
            "reply to first prompt",
            "reply to edited prompt",
            "regenerated edited reply",
        ]
    )

    async def fake_stream_chat(*_args, **_kwargs):
        yield next(replies)

    async def fake_flags():
        return {
            "deep_research": False,
            "ontology": False,
            "capability_agent": False,
            "file_gen": False,
            "chat_code": False,
            "web_search": False,
            "mcp": False,
        }

    async def no_project_context(_project_id):
        return None

    async def fake_record_plan(*_args, **_kwargs):
        return "route-e2e"

    async def fake_record_outcome(*_args, **_kwargs):
        return None

    async def solo_owner():
        return None

    monkeypatch.setattr(chat.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(chat.team, "current_owner_id", solo_owner)
    monkeypatch.setattr(router.admin, "effective_flags", fake_flags)
    monkeypatch.setattr(router.project_store, "trusted_context", no_project_context)
    monkeypatch.setattr(router.route_telemetry, "record_plan", fake_record_plan)
    monkeypatch.setattr(router.route_telemetry, "record_outcome", fake_record_outcome)
    monkeypatch.setattr(router.sandbox, "image_ready", lambda: False)

    conv = await chat.create_conversation("openai/test", None)
    cid = conv["id"]
    try:
        events = [e async for e in chat.stream_reply(cid, "first prompt")]
        assert events[-1] == {"done": True}

        loaded = await chat.get_conversation(cid)
        assert [m["content"] for m in loaded["messages"]] == [
            "first prompt",
            "reply to first prompt",
        ]
        first_user_id = loaded["messages"][0]["id"]
        first_assistant_id = loaded["messages"][1]["id"]

        events = [e async for e in chat.stream_reply(cid, "edited prompt", sibling_of=first_user_id)]
        assert events[-1] == {"done": True}

        loaded = await chat.get_conversation(cid)
        assert [m["content"] for m in loaded["messages"]] == [
            "edited prompt",
            "reply to edited prompt",
        ]
        edited_user = loaded["messages"][0]
        edited_assistant_id = loaded["messages"][1]["id"]
        assert edited_user["versions"] == 2
        assert edited_user["version"] == 2
        assert edited_user["siblings"][0] == first_user_id
        assert edited_user["siblings"][1] == edited_user["id"]

        switched = await chat.set_active_version(cid, first_user_id)
        assert [m["content"] for m in switched["messages"]] == [
            "first prompt",
            "reply to first prompt",
        ]
        assert switched["messages"][0]["version"] == 1
        assert switched["messages"][1]["id"] == first_assistant_id

        switched = await chat.set_active_version(cid, edited_user["id"])
        assert [m["content"] for m in switched["messages"]] == [
            "edited prompt",
            "reply to edited prompt",
        ]

        events = [e async for e in chat.regenerate(cid)]
        assert events[-1] == {"done": True}

        loaded = await chat.get_conversation(cid)
        assert [m["content"] for m in loaded["messages"]] == [
            "edited prompt",
            "regenerated edited reply",
        ]
        regenerated_assistant = loaded["messages"][1]
        assert regenerated_assistant["versions"] == 2
        assert regenerated_assistant["version"] == 2
        assert regenerated_assistant["siblings"][0] == edited_assistant_id
        assert regenerated_assistant["siblings"][1] == regenerated_assistant["id"]

        switched = await chat.set_active_version(cid, edited_assistant_id)
        assert [m["content"] for m in switched["messages"]] == [
            "edited prompt",
            "reply to edited prompt",
        ]
        assert switched["messages"][1]["version"] == 1
    finally:
        async with get_sessionmaker()() as session:
            await session.execute(delete(Conversation).where(Conversation.id == uuid.UUID(cid)))
            await session.commit()
