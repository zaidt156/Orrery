from backend.features import events


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
