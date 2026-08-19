"""Evidence invariants that only PostgreSQL can show (ADR-005 slice 1)."""
import asyncio
import sys

import pytest

# Marked at module scope: these exercise real persistence, so they need the PostgreSQL that
# `docker compose up -d` provides. The cross-platform CI job runs `-m "not db"`; the Linux
# job provides a pgvector service and requires them.
pytestmark = pytest.mark.db

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_a_solo_owner_is_not_mistaken_for_a_missing_parent():
    """Regression: a NULL owner is the default (solo mode), not evidence of a missing parent.

    The workflow lookup used `scalar_one_or_none()`, which returns None both for "no such run" and
    for "found it, owner is NULL" - so every automation tool call in a single-user Orrery was
    refused with `evidence_unavailable`. Each surface is checked here because the same trap applies
    to all three.
    """
    import uuid

    from backend.core.database import get_sessionmaker
    from backend.core.migrations import run_migrations
    from backend.core.models import Conversation, Workflow, WorkflowRun
    from backend.tools import lifecycle

    await run_migrations()
    async with get_sessionmaker()() as s:
        conv = Conversation(title="solo", model="openai/test")           # owner_id NULL
        wf = Workflow(name="solo", spec="{}")                            # owner_id NULL
        s.add_all([conv, wf])
        await s.commit()
        await s.refresh(conv)
        await s.refresh(wf)
        run = WorkflowRun(workflow_id=wf.id)
        s.add(run)
        await s.commit()
        await s.refresh(run)
        conv_id, wf_id, run_id = conv.id, wf.id, run.id

    try:
        async with get_sessionmaker()() as s:
            chat = lifecycle.ToolExecutionIdentity(
                surface="chat", owner_id=None, conversation_id=conv_id, turn_id=uuid.uuid4())
            automation = lifecycle.ToolExecutionIdentity(
                surface="automation", owner_id=None, workflow_run_id=run_id, turn_id=uuid.uuid4())

            assert await lifecycle._parent_owner(s, chat) is None
            assert await lifecycle._parent_owner(s, automation) is None

            # and a parent that really is absent still reports missing
            absent = lifecycle.ToolExecutionIdentity(
                surface="automation", owner_id=None, workflow_run_id=uuid.uuid4(),
                turn_id=uuid.uuid4())
            assert await lifecycle._parent_owner(s, absent) is lifecycle._MISSING
    finally:
        async with get_sessionmaker()() as s:
            for model, ident in ((Workflow, wf_id), (Conversation, conv_id)):
                row = await s.get(model, ident)
                if row is not None:
                    await s.delete(row)
            await s.commit()
