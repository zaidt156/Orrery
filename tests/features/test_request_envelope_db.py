"""The stored side of the exact-request invariant (ADR-005 slice 1).

The unit tests prove the digest logic; these prove it survives PostgreSQL - that what comes back out
of the database still reconstructs to the request that went in.
"""
import asyncio
import sys
import uuid

import pytest
from sqlalchemy import select

# Marked at module scope: these exercise real persistence, so they need the PostgreSQL that
# `docker compose up -d` provides. The cross-platform CI job runs `-m "not db"`; the Linux
# job provides a pgvector service and requires them.
pytestmark = pytest.mark.db

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _migrated():
    from backend.core.migrations import run_migrations
    asyncio.run(run_migrations())


async def _conversation():
    from backend.core.database import get_sessionmaker
    from backend.core.models import Conversation

    async with get_sessionmaker()() as s:
        row = Conversation(title="envelope", model="openai/test")
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row.id


async def _drop(conversation_id):
    from backend.core.database import get_sessionmaker
    from backend.core.models import Conversation

    async with get_sessionmaker()() as s:
        row = await s.get(Conversation, conversation_id)
        if row is not None:
            await s.delete(row)
            await s.commit()


def _frozen(**overrides):
    from backend.providers import envelope

    base = dict(
        provider="openai", model="openai/gpt-4o", effort="high", effort_defaulted=False,
        privacy_mode="basic", system_prompt="Be precise.",
        messages=[{"role": "user", "content": "what changed?"}], tool_catalog=["web_search"],
    )
    base.update(overrides)
    return envelope.RequestEnvelope(**base)


@pytest.mark.anyio
async def test_a_captured_request_still_proves_itself_after_a_round_trip():
    from backend.core.database import get_sessionmaker
    from backend.core.models import ModelRequestEnvelope
    from backend.providers import envelope

    cid = await _conversation()
    try:
        token = envelope.set_recording(envelope.RequestRecording(
            surface="chat", owner_id=None, conversation_id=cid, turn_id=uuid.uuid4(),
            tool_catalog=["web_search"],
        ))
        try:
            frozen = _frozen()
            row_id = await envelope.capture(frozen)
        finally:
            envelope.reset_recording(token)

        assert row_id is not None
        async with get_sessionmaker()() as s:
            row = await s.get(ModelRequestEnvelope, row_id)
            assert row.surface == "chat" and row.body_retained
            assert row.body_digest == frozen.digest()
            # the point of the slice: rebuild from storage and show it is the same request
            assert envelope.proves(row.body, frozen)
            # and a different request must not pass against that same record
            assert not envelope.proves(row.body, _frozen(effort="low"))
    finally:
        await _drop(cid)


@pytest.mark.anyio
async def test_request_evidence_is_deleted_with_its_conversation():
    """Owner-private evidence, not an archive: retention follows the parent."""
    from backend.core.database import get_sessionmaker
    from backend.core.models import ModelRequestEnvelope
    from backend.providers import envelope

    cid = await _conversation()
    token = envelope.set_recording(envelope.RequestRecording(
        surface="chat", owner_id=None, conversation_id=cid, turn_id=uuid.uuid4(),
    ))
    try:
        row_id = await envelope.capture(_frozen())
    finally:
        envelope.reset_recording(token)

    await _drop(cid)

    async with get_sessionmaker()() as s:
        left = (await s.execute(select(ModelRequestEnvelope).where(
            ModelRequestEnvelope.id == row_id
        ))).scalars().all()
        assert left == []
