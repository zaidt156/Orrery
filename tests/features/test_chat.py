import uuid

import pytest

from backend.features import chat


def test_title_from():
    assert chat._title_from("hello world this is a fairly long opening line")
    assert chat._title_from("") == "New chat"


def test_build_user_content_text_only_is_string():
    assert chat._build_user_content("hi", []) == "hi"


def test_build_user_content_image_returns_blocks():
    atts = [{"kind": "image", "name": "a.png", "content": "data:image/png;base64,AAAA"}]
    out = chat._build_user_content("look at this", atts)
    assert isinstance(out, list)
    assert any(b.get("type") == "image_url" for b in out)
    assert any(b.get("type") == "text" for b in out)


def test_build_user_content_text_file_inlined():
    atts = [{"kind": "text", "name": "notes.txt", "content": "FILEBODY123"}]
    out = chat._build_user_content("summarize", atts)
    assert isinstance(out, str)
    assert "FILEBODY123" in out and "notes.txt" in out


def test_build_user_content_bad_pdf_gives_placeholder():
    atts = [{"kind": "pdf", "name": "x.pdf", "content": "data:application/pdf;base64,bm90YXBkZg=="}]
    out = chat._build_user_content("", atts)
    assert isinstance(out, str)
    assert "x.pdf (PDF)" in out


def test_db_content_records_attachment_note():
    atts = [{"kind": "image", "name": "a.png", "content": "x"}]
    assert "📎" in chat._db_content("hi", atts)
    assert chat._db_content("hi", []) == "hi"


def test_context_window_missing_value_defaults_to_one_million():
    assert chat._effective_context_window(None) == 1_000_000


def test_message_artifacts_ignores_corrupt_or_non_list_json():
    assert chat._message_artifacts(None) == []
    assert chat._message_artifacts("{bad") == []
    assert chat._message_artifacts('{"kind":"svg"}') == []
    assert chat._message_artifacts('[{"kind":"svg"}]') == [{"kind": "svg"}]


def test_context_window_drops_oldest_complete_turns():
    messages = [
        {"role": "user", "content": "a" * 4000},
        {"role": "assistant", "content": "b" * 4000},
        {"role": "user", "content": "latest question"},
    ]

    limited = chat._limit_messages(messages, 2048)

    assert limited == [{"role": "user", "content": "latest question"}]


def test_context_window_always_keeps_latest_turn():
    latest = {"role": "user", "content": "x" * 20000}

    assert chat._limit_messages([latest], 2048) == [latest]


def test_context_window_counts_images_without_counting_base64_bytes():
    image = {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + "A" * 50000},
            }
        ],
    }

    assert chat._content_token_estimate(image["content"]) == 1024


@pytest.mark.anyio
async def test_generate_adds_markdown_format_instructions(monkeypatch):
    seen = {}

    async def fake_stream_chat(model, messages, system_prompt=None, effort=None, usage_out=None):
        seen["model"] = model
        seen["messages"] = messages
        seen["system_prompt"] = system_prompt
        seen["effort"] = effort
        yield "ok"

    async def fake_persist_assistant(*args, **kwargs):
        return None

    monkeypatch.setattr(chat.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(chat, "_persist_assistant", fake_persist_assistant)

    events = []
    async for event in chat._generate(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "openai/test",
        "Be concise.",
        [{"role": "user", "content": "show code"}],
        "high",
    ):
        events.append(event)

    assert "GitHub-flavored Markdown" in seen["system_prompt"]
    assert "fenced code blocks" in seen["system_prompt"]
    assert "Be concise." in seen["system_prompt"]
    assert seen["effort"] == "high"
    # the answer streams as deltas; raw model reasoning is never streamed verbatim (only condensed
    # reasoning_event steps are allowed, and this fake stream emits none)
    assert {"delta": "ok"} in events
    assert not any("reasoning" in e and "reasoning_event" not in e and "reasoning_summary" not in e for e in events)
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_generate_returns_saved_message_id(monkeypatch):
    async def fake_stream_chat(*args, **kwargs):
        yield "reply"

    async def fake_persist_assistant(*args, **kwargs):
        return "00000000-0000-0000-0000-000000000099"

    monkeypatch.setattr(chat.ai, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(chat, "_persist_assistant", fake_persist_assistant)

    events = [
        event
        async for event in chat._generate(
            uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "openai/test",
            None,
            [{"role": "user", "content": "hello"}],
        )
    ]

    assert {"message_id": "00000000-0000-0000-0000-000000000099"} in events
