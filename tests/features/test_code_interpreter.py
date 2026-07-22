import pytest

from backend.features import code_interpreter


class FakeTrace:
    def step(self, stage, detail, **kwargs):
        return {"trace": {"stage": stage, "detail": detail, **kwargs}}

    def error(self, stage, detail):
        return {"trace": {"stage": stage, "detail": detail, "status": "error"}}


@pytest.mark.anyio
async def test_tool_block_runs_through_registry_and_persists_final_answer(monkeypatch):
    calls = []
    persisted = {}

    async def fake_stream_chat(model, work, formatted_prompt=None, effort=None, usage_out=None):
        if len(work) == 1:
            yield '```orrery-tool\n{"tool":"web_search","args":{"query":"capability loop"}}\n```'
        else:
            yield "Final answer from observation."

    async def fake_run_tool(key, args=None, *, allowed=None, approval_id=None):
        calls.append((key, args, allowed))
        return {"ok": True, "results": [{"title": "Result", "url": "https://example.com", "snippet": "Safe data"}]}

    async def persist(text, artifacts):
        persisted["text"] = text
        persisted["artifacts"] = artifacts
        return "m1"

    monkeypatch.setattr(code_interpreter.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(code_interpreter.tool_registry, "run_tool", fake_run_tool)

    events = [
        event
        async for event in code_interpreter.run(
            "openai/test",
            "system",
            [{"role": "user", "content": "search this"}],
            None,
            trace=FakeTrace(),
            persist=persist,
            allowed_tools={"web_search"},
        )
    ]

    assert calls == [("web_search", {"query": "capability loop"}, {"web_search"})]
    assert persisted["text"] == "Final answer from observation."
    assert persisted["artifacts"] is None
    assert any(event.get("message_id") == "m1" for event in events)
