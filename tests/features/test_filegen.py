import pytest

from backend.features import filegen, sandbox


def test_quality_effort_promotes_file_jobs():
    assert filegen.quality_effort("openai/gpt-test", None) == "high"
    assert filegen.quality_effort("openai/gpt-test", "low") == "high"
    assert filegen.quality_effort("claude_plan/opus", None) == "xhigh"
    assert filegen.quality_effort("openai/gpt-test", "xhigh") == "xhigh"


@pytest.mark.anyio
async def test_filegen_run_uses_quality_effort_and_production_prompt(monkeypatch):
    captured = {}

    async def fake_stream_chat(model, messages, system_prompt=None, effort=None, usage_out=None):
        captured["model"] = model
        captured["messages"] = messages
        captured["system_prompt"] = system_prompt
        captured["effort"] = effort
        yield "```python\nprint('ok')\n```"

    def fake_run_code(code):
        captured["code"] = code
        return sandbox.SandboxResult(
            ok=True,
            stdout="deck.pptx",
            stderr="",
            exit_code=0,
            timed_out=False,
            files=[sandbox.SandboxFile("deck.pptx", b"PK-test")],
        )

    monkeypatch.setattr(filegen.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(filegen.skills, "skills_prompt", lambda _request: "SKILL BLOCK")
    monkeypatch.setattr(filegen.sandbox, "run_code", fake_run_code)

    events = [
        event
        async for event in filegen.run(
            "openai/gpt-test",
            "Create a polished PowerPoint about Planet Earth",
            "Use clear language.",
            "low",
        )
    ]

    assert events[0]["status"] == "Creating the file structure…"
    assert captured["effort"] == "high"
    assert "Quality bar" in captured["system_prompt"]
    assert "PowerPoint" in captured["system_prompt"]
    assert "SKILL BLOCK" in captured["system_prompt"]
    assert "Use clear language." in captured["system_prompt"]
    assert captured["code"].startswith("import os as _os")
    assert events[-1]["result"]["ok"] is True
