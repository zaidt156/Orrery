from __future__ import annotations

import base64
import datetime
import io
import json
import mimetypes
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import Conversation, Message
from backend.features import code_images, filegen, rag, sandbox, skills
from backend.features import files as file_library
from backend.providers import ai
from backend.security import privacy

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
    "documents/PDF/Word/Markdown/text/HTML. Design it like a real artifact: genuine slide titles with concise "
    "bullets for decks, real column headers and data rows for sheets, proper headings and paragraphs for "
    "documents. Orrery builds the actual file from this JSON and shows Preview/Download - the JSON is never "
    "shown to the user. Only write file-generating code if the user explicitly asks for the code itself."
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


async def _generate(cid: uuid.UUID, model: str, system_prompt: str | None, messages: list[dict], effort: str | None = None) -> AsyncIterator[dict]:
    """Stream the assistant reply and persist it (saved even if the client cancels)."""
    parts: list[str] = []
    message_id: str | None = None
    usage_out: dict = {}
    base_prompt = f"{FORMAT_INSTRUCTIONS}\n\n{system_prompt}" if system_prompt else FORMAT_INSTRUCTIONS
    skill_block = skills.skills_prompt(_latest_user_text(messages))  # inject matching skills for this turn
    formatted_prompt = f"{base_prompt}\n\n{skill_block}" if skill_block else base_prompt
    try:
        async for delta in ai.stream_chat(model, messages, formatted_prompt, effort, usage_out):
            if isinstance(delta, ai.ReasoningDelta):
                yield {"reasoning": str(delta)}  # the model's thinking — shown live, not saved
                continue
            parts.append(delta)
            yield {"delta": delta}
    except ai.MissingKeyError as exc:
        yield {"error": f"No API key for {exc.provider}. Add it in Settings."}
        return
    except Exception as exc:  # noqa: BLE001 — already sanitized by ai.stream_chat
        yield {"error": str(exc)}
        return
    finally:
        if parts:  # runs on normal completion AND on client-cancel (GeneratorExit)
            message_id = await _persist_assistant(cid, "".join(parts), model)
    if message_id:
        yield {"message_id": message_id}
    if usage_out.get("cost") is not None and (usage_out.get("tokens_out") or usage_out.get("tokens_in")):
        from backend.features import usage as usage_mod
        await usage_mod.record(usage_out["provider"], usage_out["model"], usage_out["tokens_in"], usage_out["tokens_out"], usage_out["cost"])
        yield {"usage": await usage_mod.summary()}  # live meter update
    yield {"done": True}


async def _rag_context(model: str, collection_id: str, query: str) -> tuple[str | None, list[str]]:
    """Retrieve top chunks, redact for cloud models, return (context_block, sources)."""
    try:
        results = await rag.search(collection_id, query, k=5)
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

    gen_system = system_prompt
    if collection_id and user_content.strip():
        block, sources = await _rag_context(model, collection_id, user_content)
        if block:
            preamble = (
                "Use the following context from the user's documents to answer. "
                "If the answer isn't in the context, say so. Cite sources by their [name].\n\n"
            )
            gen_system = (f"{system_prompt}\n\n" if system_prompt else "") + preamble + block
            yield {"sources": sources}

    # File generation: the model WRITES CODE that the sandbox runs (richer output than the
    # structured builder). Falls through to the structured/markdown reply if the sandbox is
    # unavailable or codegen fails.
    if filegen.wants_file(user_content) and sandbox.image_ready():
        result = None
        async for ev in filegen.run(model, user_content, gen_system, effort):
            if "status" in ev or "reasoning" in ev:
                yield ev
            elif "result" in ev:
                result = ev["result"]
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
        yield {"status": ""}  # clear the progress note before the fallback reply streams

    messages = _limit_messages(messages, context_window, gen_system)
    async for event in _generate(cid, model, gen_system, messages, effort):
        yield event


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
    yield {"status": "Rendering a safe SVG image..."}
    try:
        svg = await code_images.generate_svg(model, user_content, system_prompt, effort)
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
