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
from backend.core.models import Conversation, Message
from backend.features import code_images, docgen, filegen, rag, sandbox, skills, taskbrain, taskrouter
from backend.features import files as file_library
from backend.features.prompting import build_system_prompt
from backend.features.reasoning_trace import ThinkStream, reasoning_event
from backend.providers import ai
from backend.security import privacy

_log = logging.getLogger("orrery.chat")

# Local models (deepseek-r1, qwen3…) emit reasoning inline as <think>…</think>. That is raw
# reasoning — strip it from the saved/answer text; the panel shows safe trace events instead.
_THINK_RX = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


def _strip_think(text: str) -> str:
    text = _THINK_RX.sub("", text)
    text = re.sub(r"<think>[\s\S]*$", "", text, flags=re.IGNORECASE)  # unclosed (stream cut off)
    return text.strip()

FORMAT_INSTRUCTIONS = (
    "You are an expert-level assistant: answer with the depth and rigor of a specialist in whatever "
    "field the user is asking about (engineering, data, science, law, medicine, finance, writing, and "
    "so on). Be accurate above all — never invent facts, and say so when you are unsure or when a claim "
    "needs verifying.\n\n"
    "Match the length of the answer to the question. If a single word or one line fully and correctly "
    "answers it, reply with just that — do not pad simple questions. For anything non-trivial, multi-step, "
    "or open-ended, first briefly **plan** (a short ordered outline of how you'll approach it), then "
    "**implement** — carry the plan out with the actual answer, code, or concrete steps.\n\n"
    "Format replies in GitHub-flavored Markdown unless the user asks for another format. Use short "
    "headings, lists, or tables when they make the answer easier to scan. Always put code, commands, "
    "config, SQL, JSON, logs, and file contents in fenced code blocks with the most accurate language "
    "tag, for example ```python, ```js, ```sql, or ```bash. Do not put ordinary prose inside code fences.\n\n"
    "FILES: when the user asks you to create or 'give me' a file - PDF, Word, Excel, PowerPoint, CSV, "
    "Markdown, text, HTML, or JSON - do exactly TWO things and nothing else. (1) Write ONE short sentence in "
    "plain language saying what you made and what it contains, e.g. 'Here is a 5-slide deck on the solar "
    "system covering the Sun and the four inner planets.' (2) Then output exactly ONE fenced code block "
    "tagged orrery-doc holding a single JSON object that DESIGNS the file's real structure. Do not write the "
    "document's full content as prose anywhere outside that JSON, and do not write code to build the file.\n\n"
    "The orrery-doc JSON schema (include only the keys relevant to the request):\n"
    "{\n"
    '  "title": "string",\n'
    '  "subtitle": "string (optional, for decks)",\n'
    '  "slides": [ {"title": "string", "bullets": ["string", ...], "notes": "string (optional)"} ],\n'
    '  "sheets": [ {"name": "string", "columns": ["string", ...], "rows": [["string", ...], ...]} ],\n'
    '  "sections": [ {"heading": "string", "level": 1, "paragraphs": ["string", ...], "bullets": ["string", ...], "table": {"columns": ["string", ...], "rows": [["string", ...], ...]}} ]\n'
    "}\n"
    "Use 'slides' for presentations/PowerPoint, 'sheets' for spreadsheets/Excel/CSV, and 'sections' for "
    "documents/PDF/Word/Markdown/text/HTML.\n\n"
    "QUALITY BAR — treat this with the SAME effort and depth as writing the file yourself; the spec must be "
    "comprehensive and ready to hand over, never a skeleton or placeholders:\n"
    "- Always set a specific, descriptive \"title\" naming the actual document (e.g. \"Q3 2026 Revenue Review\", "
    "not the chat name or \"Document\").\n"
    "- Decks: enough slides to cover the topic properly (typically 6–12), each with 3–6 substantive, specific "
    "bullets (real facts/figures/examples, not one-word stubs) and a 1–2 sentence \"notes\" field.\n"
    "- Documents: full, well-developed paragraphs under each heading — real explanation and detail, not single "
    "sentences; use bullets/tables where they help.\n"
    "- Sheets: real column headers and complete, realistic data rows.\n"
    "Be accurate; do not invent figures you can't support. Orrery builds the actual file from this JSON and shows "
    "Preview/Download - the JSON is never shown to the user. Only write file-generating code if the user "
    "explicitly asks for the code itself."
)
CONTEXT_INPUT_SHARE = 0.75
DEFAULT_CONTEXT_WINDOW = 1_000_000


def _title_from(text: str) -> str:
    words = text.strip().split()
    title = " ".join(words[:8])
    return (title[:80] or "New chat").strip()


def _pdf_text(data_url: str) -> str:
    """Extract text from a base64 data-URL PDF locally (no cloud parsing)."""
    try:
        b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
        raw = base64.b64decode(b64)
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
        return "\n\n".join(t for t in pages if t).strip()
    except Exception:  # noqa: BLE001 — a bad/encrypted PDF shouldn't break the turn
        return ""


def _content_parts(text: str, attachments: list[dict]) -> tuple[str, list[dict]]:
    """Split a turn into (combined_text, image_blocks): text/PDF files are inlined as text,
    images become blocks and also leave a textual marker so later turns know they existed."""
    text_parts = [text] if text else []
    images = []
    for a in attachments:
        content = a.get("content")
        if not content:
            continue
        kind = a.get("kind")
        name = a.get("name", "file")
        if kind == "image":
            images.append({"type": "image_url", "image_url": {"url": content}})
            text_parts.append(f"\n\n[image attached: {name}]")
        elif kind == "pdf":
            extracted = _pdf_text(content)
            body = extracted or "[No extractable text — may be a scanned/image-only PDF.]"
            text_parts.append(f"\n\n--- {name} (PDF) ---\n{body}")
        else:  # text file — inline its contents
            text_parts.append(f"\n\n--- {name} ---\n{content}")
    return "".join(text_parts).strip(), images


def _build_user_content(text: str, attachments: list[dict]):
    """Multimodal content for this turn: images as blocks, text/PDF inlined; str when no images."""
    combined, images = _content_parts(text, attachments)
    if images:
        blocks = []
        if combined:
            blocks.append({"type": "text", "text": combined})
        return blocks + images
    return combined


def _history_text(text: str, attachments: list[dict]) -> str:
    """Full text persisted as a message's context, so file/PDF text survives later turns."""
    combined, _images = _content_parts(text, attachments)
    return combined


def _db_content(text: str, attachments: list[dict]) -> str:
    """What the bubble shows — the text plus a compact note of attachments (not the file dump)."""
    if not attachments:
        return text
    note = "📎 " + ", ".join(a.get("name", "file") for a in attachments)
    return f"{text}\n\n{note}".strip() if text else note


def _content_token_estimate(content) -> int:
    """Estimate tokens without sending content anywhere or adding a tokenizer dependency."""
    if isinstance(content, str):
        return max(1, (len(content) + 3) // 4)
    if isinstance(content, list):
        tokens = 0
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                tokens += _content_token_estimate(block.get("text", ""))
            elif block.get("type") == "image_url":
                tokens += 1024
        return max(1, tokens)
    return 1


def _message_groups(messages: list[dict]) -> list[list[dict]]:
    """Group each user turn with the replies that follow it so trimming keeps turns intact."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    for message in messages:
        if message.get("role") == "user" and current:
            groups.append(current)
            current = [message]
        else:
            current.append(message)
    if current:
        groups.append(current)
    return groups


def _limit_messages(
    messages: list[dict],
    context_window: int | None,
    system_prompt: str | None = None,
) -> list[dict]:
    """Keep the newest complete turns within the per-chat approximate token budget."""
    if context_window is None:
        return messages

    formatted_prompt = (
        f"{FORMAT_INSTRUCTIONS}\n\n{system_prompt}" if system_prompt else FORMAT_INSTRUCTIONS
    )
    input_budget = max(
        1,
        int(context_window * CONTEXT_INPUT_SHARE) - _content_token_estimate(formatted_prompt),
    )
    selected: list[list[dict]] = []
    used = 0
    for group in reversed(_message_groups(messages)):
        group_tokens = sum(
            4 + _content_token_estimate(message.get("content", "")) for message in group
        )
        if selected and used + group_tokens > input_budget:
            break
        selected.append(group)
        used += group_tokens

    return [message for group in reversed(selected) for message in group]


def _effective_context_window(context_window: int | None) -> int:
    return context_window or DEFAULT_CONTEXT_WINDOW


def _message_artifacts(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


async def list_conversations() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(select(Conversation).order_by(Conversation.updated_at.desc()))
        ).scalars().all()
        return [
            {"id": str(c.id), "title": c.title, "model": c.model, "updated_at": c.updated_at.isoformat()}
            for c in rows
        ]


async def create_conversation(
    model: str,
    system_prompt: str | None,
    effort: str | None = None,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> dict:
    async with get_sessionmaker()() as s:
        conv = Conversation(
            model=model,
            system_prompt=system_prompt or None,
            effort=effort or None,
            context_window=context_window,
        )
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        return {"id": str(conv.id), "title": conv.title, "model": conv.model,
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
        await s.commit()
        await s.refresh(conv)
        return {"id": str(conv.id), "title": conv.title, "model": conv.model,
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


def _latest_user_text(messages: list[dict]) -> str:
    """The most recent user turn's text — used to select which skills to load."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return ""


_HIGH_EFFORT_INTENT = re.compile(
    r"\b(code|coding|function|script|program|app|web\s*app|website|web\s*page|frontend|backend|"
    r"component|api|endpoint|algorithm|data\s*structure|implement|refactor|debug|optimi[sz]e|"
    r"svg|diagram|flow\s*chart|chart|infographic|mockup|prototype|architecture|schema|query|regex|"
    r"build\s+(a|an|me)|design\s+(a|an)|create\s+(a|an)|make\s+(a|an)|write\s+(a|an|me))\b",
    re.IGNORECASE,
)


def _wants_high_effort(text: str) -> bool:
    """Code/creative/build requests deserve deliberate, high-effort reasoning."""
    return bool(text and _HIGH_EFFORT_INTENT.search(text))


async def _generate(cid: uuid.UUID, model: str, system_prompt: str | None, messages: list[dict], effort: str | None = None, untrusted_context: str | None = None) -> AsyncIterator[dict]:
    """Stream the assistant reply and persist it (saved even if the client cancels)."""
    parts: list[str] = []
    message_id: str | None = None
    usage_out: dict = {}
    user_text = _latest_user_text(messages)
    formatted_prompt = build_system_prompt(  # explicit authority layers (app > skills > user > untrusted)
        app_rules=FORMAT_INSTRUCTIONS,
        skills_block=skills.skills_prompt(user_text),
        user_preferences=system_prompt,
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


async def _deliver_docspec(cid: uuid.UUID, model: str, request: str, system_prompt: str | None, effort: str | None, untrusted_context: str | None = None) -> AsyncIterator[dict]:
    """Reliable fallback when code-execution misses: ask for a structured spec, then build the
    file deterministically with docgen and deliver it. Yields nothing if no spec comes back."""
    yield {"status": "Creating the file structure…"}
    instructions = build_system_prompt(
        app_rules=FORMAT_INSTRUCTIONS, user_preferences=system_prompt, untrusted_context=untrusted_context,
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
    rag_context = None                 # retrieved docs — passed separately as UNTRUSTED context
    if collection_id and user_content.strip():
        block, sources = await _rag_context(model, collection_id, user_content)
        if block:
            rag_context = block
            yield {"sources": sources}
            yield reasoning_event("Preparing context", f"Loaded {len(sources)} document(s) from your collection to answer from.")

    plan = taskrouter.plan(user_content, has_attachments=bool(attachments))
    if plan.route != "chat" or attachments:
        yield reasoning_event("Planning task", f"{plan.label}: {plan.detail}")

    if plan.route == "image" and not attachments:
        async for ev in _deliver_code_image(cid, model, user_content, gen_system, effort):
            yield ev
        return

    if plan.route == "audio" and plan.unavailable_reason:
        message = plan.unavailable_reason
        message_id = await _persist_assistant(cid, message, model)
        yield {"delta": message}
        if message_id:
            yield {"message_id": message_id}
        yield {"done": True}
        return

    if plan.route == "project" and plan.unavailable_reason:
        message = plan.unavailable_reason
        message_id = await _persist_assistant(cid, message, model)
        yield {"delta": message}
        if message_id:
            yield {"message_id": message_id}
        yield {"done": True}
        return

    # File generation routing: deterministic `docgen` first for normal documents; the sandboxed
    # code path only when the router selects artifacts that need computation, visuals, or audio.
    if plan.route == "file":
        use_sandbox = plan.uses_sandbox and sandbox.image_ready()
        if use_sandbox:
            yield reasoning_event("Selected generation path", "Sandboxed code execution (charts, images, or computed files).")
            result = None
            async for ev in filegen.run(model, user_content, gen_system, effort, rag_context):
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
                    return
            # sandbox missed → fall through to the deterministic builder so we never come up empty
        else:
            yield reasoning_event("Selected generation path", "Deterministic document builder.")
        delivered = False
        async for ev in _deliver_docspec(cid, model, user_content, gen_system, effort, rag_context):
            if "files" in ev:
                delivered = True
            yield ev
        if delivered:
            return
        yield {"status": ""}  # clear the progress note before the plain fallback reply streams

    budget_system = (gen_system or "") + (f"\n\n{rag_context}" if rag_context else "")  # keep token budget honest
    messages = _limit_messages(messages, context_window, budget_system)
    async for event in _generate(cid, model, gen_system, messages, effort, rag_context):
        yield event


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

    messages = _limit_messages(messages, context_window, system_prompt)
    async for event in _generate(cid, model, system_prompt, messages, effort):
        yield event
