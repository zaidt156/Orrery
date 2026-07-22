import uuid
from types import SimpleNamespace

import pytest

from backend.features import chat
from backend.features.chat import router


class _Result:
    def __init__(self, rows=(), scalar=None):
        self._rows = list(rows)
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._scalar


class _HistorySession:
    def __init__(self, content_by_id, latest_user_context):
        self._content_by_id = content_by_id
        self._latest_user_context = latest_user_context

    async def execute(self, _statement):
        return _Result(
            (
                SimpleNamespace(id=message_id, content=content)
                for message_id, content in self._content_by_id.items()
            ),
            scalar=self._latest_user_context,
        )


def test_context_budget_keeps_100_short_messages():
    messages = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"short message {index:03d}",
        }
        for index in range(100)
    ]

    assert chat._limit_messages(messages, 131_072) == messages


@pytest.mark.anyio
async def test_history_hydration_keeps_about_100_short_turns():
    """The context window, not a fixed row count, decides when older chat turns are dropped."""
    path = []
    content_by_id = {}
    for turn in range(101):
        for role in ("user", "assistant"):
            message_id = uuid.uuid4()
            content = (
                "turn 000; remember context-marker-000"
                if turn == 0 and role == "user"
                else f"{role} turn {turn:03d}"
            )
            path.append(SimpleNamespace(id=message_id, role=role))
            content_by_id[message_id] = content

    session = _HistorySession(content_by_id, "user turn 100")

    messages = await router._hydrate_history(session, path)

    assert len(messages) == 202
    assert messages[0] == {
        "role": "user",
        "content": "turn 000; remember context-marker-000",
    }
    assert messages[-1] == {"role": "assistant", "content": "assistant turn 100"}


@pytest.mark.anyio
async def test_history_hydration_stays_bounded_for_long_messages():
    path = []
    content_by_id = {}
    for turn in range(201):
        for role in ("user", "assistant"):
            message_id = uuid.uuid4()
            path.append(SimpleNamespace(id=message_id, role=role))
            content_by_id[message_id] = f"{role} turn {turn:03d}: " + ("x" * 4000)

    session = _HistorySession(content_by_id, "x" * 4000)

    messages = await router._hydrate_history(session, path, context_window=2048)

    assert len(messages) < len(path)
    assert messages[0]["role"] == "user"
    assert messages[-1]["content"].startswith("assistant turn 200:")
