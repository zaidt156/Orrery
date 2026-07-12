import pytest

from backend.core import appconfig
from backend.providers import accounts, ai


@pytest.mark.anyio
async def test_cloud_provider_boundary_redacts_messages_and_system_prompt(monkeypatch):
    seen = {}

    async def basic_privacy(_key, _default=None):
        return "basic"

    async def fake_stream(messages, system_prompt, model_id, effort):
        seen["messages"] = messages
        seen["system_prompt"] = system_prompt
        yield "ok"

    monkeypatch.setattr(appconfig, "get_setting", basic_privacy)
    monkeypatch.setattr(accounts, "stream_claude_plan", fake_stream)

    chunks = [chunk async for chunk in ai._stream_chat_once(
        "claude_plan/sonnet",
        [{"role": "user", "content": "ask user@example.com"}],
        "# TRUSTED CONTEXT\nOwner owner@example.com",
    )]

    assert chunks == ["ok"]
    assert seen["messages"][0]["content"] == "ask [email]"
    assert seen["system_prompt"] == "# TRUSTED CONTEXT\nOwner [email]"
