import asyncio
import sys
import uuid

import pytest

from backend.features import chat

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.mark.anyio
async def test_list_conversations_pages_newest_first(monkeypatch):
    from backend.core.database import get_sessionmaker
    from backend.core.migrations import run_migrations
    from backend.core.models import Conversation
    from backend.features import team

    async def solo():
        return None

    monkeypatch.setattr(team, "current_owner_id", solo)
    await run_migrations()

    created = []
    try:
        for index in range(3):
            conv = await chat.create_conversation(f"openai/page-test-{index}", None)
            created.append(conv["id"])

        first = await chat.list_conversations(limit=2, offset=0)
        assert len(first["conversations"]) == 2
        assert first["total"] >= 3
        assert first["limit"] == 2 and first["offset"] == 0

        second = await chat.list_conversations(limit=2, offset=2)
        ids_first = {c["id"] for c in first["conversations"]}
        ids_second = {c["id"] for c in second["conversations"]}
        assert not ids_first & ids_second  # pages never overlap

        # newest-first: the most recently created test chat leads the first page
        assert first["conversations"][0]["id"] == created[-1]

        # bounds are clamped, never an error
        clamped = await chat.list_conversations(limit=99999, offset=-5)
        assert clamped["limit"] == 500 and clamped["offset"] == 0
    finally:
        async with get_sessionmaker()() as s:
            for cid in created:
                row = await s.get(Conversation, uuid.UUID(cid))
                if row is not None:
                    await s.delete(row)
            await s.commit()
