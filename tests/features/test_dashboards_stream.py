"""The streaming dashboard build surfaces status + the model's reasoning, so a build shows what it
is doing instead of an opaque wait. Verifies the event contract for the success and error paths."""

import pytest

from backend.features import dashboards
from backend.providers import ai


_SPEC = '{"name":"Sales","widgets":[{"title":"Rows","type":"table","sql":"SELECT id FROM users","connection_id":"c1"}]}'


def _keys(events):
    return [next(iter(e)) for e in events]


@pytest.fixture
def stub_build(monkeypatch):
    async def fake_stream_chat(model, msgs, sysp, effort):
        yield ai.ReasoningDelta("Choosing a chart type…")
        yield _SPEC

    async def fake_schemas(conns):
        return "table users(id int)"

    async def fake_models(conns):
        return []

    async def fake_persist(name, spec, desc, model, conns, dropped):
        return {"id": "abc", "name": name, "widgets": spec["widgets"]}

    monkeypatch.setattr(dashboards.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(dashboards, "_schemas_block", fake_schemas)
    monkeypatch.setattr(dashboards.datamodels, "models_as_transforms", fake_models)
    monkeypatch.setattr(dashboards, "_persist_new_dashboard", fake_persist)
    monkeypatch.setattr(dashboards.skills, "skills_prompt", lambda q: "")


@pytest.mark.anyio
async def test_stream_emits_status_reasoning_and_the_finished_dashboard(stub_build):
    events = [e async for e in dashboards.create_dashboard_stream("openai/x", ["c1"], "sales")]

    keys = _keys(events)
    assert "status" in keys
    assert "reasoning_delta" in keys  # the model's own thinking is forwarded
    assert keys[-1] == "done"
    result = next(e["result"] for e in events if "result" in e)
    assert result["dashboard"]["id"] == "abc"
    assert result["dashboard"]["name"] == "Sales"


@pytest.mark.anyio
async def test_stream_surfaces_a_clean_error_frame_not_a_broken_stream(monkeypatch):
    async def bad_stream_chat(model, msgs, sysp, effort):
        yield "not json at all"  # the model returns no spec

    async def fake_schemas(conns):
        return "schema"

    monkeypatch.setattr(dashboards.ai, "stream_chat", bad_stream_chat)
    monkeypatch.setattr(dashboards, "_schemas_block", fake_schemas)
    monkeypatch.setattr(dashboards.skills, "skills_prompt", lambda q: "")

    events = [e async for e in dashboards.create_dashboard_stream("openai/x", ["c1"], "sales")]

    keys = _keys(events)
    assert "error" in keys
    assert keys[-1] == "done"
    assert not any("result" in e for e in events)
