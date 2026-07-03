import asyncio
import base64
import contextlib
import io
import uuid

import pytest

from backend.features import chat, events as stream_events


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


def test_build_user_content_docx_file_inlined():
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("DOCBODY123")
    doc.save(buf)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    atts = [{"kind": "file", "name": "notes.docx", "content": f"data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{encoded}"}]

    out = chat._build_user_content("summarize", atts)

    assert isinstance(out, str)
    assert "notes.docx" in out
    assert "DOCBODY123" in out


def test_office_attachments_are_indexable_for_chat_memory():
    assert chat._is_indexable_attachment({"kind": "file", "name": "notes.docx", "content": "x"})
    assert chat._is_indexable_attachment({"kind": "image", "name": "photo.png", "content": "x"}) is False


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
    monkeypatch.setattr(chat.persistence, "_persist_assistant", fake_persist_assistant)

    events = []
    async for event in chat._generate(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "openai/test",
        "Be concise.",
        [{"role": "user", "content": "show code"}],
        "high",
        trusted_context="Project: Acme rollout\n\nStanding project instructions:\nUse the Acme terminology.",
    ):
        events.append(event)

    assert "GitHub-flavored Markdown" in seen["system_prompt"]
    assert "fenced code blocks" in seen["system_prompt"]
    assert "Be concise." in seen["system_prompt"]
    assert "Project: Acme rollout" in seen["system_prompt"]
    assert "TRUSTED CONTEXT" in seen["system_prompt"]
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
    monkeypatch.setattr(chat.persistence, "_persist_assistant", fake_persist_assistant)

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


def _fake_turn(*, model: str = "openai/test", effort: str | None = None) -> chat._TurnContext:
    return chat._TurnContext(
        model=model,
        system_prompt=None,
        effort=effort,
        project_id=None,
        context_window=chat.DEFAULT_CONTEXT_WINDOW,
        messages=[{"role": "user", "content": "hello"}],
        title="Test chat",
    )


@pytest.mark.anyio
async def test_stream_reply_dispatches_image_route(monkeypatch):
    calls = []

    async def fake_prepare_turn(*args, **kwargs):
        return _fake_turn()

    async def fake_trusted_context(project_id):
        return None

    async def fake_record_plan(*args, **kwargs):
        return "route-1"

    async def fake_route_image(*args, **kwargs):
        calls.append("image")
        yield {"artifact": {"kind": "svg"}}
        yield {"done": True}

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.project_store, "trusted_context", fake_trusted_context)
    monkeypatch.setattr(chat.route_telemetry, "record_plan", fake_record_plan)
    monkeypatch.setattr(chat.router, "_route_image", fake_route_image)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "Draw a clean logo for a data observatory",
        )
    ]

    assert calls == ["image"]
    assert {"title": "Test chat"} in events
    assert {"artifact": {"kind": "svg"}} in events
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_stream_reply_file_route_can_fall_back_to_model_reply(monkeypatch):
    calls = []

    async def fake_prepare_turn(*args, **kwargs):
        return _fake_turn()

    async def fake_trusted_context(project_id):
        return None

    async def fake_record_plan(*args, **kwargs):
        return "route-1"

    async def fake_route_file(*args, **kwargs):
        calls.append("file")
        state = args[-1]
        state.handled = False
        yield {"status": ""}

    async def fake_route_model_reply(*args, **kwargs):
        calls.append("model")
        yield {"delta": "fallback answer"}
        yield {"done": True}

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.project_store, "trusted_context", fake_trusted_context)
    monkeypatch.setattr(chat.route_telemetry, "record_plan", fake_record_plan)
    monkeypatch.setattr(chat.router, "_route_file", fake_route_file)
    monkeypatch.setattr(chat.router, "_route_model_reply", fake_route_model_reply)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "Create a PDF report about revenue",
        )
    ]

    assert calls == ["file", "model"]
    assert {"status": ""} in events
    assert {"delta": "fallback answer"} in events
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_stream_reply_file_route_sandbox_miss_uses_docspec(monkeypatch):
    calls = []
    outcomes = []

    async def fake_prepare_turn(*args, **kwargs):
        return _fake_turn()

    async def fake_trusted_context(project_id):
        return None

    async def fake_record_plan(*args, **kwargs):
        return "route-1"

    async def fake_record_outcome(route_id, outcome, detail=None):
        outcomes.append((route_id, outcome, detail))

    async def fake_filegen_run(*args, **kwargs):
        calls.append("sandbox")
        yield stream_events.result({"ok": False, "error": "sandbox validation failed"})

    async def fake_deliver_docspec(*args, **kwargs):
        calls.append("docspec")
        yield stream_events.delta("Here is your file.")
        yield stream_events.files([{"kind": "file", "name": "revenue.pdf"}])
        yield stream_events.done()

    async def fake_route_model_reply(*args, **kwargs):
        calls.append("model")
        yield stream_events.delta("plain fallback")
        yield stream_events.done()

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.project_store, "trusted_context", fake_trusted_context)
    monkeypatch.setattr(chat.route_telemetry, "record_plan", fake_record_plan)
    monkeypatch.setattr(chat.route_telemetry, "record_outcome", fake_record_outcome)
    monkeypatch.setattr(chat.sandbox, "image_ready", lambda: True)
    monkeypatch.setattr(chat.filegen, "run", fake_filegen_run)
    monkeypatch.setattr(chat.router, "_deliver_docspec", fake_deliver_docspec)
    monkeypatch.setattr(chat.router, "_route_model_reply", fake_route_model_reply)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "Create a PDF report about revenue",
        )
    ]

    assert calls == ["sandbox", "docspec"]
    assert {"files": [{"kind": "file", "name": "revenue.pdf"}]} in events
    assert events[-1] == stream_events.done()
    assert ("route-1", "sandbox_fallback", None) in outcomes


@pytest.mark.anyio
async def test_stream_reply_file_route_full_fallback_to_model_reply(monkeypatch):
    calls = []
    outcomes = []

    async def fake_prepare_turn(*args, **kwargs):
        return _fake_turn()

    async def fake_trusted_context(project_id):
        return None

    async def fake_record_plan(*args, **kwargs):
        return "route-1"

    async def fake_record_outcome(route_id, outcome, detail=None):
        outcomes.append((route_id, outcome, detail))

    async def fake_filegen_run(*args, **kwargs):
        calls.append("sandbox")
        yield stream_events.result({"ok": False, "error": "sandbox produced no files"})

    async def fake_deliver_docspec(*args, **kwargs):
        calls.append("docspec")
        return
        yield

    async def fake_route_model_reply(*args, **kwargs):
        calls.append("model")
        yield stream_events.delta("fallback answer")
        yield stream_events.done()

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.project_store, "trusted_context", fake_trusted_context)
    monkeypatch.setattr(chat.route_telemetry, "record_plan", fake_record_plan)
    monkeypatch.setattr(chat.route_telemetry, "record_outcome", fake_record_outcome)
    monkeypatch.setattr(chat.sandbox, "image_ready", lambda: True)
    monkeypatch.setattr(chat.filegen, "run", fake_filegen_run)
    monkeypatch.setattr(chat.router, "_deliver_docspec", fake_deliver_docspec)
    monkeypatch.setattr(chat.router, "_route_model_reply", fake_route_model_reply)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "Create a PDF report about revenue",
        )
    ]

    assert calls == ["sandbox", "docspec", "model"]
    assert {"status": ""} in events
    assert {"delta": "fallback answer"} in events
    assert events[-1] == stream_events.done()
    assert ("route-1", "deterministic_failed", None) in outcomes


@pytest.mark.anyio
async def test_stream_reply_dispatches_research_route(monkeypatch):
    calls = []

    async def fake_prepare_turn(*args, **kwargs):
        return _fake_turn(effort="high")

    async def fake_route_research(*args, **kwargs):
        calls.append(args[2])
        yield {"delta": "research report"}
        yield {"done": True}

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.router, "_route_research", fake_route_research)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "/research latest revenue trend",
        )
    ]

    assert calls == ["latest revenue trend"]
    assert {"delta": "research report"} in events
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_stream_reply_dispatches_project_create_route(monkeypatch):
    calls = []

    async def fake_prepare_turn(*args, **kwargs):
        return _fake_turn()

    async def fake_trusted_context(project_id):
        return None

    async def fake_record_plan(*args, **kwargs):
        return "route-1"

    async def fake_route_project_create(*args, **kwargs):
        calls.append(args[2])
        yield {"project": {"id": "p1", "name": args[2]}}
        yield {"done": True}

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.project_store, "trusted_context", fake_trusted_context)
    monkeypatch.setattr(chat.project_store, "name_from_prompt", lambda text: "Acme rollout")
    monkeypatch.setattr(chat.route_telemetry, "record_plan", fake_record_plan)
    monkeypatch.setattr(chat.router, "_route_project_create", fake_route_project_create)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "Create a new project workspace for Acme rollout",
        )
    ]

    assert calls == ["Acme rollout"]
    assert {"project": {"id": "p1", "name": "Acme rollout"}} in events
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_stream_reply_dispatches_audio_to_file_route(monkeypatch):
    calls = []

    async def fake_prepare_turn(*args, **kwargs):
        return _fake_turn()

    async def fake_trusted_context(project_id):
        return None

    async def fake_record_plan(*args, **kwargs):
        return "route-1"

    async def fake_route_file(*args, **kwargs):
        calls.append("file")
        state = args[-1]
        state.handled = True
        yield {"files": [{"kind": "file", "name": "narration.wav"}]}
        yield {"done": True}

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.project_store, "trusted_context", fake_trusted_context)
    monkeypatch.setattr(chat.route_telemetry, "record_plan", fake_record_plan)
    monkeypatch.setattr(chat.router, "_route_file", fake_route_file)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "Create a voice narration for this introduction",
        )
    ]

    assert calls == ["file"]
    assert {"files": [{"kind": "file", "name": "narration.wav"}]} in events
    assert events[-1] == {"done": True}


@pytest.mark.anyio
async def test_stream_reply_missing_conversation_returns_error(monkeypatch):
    async def fake_prepare_turn(*args, **kwargs):
        return None

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)

    events = [
        event
        async for event in chat.stream_reply(
            "00000000-0000-0000-0000-000000000001",
            "hello",
        )
    ]

    assert events == [stream_events.error("Conversation not found.")]


@pytest.mark.anyio
async def test_resume_without_running_task_signals_done():
    events = [
        event
        async for event in chat.resume("00000000-0000-0000-0000-0000000000ff")
    ]

    assert events == [stream_events.done()]


@pytest.mark.anyio
async def test_resume_running_task_streams_resumed_then_events(monkeypatch):
    statuses = []
    release = asyncio.Event()

    async def fake_conv_title(*args, **kwargs):
        return "Test chat"

    async def fake_start(*args, **kwargs):
        return "task-1"

    async def fake_finish(task_id, status):
        statuses.append((task_id, status))

    async def source():
        yield stream_events.delta("first")
        await release.wait()
        yield stream_events.delta("second")

    conv_id = "00000000-0000-0000-0000-0000000000dd"
    monkeypatch.setattr(chat.router, "_conv_title", fake_conv_title)
    monkeypatch.setattr(chat.taskbrain, "start", fake_start)
    monkeypatch.setattr(chat.taskbrain, "finish", fake_finish)

    chat.start_detached(conv_id, source())
    collector = asyncio.create_task(_collect_async(chat.resume(conv_id)))
    await asyncio.sleep(0)
    release.set()
    events = await asyncio.wait_for(collector, timeout=1)
    for _ in range(10):
        if statuses:
            break
        await asyncio.sleep(0)

    assert events[0] == stream_events.resumed()
    assert stream_events.delta("first") in events
    assert stream_events.delta("second") in events
    assert events[-1] == stream_events.done()
    assert statuses == [("task-1", "done")]


@pytest.mark.anyio
async def test_detached_run_surfaces_generator_errors(monkeypatch):
    statuses = []

    async def fake_conv_title(*args, **kwargs):
        return "Test chat"

    async def fake_start(*args, **kwargs):
        return "task-1"

    async def fake_finish(task_id, status):
        statuses.append((task_id, status))

    async def broken_source():
        yield stream_events.delta("before")
        raise RuntimeError("boom")

    monkeypatch.setattr(chat.router, "_conv_title", fake_conv_title)
    monkeypatch.setattr(chat.taskbrain, "start", fake_start)
    monkeypatch.setattr(chat.taskbrain, "finish", fake_finish)

    queue = chat.start_detached(
        "00000000-0000-0000-0000-0000000000ee",
        broken_source(),
    )
    events = [event async for event in chat.observe(queue)]
    for _ in range(10):
        if statuses:
            break
        await asyncio.sleep(0)

    assert events == [stream_events.delta("before"), stream_events.error("boom")]
    assert statuses == [("task-1", "failed")]


@pytest.mark.anyio
async def test_cancel_run_marks_detached_task_canceled(monkeypatch):
    statuses = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_conv_title(*args, **kwargs):
        return "Test chat"

    async def fake_start(*args, **kwargs):
        return "task-1"

    async def fake_finish(task_id, status):
        statuses.append((task_id, status))

    async def source():
        started.set()
        await release.wait()
        yield stream_events.delta("late")

    conv_id = "00000000-0000-0000-0000-0000000000cc"
    monkeypatch.setattr(chat.router, "_conv_title", fake_conv_title)
    monkeypatch.setattr(chat.taskbrain, "start", fake_start)
    monkeypatch.setattr(chat.taskbrain, "finish", fake_finish)

    queue = chat.start_detached(conv_id, source())
    await asyncio.wait_for(started.wait(), timeout=1)
    task = chat._run_tasks[conv_id]

    chat.cancel_run(conv_id)
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    events = [event async for event in chat.observe(queue)]

    assert events == []
    assert statuses == [("task-1", "canceled")]
    assert not chat.is_running(conv_id)


async def _collect_async(source):
    return [event async for event in source]
