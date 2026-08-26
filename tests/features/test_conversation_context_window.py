"""A chat's context window, and the clamp that could only ever shrink it.

The window stored on a conversation is the budget `_limit_messages` trims history against, and it is
clamped to the model's real maximum on every update. That clamp was written as `min(stored, max)`,
which is right in one direction and a trap in the other: when the *maximum* turns out to have been
understated, every conversation created under the old number keeps it for good.

That is not hypothetical. Orrery reported 131,072 for Gemini 3.7 Flash (really 1,048,576) and 32,768
for every local model until that was fixed — so the fix corrected new chats and left every existing
one quietly trimming to a fraction of what its model can hold.
"""
import asyncio
import sys
import uuid

import pytest

from backend.features import chat
from backend.providers import ai

pytestmark = pytest.mark.db

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _delete(conversation_id):
    from backend.core.database import get_sessionmaker
    from backend.core.models import Conversation

    async with get_sessionmaker()() as s:
        row = await s.get(Conversation, uuid.UUID(conversation_id))
        if row is not None:
            await s.delete(row)
            await s.commit()


@pytest.mark.anyio
async def test_a_chat_created_under_an_understated_maximum_recovers(monkeypatch):
    """The regression: a window stored while the model's maximum was wrong must widen once the
    maximum is right. A `min()` alone can never do that."""
    from backend.core.migrations import run_migrations

    await run_migrations()

    # The world as it was: Gemini 3.7 Flash reported as an eighth of its real size.
    monkeypatch.setattr(ai, "model_context_window", lambda _m: 131_072)
    created = await chat.create_conversation(
        "gemini/gemini-3.7-flash", None, context_window=1_000_000,
    )
    assert created["context_window"] == 131_072  # clamped, correctly, to what we believed then

    # The world after the fix.
    monkeypatch.setattr(ai, "model_context_window", lambda _m: 1_048_576)
    updated = await chat.update_conversation(created["id"], model="gemini/gemini-3.7-flash")

    try:
        # Back to what was actually asked for — not silently upgraded past it. The request was
        # 1,000,000; the model can now hold 1,048,576; the chat uses the smaller of the two.
        assert updated["context_window"] == 1_000_000, (
            "the chat is still trimming to the old, wrong maximum"
        )
    finally:
        await _delete(created["id"])


@pytest.mark.anyio
async def test_a_window_the_user_chose_below_the_maximum_is_left_alone(monkeypatch):
    """Widening must not overwrite a deliberate choice. Someone who set 64K to keep a model fast
    and cheap has not asked for a megabyte."""
    from backend.core.migrations import run_migrations

    await run_migrations()
    monkeypatch.setattr(ai, "model_context_window", lambda _m: 1_048_576)

    created = await chat.create_conversation(
        "gemini/gemini-3.7-flash", None, context_window=65_536,
    )
    updated = await chat.update_conversation(created["id"], model="gemini/gemini-3.7-flash")

    try:
        assert updated["context_window"] == 65_536
    finally:
        await _delete(created["id"])


@pytest.mark.anyio
async def test_a_window_above_the_new_models_maximum_still_narrows(monkeypatch):
    """The clamp's original job has to survive: switching to a smaller model must not leave a
    conversation asking for more context than that model has, which the provider would reject."""
    from backend.core.migrations import run_migrations

    await run_migrations()
    monkeypatch.setattr(ai, "model_context_window", lambda _m: 1_048_576)
    created = await chat.create_conversation(
        "gemini/gemini-3.7-flash", None, context_window=1_000_000,
    )

    monkeypatch.setattr(ai, "model_context_window", lambda _m: 200_000)
    updated = await chat.update_conversation(created["id"], model="anthropic/claude-haiku-4-5")

    try:
        assert updated["context_window"] == 200_000
    finally:
        await _delete(created["id"])


@pytest.mark.anyio
async def test_switching_to_a_smaller_model_and_back_does_not_cost_the_window(monkeypatch):
    """The other half of the same bug. Trying Haiku for one reply and switching back used to leave
    the chat permanently capped at 200K, because the clamp had overwritten the larger request and
    nothing remembered it."""
    from backend.core.migrations import run_migrations

    await run_migrations()
    windows = {"anthropic/claude-opus-5": 1_000_000, "anthropic/claude-haiku-4-5": 200_000}
    monkeypatch.setattr(ai, "model_context_window", lambda m: windows[m])

    created = await chat.create_conversation(
        "anthropic/claude-opus-5", None, context_window=1_000_000,
    )
    try:
        assert created["context_window"] == 1_000_000

        narrowed = await chat.update_conversation(created["id"], model="anthropic/claude-haiku-4-5")
        assert narrowed["context_window"] == 200_000        # capped while Haiku is serving it

        restored = await chat.update_conversation(created["id"], model="anthropic/claude-opus-5")
        assert restored["context_window"] == 1_000_000, "the window did not come back"
    finally:
        await _delete(created["id"])
