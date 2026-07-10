from backend.features import events
from backend.features.reasoning_trace import ThinkStream


def test_stream_event_helpers_preserve_legacy_shapes():
    assert events.delta("hello") == {"delta": "hello"}
    assert events.status("") == {"status": ""}
    assert events.error("bad") == {"error": "bad"}
    assert events.done() == {"done": True}
    assert events.resumed() == {"resumed": True}
    assert events.title("Chat") == {"title": "Chat"}
    assert events.message_id("mid") == {"message_id": "mid"}
    assert events.sources(["s1"]) == {"sources": ["s1"]}
    assert events.files([{"name": "a.pdf"}]) == {"files": [{"name": "a.pdf"}]}
    assert events.artifact({"kind": "svg"}) == {"artifact": {"kind": "svg"}}
    assert events.project({"id": "p1"}) == {"project": {"id": "p1"}}
    assert events.result({"ok": True}) == {"result": {"ok": True}}
    assert events.svg("<svg />") == {"svg": "<svg />"}
    assert events.usage({"total": 1}) == {"usage": {"total": 1}}
    assert events.reasoning_delta("thinking") == {"reasoning_delta": "thinking"}


def test_message_usage_and_missing_key_events_are_centralized():
    assert events.message_usage(None, 12, False) == {
        "message_usage": {"in": 0, "out": 12, "pricing_known": False}
    }
    assert events.missing_key("openai") == {"error": "No API key for openai. Add it in Settings."}


def test_think_stream_streams_raw_thoughts_to_the_panel_by_default():
    """Raw model thoughts are the user's to see: inline <think> content leaves the ANSWER but
    streams to the local reasoning panel as reasoning_delta (click-to-expand in the UI)."""
    stream = ThinkStream()

    answer, emitted = stream.feed("<think>private scratchpad</think>Hello")
    tail, tail_events = stream.finish()

    assert answer + tail == "Hello"  # the visible answer never contains the thinking
    deltas = "".join(e["reasoning_delta"] for e in emitted + tail_events if "reasoning_delta" in e)
    assert deltas == "private scratchpad"
    assert stream.stats.seen


def test_think_stream_provider_reasoning_streams_by_default():
    stream = ThinkStream()

    assert stream.feed_reasoning("model thought") == [{"reasoning_delta": "model thought"}]


def test_think_stream_can_still_suppress_raw_reasoning():
    stream = ThinkStream(emit_raw=False)

    answer, emitted = stream.feed("<think>hidden</think>Hi")
    tail, tail_events = stream.finish()
    assert emitted == [] and tail_events == []
    assert stream.feed_reasoning("x") == []
    assert answer + tail == "Hi"
