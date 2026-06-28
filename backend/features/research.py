"""Deep Research: a multi-step research workflow that produces a cited report.

Flow: decompose the question into focused sub-questions -> gather evidence for each (from the user's
uploaded documents via RAG today; provider web search is the next increment) -> synthesize one
structured report that cites its evidence with [n] markers and a Sources list.

It is model-agnostic (works on any provider/connection) and emits the same two-layer activity trace
as the rest of chat. Gathered document/web text is always treated as UNTRUSTED context: it is evidence
to cite, never instructions to follow.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable

from backend.features import rag, websearch
from backend.features.prompting import FORMAT_INSTRUCTIONS, RESEARCH_PROMPT, build_system_prompt, strip_think
from backend.features.reasoning_trace import ThinkStream
from backend.providers import ai

MAX_SUBQUESTIONS = 6
PASSAGES_PER_SUBQUESTION = 4
_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


async def _plan(model: str, question: str, effort: str | None) -> list[str]:
    """Ask the model for focused sub-questions; degrade to the original question on any failure."""
    instruction = (
        "Break this research question into 3-6 focused, non-overlapping sub-questions that together "
        "answer it well. Return ONLY a JSON array of short strings, nothing else.\n\nQuestion: " + question
    )
    parts: list[str] = []
    think = ThinkStream()
    try:
        async for delta in ai.stream_chat(model, [{"role": "user", "content": instruction}], None, effort):
            if isinstance(delta, ai.ReasoningDelta):
                continue
            answer, _ = think.feed(delta)
            parts.append(answer)
        tail, _ = think.finish()
        parts.append(tail)
        match = _JSON_ARRAY.search("".join(parts))
        if match:
            items = json.loads(match.group(0))
            subqs = [str(i).strip() for i in items if str(i).strip()][:MAX_SUBQUESTIONS]
            if subqs:
                return subqs
    except Exception:  # noqa: BLE001 — planning is best-effort; fall back to a single pass
        pass
    return [question]


def _build_evidence(findings: list[tuple[str, list[dict]]]) -> tuple[str, list[str]]:
    """Number every passage [n] and return (evidence_block, ordered_source_labels)."""
    lines: list[str] = []
    sources: list[str] = []
    n = 0
    for subq, passages in findings:
        for p in passages:
            n += 1
            label = p.get("source") or "document"
            sources.append(label)
            lines.append(f"[{n}] (source: {label}) for sub-question \"{subq}\":\n{p.get('content', '').strip()}")
    return "\n\n".join(lines), sources


def _synth_instruction(question: str, source_count: int) -> str:
    if source_count:
        return (
            f"Write a thorough, well-structured research report answering: {question}\n\n"
            f"Use the numbered evidence in the untrusted context. Cite claims with [n] markers that refer to "
            f"that evidence, and end with a 'Sources' section listing each [n]. Where the evidence is silent, "
            f"you may use general knowledge but say so plainly and do not fabricate citations."
        )
    return (
        f"Write a thorough, well-structured research report answering: {question}\n\n"
        f"No source documents were available, so answer from general knowledge. State this limitation at the "
        f"top, flag anything uncertain, and do not invent citations."
    )


async def run(
    model: str,
    question: str,
    *,
    collection_id: str | None,
    effort: str | None,
    trusted_context: str | None,
    trace,
    persist: Callable[[str, list[dict] | None], Awaitable[str]],
    web_search: bool = True,
) -> AsyncIterator[dict]:
    """Decompose -> gather (documents + web) -> synthesize a cited report. Yields chat events."""
    yield trace.step("Planning research", "Breaking the question into focused sub-questions.",
                     kind="route", status="running", phase="plan")
    subqs = await _plan(model, question, effort)
    yield trace.step("Research plan ready", "; ".join(subqs), kind="route", status="done", phase="plan",
                     metadata={"subquestions": subqs})

    findings: list[tuple[str, list[dict]]] = []
    total_passages = 0
    for index, subq in enumerate(subqs):
        yield trace.step("Researching", subq, kind="context", status="running", phase="gather",
                         metadata={"step": index + 1, "of": len(subqs)})
        passages: list[dict] = []
        if collection_id:
            try:
                passages = await rag.search(collection_id, subq, k=PASSAGES_PER_SUBQUESTION)
            except Exception:  # noqa: BLE001 — a retrieval miss shouldn't abort the whole report
                passages = []
        if web_search:
            try:
                hits = await websearch.search(subq, max_results=4)
            except Exception:  # noqa: BLE001 — web is best-effort
                hits = []
            for h in hits:
                body = f"{h.get('title', '')} — {h.get('snippet', '')}".strip(" —")
                if body:
                    passages.append({"source": h.get("url") or h.get("title") or "web", "content": body})
        findings.append((subq, passages))
        total_passages += len(passages)
        yield trace.step("Gathered evidence", f"{len(passages)} passage(s) for: {subq}",
                         kind="context", status="done", phase="gather", metadata={"passages": len(passages)})

    evidence, sources = _build_evidence(findings)
    if sources:
        # de-duplicate for the user-facing source list shown in the trace
        unique_sources = list(dict.fromkeys(sources))
        yield {"sources": unique_sources}

    yield trace.step("Writing report",
                     f"Synthesizing a cited report from {total_passages} passage(s) across {len(subqs)} sub-question(s).",
                     kind="work", status="running", phase="execute")
    formatted_prompt = build_system_prompt(
        app_rules=FORMAT_INSTRUCTIONS,
        feature_rules=RESEARCH_PROMPT,
        trusted_context=trusted_context,
        untrusted_context=evidence or None,
    )
    usage_out: dict = {}
    parts: list[str] = []
    think = ThinkStream()
    try:
        async for delta in ai.stream_chat(
            model, [{"role": "user", "content": _synth_instruction(question, len(sources))}],
            formatted_prompt, effort, usage_out,
        ):
            if isinstance(delta, ai.ReasoningDelta):
                think.feed_reasoning(str(delta))
                continue
            answer, _ = think.feed(delta)
            if answer:
                parts.append(answer)
                yield {"delta": answer}
        tail, _ = think.finish()
        if tail:
            parts.append(tail)
            yield {"delta": tail}
    except ai.MissingKeyError as exc:
        yield {"error": f"No API key for {exc.provider}. Add it in Settings."}
        return
    except Exception as exc:  # noqa: BLE001 — provider errors already sanitized upstream
        yield {"error": str(exc)}
        return

    final_text = strip_think("".join(parts)).strip() or "I couldn't produce a report for that."
    message_id = await persist(final_text, None)
    if message_id:
        yield {"message_id": message_id}
    if usage_out.get("tokens_in") or usage_out.get("tokens_out"):
        yield {"message_usage": {
            "in": usage_out.get("tokens_in") or 0,
            "out": usage_out.get("tokens_out") or 0,
            "pricing_known": usage_out.get("pricing_known", True),
        }}
    if usage_out.get("cost") is not None and (usage_out.get("tokens_out") or usage_out.get("tokens_in")):
        from backend.features import usage as usage_mod
        await usage_mod.record(usage_out["provider"], usage_out["model"],
                               usage_out["tokens_in"], usage_out["tokens_out"], usage_out["cost"])
        yield {"usage": await usage_mod.summary()}
    yield {"done": True}
