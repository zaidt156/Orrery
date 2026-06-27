from __future__ import annotations

import asyncio
import base64
import datetime
import io
import json
import logging
import mimetypes
import re
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import get_sessionmaker
from backend.core.observability import log_event
from backend.core.models import Conversation, Message, Project
from backend.features import code_images, docgen, filegen, rag, route_telemetry, sandbox, skills, taskbrain, taskrouter
from backend.features import projects as project_store
from backend.features import files as file_library
from backend.features.prompting import FORMAT_INSTRUCTIONS, build_system_prompt, strip_think as _strip_think
from backend.features.chat_context import (
    DEFAULT_CONTEXT_WINDOW, _build_user_content, _content_token_estimate, _db_content,
    _effective_context_window, _history_text, _latest_user_text, _limit_messages,
    _message_artifacts, _title_from, _wants_high_effort,
)
from backend.features.reasoning_trace import ThinkStream, reasoning_event
from backend.providers import ai
from backend.security import privacy

_log = logging.getLogger("orrery.chat")


async def list_conversations() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(select(Conversation).order_by(Conversation.updated_at.desc()))
        ).scalars().all()
        return [
            {
                "id": str(c.id),
                "project_id": str(c.project_id) if c.project_id else None,
                "title": c.title,
                "model": c.model,
                "updated_at": c.updated_at.isoformat(),
            }
            for c in rows
        ]


async def create_conversation(
    model: str,
    system_prompt: str | None,
    effort: str | None = None,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    project_id: str | None = None,
) -> dict:
    async with get_sessionmaker()() as s:
        project_uuid = None
        if project_id:
            project = await s.get(Project, uuid.UUID(project_id))
            if project is None:
                raise ValueError("Project not found")
            project_uuid = project.id
        conv = Conversation(
            project_id=project_uuid,
            model=model,
            system_prompt=system_prompt or None,
            effort=effort or None,
            context_window=context_window,
        )
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        return {"id": str(conv.id), "project_id": str(conv.project_id) if conv.project_id else None,
                "title": conv.title, "model": conv.model,
                "system_prompt": conv.system_prompt, "effort": conv.effort,
                "context_window": _effective_context_window(conv.context_window), "messages": []}


async def get_conversation(conv_id: str) -> dict | None:
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        if conv is None:
            return None
        msgs = (
            await s.execute(
                select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
            )
        ).scalars().all()
        return {
            "id": str(conv.id), "title": conv.title, "model": conv.model,
            "project_id": str(conv.project_id) if conv.project_id else None,
            "system_prompt": conv.system_prompt, "effort": conv.effort,
            "context_window": _effective_context_window(conv.context_window),
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "model": m.model,
                    "artifacts": _message_artifacts(m.artifacts),
                }
                for m in msgs
            ],
        }


_UNSET = object()


async def update_conversation(
    conv_id: str,
    *,
    model=_UNSET,
    system_prompt=_UNSET,
    effort=_UNSET,
    context_window=_UNSET,
    project_id=_UNSET,
) -> dict | None:
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        if conv is None:
            return None
        if model is not _UNSET and model:
            conv.model = model
        if system_prompt is not _UNSET:
            conv.system_prompt = (system_prompt or None)
        if effort is not _UNSET:
            conv.effort = (effort or None)
        if context_window is not _UNSET:
            conv.context_window = context_window
        if project_id is not _UNSET:
            if project_id:
                project = await s.get(Project, uuid.UUID(project_id))
                if project is None:
                    return None
                conv.project_id = project.id
            else:
                conv.project_id = None
        await s.commit()
        await s.refresh(conv)
        return {"id": str(conv.id), "project_id": str(conv.project_id) if conv.project_id else None,
                "title": conv.title, "model": conv.model,
                "system_prompt": conv.system_prompt, "effort": conv.effort,
                "context_window": _effective_context_window(conv.context_window)}


async def delete_conversation(conv_id: str) -> bool:
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        if conv is None:
            return False
        await s.delete(conv)
        await s.commit()
        return True


async def _persist_assistant(
    cid: uuid.UUID,
    text: str,
    model: str,
    artifacts: list[dict] | None = None,
) -> str:
    async with get_sessionmaker()() as s:
        message = Message(
            conversation_id=cid,
            role="assistant",
            content=text,
            model=model,
            artifacts=json.dumps(artifacts) if artifacts else None,
        )
        s.add(message)
        conv = await s.get(Conversation, cid)
        if conv is not None:
            conv.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await s.commit()
        await s.refresh(message)
        return str(message.id)


async def _generate(
    cid: uuid.UUID,
    model: str,
    system_prompt: str | None,
    messages: list[dict],
    effort: str | None = None,
    untrusted_context: str | None = None,
    trusted_context: str | None = None,
) -> AsyncIterator[dict]:
    """Stream the assistant reply and persist it (saved even if the client cancels)."""
    parts: list[str] = []
    message_id: str | None = None
    usage_out: dict = {}
    user_text = _latest_user_text(messages)
    matched_skills = skills.select(user_text)  # which skill playbooks apply to this turn
    if matched_skills:
        yield reasoning_event("Loaded skills", ", ".join(s.name for s in matched_skills))
    formatted_prompt = build_system_prompt(  # explicit authority layers (app > skills > user > untrusted)
        app_rules=FORMAT_INSTRUCTIONS,
        skills_block=skills.skills_prompt(user_text),
        user_preferences=system_prompt,
        trusted_context=trusted_context,
        untrusted_context=untrusted_context,
    )
    # Code/creative work (code, web apps, SVGs, diagrams, building things) always gets high effort.
    gen_effort = filegen.quality_effort(model, effort) if _wants_high_effort(user_text) else effort
    log_event(_log, "chat_generate_started", model=model, rag=bool(untrusted_context), effort=gen_effort or "default")
    think = ThinkStream()  # condense the model's real reasoning (separate channel OR inline <think>)
    try:
        async for delta in ai.stream_chat(model, messages, formatted_prompt, gen_effort, usage_out):
            if isinstance(delta, ai.ReasoningDelta):
                for ev in think.feed_reasoning(str(delta)):
                    yield ev
                continue
            answer, events = think.feed(delta)  # strip inline <think> → reasoning steps; keep the answer
            for ev in events:
                yield ev
            if answer:
                parts.append(answer)
                yield {"delta": answer}
        tail, events = think.finish()
        for ev in events:
            yield ev
        if tail:
            parts.append(tail)
            yield {"delta": tail}
    except ai.MissingKeyError as exc:
        yield {"error": f"No API key for {exc.provider}. Add it in Settings."}
        return
    except Exception as exc:  # noqa: BLE001 — already sanitized by ai.stream_chat
        log_event(_log, "chat_generate_failed", model=model, error=type(exc).__name__)
        yield {"error": str(exc)}
        return
    finally:
        if parts:  # runs on normal completion AND on client-cancel (GeneratorExit)
            message_id = await _persist_assistant(cid, _strip_think("".join(parts)), model)
    if message_id:
        yield {"message_id": message_id}
    if usage_out.get("tokens_out") or usage_out.get("tokens_in"):
        # exact per-message token count (API/custom routes report it); the UI shows a live
        # estimate during streaming and replaces it with this exact count on completion
        yield {"message_usage": {
            "in": usage_out.get("tokens_in") or 0,
            "out": usage_out.get("tokens_out") or 0,
            "pricing_known": usage_out.get("pricing_known", True),
        }}
    if usage_out.get("cost") is not None and (usage_out.get("tokens_out") or usage_out.get("tokens_in")):
        from backend.features import usage as usage_mod
        await usage_mod.record(usage_out["provider"], usage_out["model"], usage_out["tokens_in"], usage_out["tokens_out"], usage_out["cost"])
        yield {"usage": await usage_mod.summary()}  # live meter update
    yield {"done": True}


async def _rag_context(model: str, collection_id: str, query: str) -> tuple[str | None, list[str]]:
    """Retrieve top chunks, redact for cloud models, return (context_block, sources)."""
    try:
        results = await rag.search(collection_id, query, k=settings.rag_top_k)
    except Exception:  # noqa: BLE001 — a retrieval failure shouldn't break the chat
        return None, []
    if not results:
        return None, []
    is_local = ai.model_provider(model) == "ollama"
    block = "\n\n".join(
        f"[{r['source']}]\n{privacy.redact_for_model(r['content'], is_local)}" for r in results
    )
    sources = list(dict.fromkeys(r["source"] for r in results))
    return block, sources


_FILE_FORMAT_PATTERNS = [
    ("pptx", re.compile(r"\b(powerpoint|pptx?|presentation|slide|deck)\b", re.IGNORECASE)),
    ("xlsx", re.compile(r"\b(excel|xlsx?|spreadsheet|workbook|sheet)\b", re.IGNORECASE)),
    ("docx", re.compile(r"\b(word|docx?|document)\b", re.IGNORECASE)),
    ("csv", re.compile(r"\bcsv\b", re.IGNORECASE)),
    ("pdf", re.compile(r"\b(pdf|report)\b", re.IGNORECASE)),
]


def _detect_formats(text: str) -> list[str]:
    found = [fmt for fmt, pattern in _FILE_FORMAT_PATTERNS if pattern.search(text or "")]
    return found or ["pdf"]


async def _conv_title(cid: uuid.UUID) -> str:
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        return (conv.title if conv and conv.title else None) or "Orrery file"


async def _deliver_docspec(
    cid: uuid.UUID,
    model: str,
    request: str,
    system_prompt: str | None,
    effort: str | None,
    untrusted_context: str | None = None,
    trusted_context: str | None = None,
) -> AsyncIterator[dict]:
    """Reliable fallback when code-execution misses: ask for a structured spec, then build the
    file deterministically with docgen and deliver it. Yields nothing if no spec comes back."""
    yield {"status": "Creating the file structure…"}
    instructions = build_system_prompt(
        app_rules=FORMAT_INSTRUCTIONS,
        user_preferences=system_prompt,
        trusted_context=trusted_context,
        untrusted_context=untrusted_context,
    )
    parts: list[str] = []
    think = ThinkStream()  # universal: separate reasoning channel OR inline <think>
    try:
        async for delta in ai.stream_chat(model, [{"role": "user", "content": request}], instructions, filegen.quality_effort(model, effort)):
            if isinstance(delta, ai.ReasoningDelta):
                for ev in think.feed_reasoning(str(delta)):
                    yield ev
                continue
            answer, events = think.feed(str(delta))
            for ev in events:
                yield ev
            if answer:
                parts.append(answer)
        tail, events = think.finish()
        for ev in events:
            yield ev
        if tail:
            parts.append(tail)
    except Exception:  # noqa: BLE001 — fall through to a normal reply
        return
    content = "".join(parts)
    spec = docgen.parse_doc_spec(content)
    if spec is None:
        return
    title = await _conv_title(cid)
    produced: list[dict] = []
    for fmt in _detect_formats(request):
        try:
            result = await asyncio.to_thread(docgen.render_spec, title, model, spec, fmt)
            produced.append({"kind": "file", **file_library.store(result.filename, result.media_type, result.content)})
        except Exception:  # noqa: BLE001 — skip a format that fails to build
            continue
    if not produced:
        return
    idx = content.lower().find("```orrery-doc")
    summary = (content[:idx] if idx >= 0 else content).strip()[:300] or "Here is your file."
    message_id = await _persist_assistant(cid, summary, model, produced)
    yield {"delta": summary}
    yield {"files": produced}
    yield {"message_id": message_id}
    yield {"done": True}


# --- detached runs: keep generating + persisting even if the client navigates away ---
_RUN_DONE = object()
_run_queues: dict[str, asyncio.Queue] = {}
_run_tasks: dict[str, asyncio.Task] = {}


def start_detached(conv_id: str, source: AsyncIterator[dict]) -> asyncio.Queue:
    """Drive a generation to completion in a background task (it persists in its own finally),
    pushing events to a queue the HTTP request observes. Client disconnect stops the observer,
    not the task — so the reply finishes and is saved regardless. Recorded in the Task Brain."""
    cancel_run(conv_id)
    queue: asyncio.Queue = asyncio.Queue()
    _run_queues[conv_id] = queue

    async def drive() -> None:
        task_id: str | None = None
        status = "done"
        try:
            try:  # the Task Brain ledger is best-effort and must NEVER hang or fail the generation
                title = await asyncio.wait_for(_conv_title(uuid.UUID(conv_id)), timeout=5)
                task_id = await asyncio.wait_for(taskbrain.start("chat", title, conv_id), timeout=5)
            except Exception:  # noqa: BLE001 — ledger down/slow → just skip recording
                task_id = None
            async for event in source:
                if "error" in event:
                    status = "failed"
                queue.put_nowait(event)
        except asyncio.CancelledError:
            status = "canceled"
            raise
        except Exception as exc:  # noqa: BLE001 — surface a sanitized error
            status = "failed"
            queue.put_nowait({"error": str(exc)})
        finally:
            queue.put_nowait(_RUN_DONE)
            if _run_queues.get(conv_id) is queue:
                _run_queues.pop(conv_id, None)
            _run_tasks.pop(conv_id, None)
            try:
                await asyncio.wait_for(taskbrain.finish(task_id, status), timeout=5)
            except Exception:  # noqa: BLE001 — ledger update is best-effort
                pass

    _run_tasks[conv_id] = asyncio.create_task(drive())
    return queue


async def observe(queue: asyncio.Queue) -> AsyncIterator[dict]:
    while True:
        event = await queue.get()
        if event is _RUN_DONE:
            return
        yield event


def is_running(conv_id: str) -> bool:
    """True if a detached generation for this conversation is still in flight."""
    return conv_id in _run_tasks


async def resume(conv_id: str) -> AsyncIterator[dict]:
    """Re-attach to an in-flight generation and stream its remaining events. If nothing is
    running, signal done immediately so the client just reloads the (saved) conversation."""
    queue = _run_queues.get(conv_id)
    if queue is None:
        yield {"done": True}
        return
    yield {"resumed": True}
    async for event in observe(queue):
        yield event
    yield {"done": True}


def cancel_run(conv_id: str) -> None:
    """Explicitly stop a run (the Stop button) — different from a client just navigating away."""
    task = _run_tasks.pop(conv_id, None)
    _run_queues.pop(conv_id, None)
    if task and not task.done():
        task.cancel()


async def stream_reply(
    conv_id: str,
    user_content: str,
    attachments: list[dict] | None = None,
    collection_id: str | None = None,
) -> AsyncIterator[dict]:
    """Persist the user message (with any attachments), then stream + persist the reply."""
    cid = uuid.UUID(conv_id)
    attachments = attachments or []

    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        if conv is None:
            yield {"error": "Conversation not found."}
            return
        model, system_prompt, effort = conv.model, conv.system_prompt, conv.effort
        project_id = conv.project_id
        context_window = _effective_context_window(conv.context_window)

        history = (
            await s.execute(
                select(Message).where(Message.conversation_id == cid).order_by(Message.created_at)
            )
        ).scalars().all()
        messages = [{"role": m.role, "content": m.context or m.content} for m in history]
        messages.append({"role": "user", "content": _build_user_content(user_content, attachments)})

        s.add(Message(
            conversation_id=cid, role="user",
            content=_db_content(user_content, attachments),
            context=_history_text(user_content, attachments),  # keeps file/PDF text for later turns
        ))
        if conv.title == "New chat" and not history:
            seed = user_content or (attachments[0].get("name") if attachments else "")
            conv.title = _title_from(seed)
        new_title = conv.title
        await s.commit()

    yield {"title": new_title}

    gen_system = system_prompt        # user's standing instructions only
    trusted_context = await project_store.trusted_context(project_id)
    if trusted_context:
        yield reasoning_event("Preparing project context", "Loaded the current project's standing context and instructions.")
    rag_context = None                 # retrieved docs — passed separately as UNTRUSTED context
    if collection_id and user_content.strip():
        block, sources = await _rag_context(model, collection_id, user_content)
        if block:
            rag_context = block
            yield {"sources": sources}
            yield reasoning_event("Preparing context", f"Loaded {len(sources)} document(s) from your collection to answer from.")

    plan = taskrouter.plan(user_content, has_attachments=bool(attachments))
    route_event_id = await route_telemetry.record_plan(str(cid), plan, has_attachments=bool(attachments))
    if plan.route != "chat" or attachments:
        yield reasoning_event("Planning task", f"{plan.label}: {plan.detail}")

    if plan.route == "image" and not attachments:
        outcome = "completed"
        async for ev in _deliver_code_image(cid, model, user_content, gen_system, effort):
            if "error" in ev:
                outcome = "failed"
            yield ev
        await route_telemetry.record_outcome(route_event_id, outcome)
        return

    if plan.route == "project":
        project_name = project_store.name_from_prompt(user_content)
        if project_name:
            project = await project_store.create_project(project_name)
            await project_store.set_conversation_project(str(cid), project["id"])
            message = f"Created project **{project['name']}** and attached this chat to it."
            message_id = await _persist_assistant(cid, message, model)
            yield {"project": project}
            yield {"delta": message}
            if message_id:
                yield {"message_id": message_id}
            yield {"done": True}
            await route_telemetry.record_outcome(route_event_id, "completed")
            return

    if plan.route == "audio" and plan.unavailable_reason:
        message = plan.unavailable_reason
        message_id = await _persist_assistant(cid, message, model)
        yield {"delta": message}
        if message_id:
            yield {"message_id": message_id}
        yield {"done": True}
        await route_telemetry.record_outcome(route_event_id, "unavailable", "voice provider not configured")
        return

    if plan.route == "project" and plan.unavailable_reason:
        message = plan.unavailable_reason
        message_id = await _persist_assistant(cid, message, model)
        yield {"delta": message}
        if message_id:
            yield {"message_id": message_id}
        yield {"done": True}
        await route_telemetry.record_outcome(route_event_id, "unavailable", "project route unavailable")
        return

    # File generation routing: deterministic `docgen` first for normal documents; the sandboxed
    # code path only when the router selects artifacts that need computation, visuals, or audio.
    if plan.route == "file":
        use_sandbox = plan.uses_sandbox and sandbox.image_ready()
        sandbox_attempted = False
        if use_sandbox:
            sandbox_attempted = True
            yield reasoning_event("Selected generation path", "Sandboxed code execution (charts, images, or computed files).")
            result = None
            async for ev in filegen.run(model, user_content, gen_system, effort, rag_context, trusted_context):
                if "result" in ev:
                    result = ev["result"]
                else:
                    yield ev  # status / reasoning_event / etc.
            if result and result.get("ok") and result.get("files"):
                produced: list[dict] = []
                for item in result["files"]:
                    mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
                    try:
                        produced.append({"kind": "file", **file_library.store(item.name, mime, item.data)})
                    except ValueError:
                        continue
                if produced:
                    summary = result.get("summary") or "Here is your file."
                    message_id = await _persist_assistant(cid, summary, model, produced)
                    yield {"delta": summary}
                    yield {"files": produced}
                    yield {"message_id": message_id}
                    yield {"done": True}
                    await route_telemetry.record_outcome(route_event_id, "sandbox_success")
                    return
            # sandbox missed → fall through to the deterministic builder so we never come up empty
        else:
            yield reasoning_event("Selected generation path", "Deterministic document builder.")
        delivered = False
        async for ev in _deliver_docspec(cid, model, user_content, gen_system, effort, rag_context, trusted_context):
            if "files" in ev:
                delivered = True
            yield ev
        if delivered:
            outcome = "sandbox_fallback" if sandbox_attempted else "deterministic_success"
            await route_telemetry.record_outcome(route_event_id, outcome)
            return
        await route_telemetry.record_outcome(route_event_id, "deterministic_failed")
        yield {"status": ""}  # clear the progress note before the plain fallback reply streams

    budget_system = "\n\n".join(part for part in (gen_system, trusted_context, rag_context) if part)
    messages = _limit_messages(messages, context_window, budget_system)
    outcome = "completed"
    async for event in _generate(cid, model, gen_system, messages, effort, rag_context, trusted_context):
        if "error" in event:
            outcome = "failed"
        yield event
    if plan.route in {"chat", "project"}:
        await route_telemetry.record_outcome(route_event_id, outcome)


async def _deliver_code_image(
    cid: uuid.UUID,
    model: str,
    user_content: str,
    system_prompt: str | None,
    effort: str | None,
) -> AsyncIterator[dict]:
    """Generate, persist, and stream a sanitized SVG artifact."""
    yield {"status": "Rendering a safe SVG image..."}
    yield reasoning_event("Selected generation path", "Sanitized code-rendered SVG image.")
    try:
        svg = await code_images.generate_svg(model, user_content, system_prompt, filegen.quality_effort(model, effort))
    except ai.MissingKeyError as exc:
        yield {"error": f"No API key for {exc.provider}. Add it in Settings."}
        return
    except Exception as exc:  # noqa: BLE001 - provider errors are sanitized upstream
        yield {"error": str(exc)}
        return

    artifact = {
        "kind": "svg",
        "name": "orrery-generated-image.svg",
        "mime": "image/svg+xml",
        "content": svg,
    }
    message = "Created a code-rendered SVG image from your prompt."
    message_id = await _persist_assistant(cid, message, model, [artifact])
    yield {"artifact": artifact}
    yield {"delta": message}
    yield {"message_id": message_id}
    yield {"done": True}


async def stream_code_image(conv_id: str, user_content: str) -> AsyncIterator[dict]:
    """Generate a sanitized SVG artifact through the selected text model."""
    cid = uuid.UUID(conv_id)
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        if conv is None:
            yield {"error": "Conversation not found."}
            return
        model, system_prompt, effort = conv.model, conv.system_prompt, conv.effort
        history = (
            await s.execute(
                select(Message).where(Message.conversation_id == cid).order_by(Message.created_at)
            )
        ).scalars().all()
        s.add(Message(
            conversation_id=cid,
            role="user",
            content=user_content,
            context=f"[code-rendered image request]\n{code_images.image_prompt(user_content)}",
        ))
        if conv.title == "New chat" and not history:
            conv.title = _title_from(code_images.image_prompt(user_content))
        new_title = conv.title
        await s.commit()

    yield {"title": new_title}
    async for ev in _deliver_code_image(cid, model, user_content, system_prompt, effort):
        yield ev


async def regenerate(conv_id: str) -> AsyncIterator[dict]:
    """Re-answer the last user turn: drop trailing assistant message(s), re-stream."""
    cid = uuid.UUID(conv_id)

    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        if conv is None:
            yield {"error": "Conversation not found."}
            return
        model, system_prompt, effort = conv.model, conv.system_prompt, conv.effort
        project_id = conv.project_id
        context_window = _effective_context_window(conv.context_window)

        history = (
            await s.execute(
                select(Message).where(Message.conversation_id == cid).order_by(Message.created_at)
            )
        ).scalars().all()
        history = list(history)
        while history and history[-1].role == "assistant":
            await s.delete(history[-1])
            history.pop()
        await s.commit()

        if not history or history[-1].role != "user":
            yield {"error": "Nothing to regenerate."}
            return
        messages = [{"role": m.role, "content": m.context or m.content} for m in history]

    trusted_context = await project_store.trusted_context(project_id)
    budget_system = "\n\n".join(part for part in (system_prompt, trusted_context) if part)
    messages = _limit_messages(messages, context_window, budget_system)
    async for event in _generate(cid, model, system_prompt, messages, effort, trusted_context=trusted_context):
        yield event
