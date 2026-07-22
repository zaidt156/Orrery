import pytest

from backend.features import capabilities, code_interpreter


@pytest.mark.anyio
async def test_catalog_describes_purpose_and_grounds_resource_ids(monkeypatch):
    async def fake_conns():
        return [{"id": "conn-1234-5678", "name": "warehouse", "reachable": True},
                {"id": "conn-dead", "name": "down", "reachable": False}]

    async def fake_boards():
        return [{"id": "dash-9999", "name": "Sales"}]

    from backend.features import data, dashboards
    monkeypatch.setattr(data, "list_connections", fake_conns)
    monkeypatch.setattr(dashboards, "list_dashboards", fake_boards)

    text = await capabilities.tool_catalog({"file_generate", "db_query", "dashboard_refresh"})

    # purpose (not just the label) is present so the model chooses by intent
    assert "downloadable FILE" in text and "LaTeX/TeX" in text
    assert "read-only SELECT" in text
    # only reachable connections are offered, with their real id; the [writes] flag is surfaced
    assert "warehouse = conn-1234-5678" in text
    assert "conn-dead" not in text  # the unreachable connection is not offered
    assert "Sales = dash-9999" in text
    assert "[writes files/remote state]" in text


@pytest.mark.anyio
async def test_catalog_empty_when_only_dedicated_block_tools_allowed():
    # run_python/run_shell/mcp_call use their own fenced blocks, not the orrery-tool catalog
    assert await capabilities.tool_catalog({"run_python", "run_shell", "mcp_call"}) == ""
    assert await capabilities.tool_catalog(set()) == ""


class _FakeTrace:
    def step(self, stage, detail, **kwargs):
        return {"trace": {"stage": stage, "detail": detail, **kwargs}}

    def error(self, stage, detail):
        return {"trace": {"stage": stage, "detail": detail, "status": "error"}}


@pytest.mark.anyio
async def test_model_self_selects_file_generate_and_gets_context_injected(monkeypatch):
    """The capability loop: the model picks file_generate from the catalog and the backend injects
    the current model/context the tool needs, then feeds the result back."""
    seen = {}

    async def fake_stream_chat(model, work, formatted_prompt=None, effort=None, usage_out=None):
        if len(work) == 1:
            yield '```orrery-tool\n{"tool":"file_generate","args":{"request":"a resume as LaTeX"}}\n```'
        else:
            yield "Here is your resume."

    async def fake_run_tool(key, args=None, *, allowed=None, approval_id=None):
        seen["key"] = key
        seen["args"] = args
        return {"ok": True, "summary": "Built resume.tex", "files": ["resume.tex"],
                "artifacts": [{"kind": "file", "id": "f1", "name": "resume.tex"}]}

    async def persist(text, artifacts):
        seen["artifacts"] = artifacts
        return "m1"

    monkeypatch.setattr(code_interpreter.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(code_interpreter.tool_registry, "run_tool", fake_run_tool)

    events = [
        event
        async for event in code_interpreter.run(
            "anthropic/claude-fable-5",
            "system",
            [{"role": "user", "content": "make me a resume in latex"}],
            None,
            trace=_FakeTrace(),
            persist=persist,
            allowed_tools={"file_generate"},
            system_prompt="be concise",
        )
    ]

    assert seen["key"] == "file_generate"
    # the loop injected the current model so file_generate can run without the model guessing it
    assert seen["args"]["model"] == "anthropic/claude-fable-5"
    assert seen["args"]["request"] == "a resume as LaTeX"
    assert seen["artifacts"] == [{"kind": "file", "id": "f1", "name": "resume.tex"}]
    assert any(e.get("message_id") == "m1" for e in events)
