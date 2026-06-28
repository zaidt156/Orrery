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
from dataclasses import dataclass

from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import get_sessionmaker
from backend.core.observability import log_event
from backend.core.models import Conversation, Message, Project
from backend.features import code_images, code_interpreter, docgen, filegen, rag, reasoning, research, route_telemetry, sandbox, skills, taskbrain, taskrouter
from backend.features import projects as project_store
from backend.features import files as file_library
from backend.features.prompting import CODE_INTERPRETER_PROMPT, FORMAT_INSTRUCTIONS, build_system_prompt, strip_think as _strip_think
from backend.features.chat_context import (
    DEFAULT_CONTEXT_WINDOW, _build_user_content, _content_token_estimate, _db_content,
    _effective_context_window, _history_text, _latest_user_text, _limit_messages,
    _message_artifacts, _title_from, _wants_high_effort,
)
from backend.features.reasoning_trace import ReasoningTrace, ThinkStream, reasoning_event
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


@dataclass(slots=True)
class _TurnContext:
    """Everything stream_reply needs from the DB for one turn — the single DB seam.

    Keeping this load/persist in one place makes the orchestrator mockable (see Phase A of the
    task-routing hardening plan): tests can substitute _prepare_turn instead of a live Postgres.
    """
    model: str
    system_prompt: str | None
    effort: str | None
    project_id: uuid.UUID | None
    context_window: int
    messages: list[dict]
    title: str


async def _prepare_turn(cid: uuid.UUID, user_content: str, attachments: list[dict]) -> _TurnContext | None:
    """Load the conversation + history and persist the incoming user message. None if missing."""
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        if conv is None:
            return None
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
        title = conv.title
        await s.commit()

    return _TurnContext(model, system_prompt, effort, project_id, context_window, messages, title)


def _plan_metadata(plan) -> dict:
    """Small, safe metadata for the reasoning UI (route/sandbox/confidence — never prompt text)."""
    telemetry = getattr(plan, "telemetry", None)
    if callable(telemetry):
        try:
            return telemetry()
        except Exception:  # noqa: BLE001 — metadata is cosmetic; never break the stream
            pass
    sandbox = "required" if getattr(plan, "sandbox_required", False) else (
        "preferred" if getattr(plan, "sandbox_preferred", False) else "none")
    return {
        "route": getattr(plan, "route", "chat"),
        "label": getattr(plan, "label", "Chat"),
        "output_mode": getattr(plan, "output_mode", "chat"),
        "sandbox_policy": sandbox,
        "confidence": float(getattr(plan, "confidence", 0.0) or 0.0),
        "skills": ",".join(getattr(plan, "skills", ()) or ()),
    }


def _outer_title_for_plan(plan) -> str:
    """The collapsed outer card headline — what Orrery is about to do, plainly."""
    route = getattr(plan, "route", "chat")
    label = getattr(plan, "label", "Chat")
    if route == "file":
        return "Preparing the requested file"
    if route == "image":
        return "Preparing a safe visual artifact"
    if route == "project":
        return "Preparing the project workspace action"
    if route == "audio":
        return "Checking audio and voice capabilities"
    return f"Working through the request with {label.lower()}"


def _outer_summary_for_plan(plan, *, has_attachments: bool) -> str:
    detail = getattr(plan, "detail", "") or "Preparing the answer."
    return f"{detail} Attachments are included as context." if has_attachments else detail


_RESEARCH_PREFIX = re.compile(r"^\s*/(?:deep[\s-]?research|research)\b[:\s]*", re.IGNORECASE)


def _research_query(text: str) -> str | None:
    """Return the question after a /research (or /deep research) command, else None."""
    match = _RESEARCH_PREFIX.match(text or "")
    if not match:
        return None
    return text[match.end():].strip()


@dataclass(slots=True)
class _RouteResult:
    """Mutable outcome for route handlers that may fall back to normal chat."""

    handled: bool = False
    outcome: str = "completed"


async def _route_research(
    cid: uuid.UUID,
    model: str,
    query: str,
    collection_id: str | None,
    project_id: uuid.UUID | None,
    effort: str | None,
    trace: ReasoningTrace,
) -> AsyncIterator[dict]:
    """Run the explicit Deep Research workflow."""
    research_collection = collection_id
    if not research_collection and project_id:
        research_collection = await project_store.collection_id_for(project_id)
    research_trusted = await project_store.trusted_context(project_id)

    async def _persist_research(text: str, arts: list[dict] | None) -> str:
        return await _persist_assistant(cid, text, model, arts)

    async for event in research.run(
        model, query,
        collection_id=research_collection, effort=effort,
        trusted_context=research_trusted, trace=trace, persist=_persist_research,
    ):
        if event.get("done"):
            yield trace.done("Finished the research report and saved it.")
            yield trace.summary()
        yield event


async def _route_image(
    cid: uuid.UUID,
    model: str,
    user_content: str,
    gen_system: str | None,
    effort: str | None,
    trace: ReasoningTrace,
    route_event_id: str | None,
) -> AsyncIterator[dict]:
    """Generate and persist a standalone sanitized SVG artifact."""
    outcome = "completed"
    yield trace.step(
        "Rendering visual artifact",
        "Generating and sanitizing the SVG before saving it to the conversation.",
        kind="tool", status="running", phase="execute",
    )
    async for ev in _deliver_code_image(cid, model, user_content, gen_system, effort):
        if "error" in ev:
            outcome = "failed"
            yield trace.error("Image generation failed", ev.get("error", "The image route failed."))
        elif ev.get("done"):
            yield trace.done("Created and saved the sanitized visual artifact.")
            yield trace.summary()
        yield ev
    await route_telemetry.record_outcome(route_event_id, outcome)


async def _route_project_create(
    cid: uuid.UUID,
    model: str,
    project_name: str,
    trace: ReasoningTrace,
    route_event_id: str | None,
) -> AsyncIterator[dict]:
    """Create a durable project workspace and attach this chat."""
    yield trace.step(
        "Creating project",
        f"Creating a durable project workspace named {project_name} and attaching this chat.",
        kind="tool", status="running", phase="execute",
    )
    project = await project_store.create_project(project_name)
    await project_store.set_conversation_project(str(cid), project["id"])
    message = f"Created project **{project['name']}** and attached this chat to it."
    message_id = await _persist_assistant(cid, message, model)
    yield {"project": project}
    yield {"delta": message}
    if message_id:
        yield {"message_id": message_id}
    yield trace.done("Created the project and attached this chat to it.")
    yield trace.summary()
    yield {"done": True}
    await route_telemetry.record_outcome(route_event_id, "completed")


async def _route_audio_unavailable(
    cid: uuid.UUID,
    model: str,
    message: str,
    trace: ReasoningTrace,
    route_event_id: str | None,
) -> AsyncIterator[dict]:
    """Return a clear status when voice/audio providers are not configured."""
    message_id = await _persist_assistant(cid, message, model)
    yield trace.warning("Audio route unavailable", "Voice playback/transcription providers are not configured yet.")
    yield {"delta": message}
    if message_id:
        yield {"message_id": message_id}
    yield trace.summary()
    yield {"done": True}
    await route_telemetry.record_outcome(route_event_id, "unavailable", "voice provider not configured")


async def _route_file(
    cid: uuid.UUID,
    model: str,
    user_content: str,
    gen_system: str | None,
    effort: str | None,
    rag_context: str | None,
    trusted_context: str | None,
    plan: taskrouter.TaskPlan,
    trace: ReasoningTrace,
    route_event_id: str | None,
    state: _RouteResult,
) -> AsyncIterator[dict]:
    """Generate requested files, falling back from sandbox to docgen to normal chat."""
    use_sandbox = plan.uses_sandbox and sandbox.image_ready()
    sandbox_attempted = False
    if use_sandbox:
        sandbox_attempted = True
        yield trace.step(
            "Selected generation path",
            "Using sandboxed code execution because this file needs computation, visuals, audio, archives, or complex output.",
            kind="tool", status="done", phase="execute", metadata={"sandbox": True},
        )
        result = None
        async for ev in filegen.run(model, user_content, gen_system, effort, rag_context, trusted_context):
            if "result" in ev:
                result = ev["result"]
            else:
                yield ev
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
                yield trace.done("Generated, validated, stored, and attached the requested file output.")
                yield trace.summary()
                yield {"done": True}
                await route_telemetry.record_outcome(route_event_id, "sandbox_success")
                state.handled = True
                state.outcome = "sandbox_success"
                return
        yield trace.warning(
            "Sandbox fallback",
            "The sandbox path did not produce an approved file, so Orrery is falling back to deterministic document generation.",
            sandbox_attempted=True,
        )
    else:
        yield trace.step(
            "Selected generation path",
            "Using the deterministic document builder for this downloadable file.",
            kind="tool", status="done", phase="execute", metadata={"sandbox": False},
        )

    delivered = False
    async for ev in _deliver_docspec(cid, model, user_content, gen_system, effort, rag_context, trusted_context):
        if "files" in ev:
            delivered = True
        if ev.get("done"):
            yield trace.done("Rendered the structured document spec, stored the file, and attached it to the chat.")
            yield trace.summary()
        yield ev
    if delivered:
        outcome = "sandbox_fallback" if sandbox_attempted else "deterministic_success"
        await route_telemetry.record_outcome(route_event_id, outcome)
        state.handled = True
        state.outcome = outcome
        return

    await route_telemetry.record_outcome(route_event_id, "deterministic_failed")
    state.outcome = "deterministic_failed"
    yield trace.warning(
        "File route fallback",
        "The file builder could not produce an approved artifact, so Orrery will answer in normal chat instead.",
    )
    yield {"status": ""}


async def _route_model_reply(
    cid: uuid.UUID,
    model: str,
    gen_system: str | None,
    messages: list[dict],
    effort: str | None,
    context_window: int,
    trusted_context: str | None,
    rag_context: str | None,
    plan: taskrouter.TaskPlan,
    trace: ReasoningTrace,
    route_event_id: str | None,
) -> AsyncIterator[dict]:
    """Stream the normal model reply, optionally using the universal sandbox tool loop."""
    budget_system = "\n\n".join(part for part in (gen_system, trusted_context, rag_context) if part)
    limited_messages = _limit_messages(messages, context_window, budget_system)
    outcome = "completed"

    if sandbox.image_ready():
        user_text = _latest_user_text(limited_messages)
        gen_effort = filegen.quality_effort(model, effort) if _wants_high_effort(user_text) else effort
        matched_skills = skills.select(user_text)
        if matched_skills:
            yield trace.step("Loaded skills", ", ".join(s.name for s in matched_skills), kind="context", status="done", phase="context")
        yield trace.step(
            "Generating answer",
            "Answering with the selected model; it can write and run Python in the sandbox if that helps.",
            kind="work", status="running", phase="execute", metadata={"model": model},
        )
        formatted_prompt = build_system_prompt(
            app_rules=FORMAT_INSTRUCTIONS,
            feature_rules=CODE_INTERPRETER_PROMPT,
            skills_block=skills.skills_prompt(user_text),
            user_preferences=gen_system,
            trusted_context=trusted_context,
            untrusted_context=rag_context,
        )

        async def _persist(text: str, arts: list[dict] | None) -> str:
            return await _persist_assistant(cid, text, model, arts)

        async for event in code_interpreter.run(
            model, formatted_prompt, limited_messages, gen_effort, trace=trace, persist=_persist,
        ):
            if "error" in event:
                outcome = "failed"
                yield trace.error("Generation failed", event.get("error", "The model call failed."))
            if event.get("done"):
                yield trace.done("Finished the answer and saved the reply.")
                yield trace.summary()
            yield event
    else:
        yield trace.step(
            "Generating answer",
            "Streaming the response from the selected model while keeping hidden reasoning out of the visible answer.",
            kind="work", status="running", phase="execute", metadata={"model": model},
        )
        async for event in _generate(cid, model, gen_system, limited_messages, effort, rag_context, trusted_context):
            if "error" in event:
                outcome = "failed"
                yield trace.error("Generation failed", event.get("error", "The model call failed."))
            if event.get("done"):
                yield trace.done("Finished streaming and saved the assistant reply.")
                yield trace.summary()
            yield event

    if plan.route in {"chat", "project"}:
        await route_telemetry.record_outcome(route_event_id, outcome)


async def stream_reply(
    conv_id: str,
    user_content: str,
    attachments: list[dict] | None = None,
    collection_id: str | None = None,
) -> AsyncIterator[dict]:
    """Persist the user message (with any attachments), then stream + persist the reply."""
    cid = uuid.UUID(conv_id)
    attachments = attachments or []

    turn = await _prepare_turn(cid, user_content, attachments)
    if turn is None:
        yield {"error": "Conversation not found."}
        return
    model, system_prompt, effort = turn.model, turn.system_prompt, turn.effort
    project_id = turn.project_id
    context_window = turn.context_window
    messages = turn.messages

    yield {"title": turn.title}

    # Deep Research: an explicit /research command runs the decompose -> gather -> cited-report
    # workflow instead of a normal chat turn.
    research_q = _research_query(user_content)
    if research_q is not None:
        trace = ReasoningTrace()
        yield trace.outer(
            "Deep Research",
            "Decomposing the question, gathering evidence from your documents, and writing a cited report.",
            status="running", phase="route", metadata={"route": "research", "reasoning_mode": reasoning.label(effort)},
        )
        async for event in _route_research(cid, model, research_q or user_content, collection_id, project_id, effort, trace):
            yield event
        return

    # Plan first so the UI can show the collapsed outer reasoning card immediately. Every visible
    # line below is backend-authored: route chosen → context loaded → tool run → validated → done.
    # Raw/condensed model chain-of-thought is never surfaced here (see reasoning_trace safety rule).
    plan = taskrouter.plan(user_content, has_attachments=bool(attachments))
    plan_meta = _plan_metadata(plan)
    plan_meta["reasoning_mode"] = reasoning.label(effort)  # Quick / Standard / Deep / Max
    trace = ReasoningTrace()
    yield trace.outer(
        _outer_title_for_plan(plan),
        _outer_summary_for_plan(plan, has_attachments=bool(attachments)),
        status="running", phase="route", metadata=plan_meta,
    )
    yield trace.step(
        "Choosing response path", f"Selected {plan.label}. {plan.detail}",
        kind="route", status="done", phase="route", metadata=plan_meta,
    )
    route_event_id = await route_telemetry.record_plan(str(cid), plan, has_attachments=bool(attachments))

    gen_system = system_prompt        # user's standing instructions only
    trusted_context = await project_store.trusted_context(project_id)
    if trusted_context:
        yield trace.step(
            "Preparing project context",
            "Loaded the current project's standing context and instructions.",
            kind="context", status="done", phase="context",
        )
    if not collection_id and project_id:  # project chats answer from the project's uploaded files
        collection_id = await project_store.collection_id_for(project_id)
    rag_context = None                 # retrieved docs — passed separately as UNTRUSTED context
    if collection_id and user_content.strip():
        block, sources = await _rag_context(model, collection_id, user_content)
        if block:
            rag_context = block
            yield {"sources": sources}
            yield trace.step(
                "Searching uploaded documents",
                f"Loaded {len(sources)} document(s) from project/collection files to answer from.",
                kind="context", status="done", phase="context", metadata={"source_count": len(sources)},
            )

    if plan.route == "image" and not attachments:
        async for event in _route_image(cid, model, user_content, gen_system, effort, trace, route_event_id):
            yield event
        return

    if plan.route == "project":
        project_name = project_store.name_from_prompt(user_content)
        if project_name:
            async for event in _route_project_create(cid, model, project_name, trace, route_event_id):
                yield event
            return

    if plan.route == "audio" and plan.unavailable_reason:
        async for event in _route_audio_unavailable(cid, model, plan.unavailable_reason, trace, route_event_id):
            yield event
        return

    if plan.route == "file":
        route_state = _RouteResult()
        async for event in _route_file(
            cid, model, user_content, gen_system, effort, rag_context, trusted_context,
            plan, trace, route_event_id, route_state,
        ):
            yield event
        if route_state.handled:
            return

    async for event in _route_model_reply(
        cid, model, gen_system, messages, effort, context_window, trusted_context, rag_context,
        plan, trace, route_event_id,
    ):
        yield event
    return


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

    trace = ReasoningTrace()  # same two-layer activity card as a normal turn
    yield trace.outer("Regenerating the answer", "Re-answering the last turn with the selected model.", status="running", phase="route")
    if trusted_context:
        yield trace.step("Preparing project context", "Loaded the current project's standing context and instructions.", kind="context", status="done", phase="context")
    yield trace.step("Generating answer", "Streaming a fresh response from the selected model.", kind="work", status="running", phase="execute", metadata={"model": model})
    async for event in _generate(cid, model, system_prompt, messages, effort, trusted_context=trusted_context):
        if event.get("done"):
            yield trace.done("Finished streaming and saved the regenerated reply.")
            yield trace.summary()
        yield event
