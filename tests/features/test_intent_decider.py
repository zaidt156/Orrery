import pytest

from backend.features import taskrouter


def _fake_stream(text):
    async def stream(model, messages, system_prompt=None, effort=None, usage_out=None):
        yield text
    return stream


def test_parse_decision_tolerates_wrapping_and_rejects_junk():
    assert taskrouter._parse_decision('sure: {"route": "chat", "format": null}')["route"] == "chat"
    assert taskrouter._parse_decision('{"route": "file", "format": "pdf"}') == {"route": "file", "format": "pdf"}
    assert taskrouter._parse_decision("no json") is None
    assert taskrouter._parse_decision('{"route": "nonsense"}') is None


@pytest.mark.anyio
async def test_plain_chat_never_calls_the_model(monkeypatch):
    from backend.providers import ai

    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
        yield ""

    monkeypatch.setattr(ai, "stream_chat", boom)
    plan = await taskrouter.decide("what is the capital of France", model="openai/x", recent_messages=[])
    assert plan.route == "chat"
    assert called["n"] == 0  # heuristic-chat short-circuits — no model latency on ordinary turns


@pytest.mark.anyio
async def test_model_overrides_a_false_generative_route_to_chat(monkeypatch):
    from backend.providers import ai

    # heuristic sees the inherited "sing a song" text → file(audio); the model, judging the TRUE
    # current message (a calculation), returns chat and wins.
    monkeypatch.setattr(ai, "stream_chat", _fake_stream('{"route": "chat", "format": null}'))
    plan = await taskrouter.decide(
        "sing me a song\nWhats 12598653 + 1836493",
        current_message="Whats 12598653 + 1836493",
        model="openai/x",
        recent_messages=[{"role": "user", "content": "sing me a song"}],
    )
    assert plan.route == "chat"


@pytest.mark.anyio
async def test_model_confirms_a_real_file_request(monkeypatch):
    from backend.providers import ai

    monkeypatch.setattr(ai, "stream_chat", _fake_stream('{"route": "file", "format": "pdf"}'))
    plan = await taskrouter.decide("create a PDF invoice for $500", model="openai/x", recent_messages=[])
    assert plan.route == "file"
    assert plan.output_mode == "file"


@pytest.mark.anyio
async def test_model_failure_falls_back_to_heuristic(monkeypatch):
    from backend.providers import ai

    async def failing(*a, **k):
        raise RuntimeError("limit hit")
        yield  # pragma: no cover

    monkeypatch.setattr(ai, "stream_chat", failing)
    # heuristic routes this to file(audio); with the model down we keep that rather than break
    plan = await taskrouter.decide("make me an mp3 of ocean sounds", model="openai/x", recent_messages=[])
    assert plan.route == "file"


@pytest.mark.anyio
async def test_decider_disabled_uses_heuristic_only(monkeypatch):
    from backend.core.config import settings
    from backend.providers import ai

    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
        yield ""

    monkeypatch.setattr(ai, "stream_chat", boom)
    monkeypatch.setattr(settings, "model_intent_decider", False)
    plan = await taskrouter.decide("create a PDF invoice", model="openai/x", recent_messages=[])
    assert plan.route == "file"
    assert called["n"] == 0
