from backend.features.chat import conversations


def test_reasoning_snapshot_round_trips_long_raw_thinking_verbatim():
    raw = ("  raw thought <tag> — line\n" * 8_500) + "final  "
    snapshot = {
        "thinking": raw,
        "trace": [{"stage": "Routing", "status": "done"}],
        "outer": None,
        "summary": None,
        "sources": None,
    }

    payload = conversations._dump_reasoning(snapshot)

    assert len(payload) > 200_000
    assert conversations._load_reasoning(payload) == snapshot

