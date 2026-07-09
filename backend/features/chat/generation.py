"""Plain streaming generation: one model call, ThinkStream-filtered, persisted even on cancel/fail."""
from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from backend.core.observability import log_event
from backend.features import events as stream_events
from backend.features import filegen, skills
from backend.features.chat import persistence
from backend.features.chat_context import _latest_user_text, _wants_high_effort
from backend.features.prompting import FORMAT_INSTRUCTIONS, build_system_prompt, strip_think as _strip_think
from backend.features.reasoning_trace import ThinkStream
from backend.providers import ai

_log = logging.getLogger("orrery.chat")


async def _generate(
    cid: uuid.UUID,
    model: str,
    system_prompt: str | None,
    messages: list[dict],
    effort: str | None = None,
    untrusted_context: str | None = None,
    trusted_context: str | None = None,
    branch_from: uuid.UUID | None = None,
) -> AsyncIterator[dict]:
    """Stream the assistant reply and persist it (saved even if the client cancels)."""
    parts: list[str] = []
    message_id: str | None = None
    usage_out: dict = {}
    user_text = _latest_user_text(messages)
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
    think = ThinkStream()  # strips provider/inline hidden reasoning; public trace is emitted separately
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
                yield stream_events.delta(answer)
        tail, events = think.finish()
        for ev in events:
            yield ev
        if tail:
            parts.append(tail)
            yield stream_events.delta(tail)
    except ai.MissingKeyError as exc:
        yield stream_events.missing_key(exc.provider)
        return
    except Exception as exc:  # noqa: BLE001 — already sanitized by ai.stream_chat
        log_event(_log, "chat_generate_failed", model=model, error=type(exc).__name__)
        yield stream_events.error(str(exc))
        # Persist the failed turn too — otherwise the error (and any partial answer) vanishes as soon
        # as the user switches chats, leaving a user message with no reply and a hole in the context.
        failed_text = _strip_think("".join(parts)).strip()
        error_note = f"⚠️ The model call failed: {exc}"
        failed_text = f"{failed_text}\n\n{error_note}" if failed_text else error_note
        message_id = await persistence._persist_assistant(cid, failed_text, model, branch_from=branch_from)
        parts.clear()  # already persisted with the error note; don't re-persist in finally
        yield stream_events.message_id(message_id)
        return
    finally:
        if parts:  # runs on normal completion AND on client-cancel (GeneratorExit)
            message_id = await persistence._persist_assistant(cid, _strip_think("".join(parts)), model, branch_from=branch_from)
    if message_id:
        yield stream_events.message_id(message_id)
    if usage_out.get("tokens_out") or usage_out.get("tokens_in"):
        # exact per-message token count (API/custom routes report it); the UI shows a live
        # estimate during streaming and replaces it with this exact count on completion
        yield stream_events.message_usage(
            usage_out.get("tokens_in"),
            usage_out.get("tokens_out"),
            usage_out.get("pricing_known", True),
        )
    if usage_out.get("cost") is not None and (usage_out.get("tokens_out") or usage_out.get("tokens_in")):
        from backend.features import usage as usage_mod
        await usage_mod.record(usage_out["provider"], usage_out["model"], usage_out["tokens_in"], usage_out["tokens_out"], usage_out["cost"])
        yield stream_events.usage(await usage_mod.summary())  # live meter update
    yield stream_events.done()
