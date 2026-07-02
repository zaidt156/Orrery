"""On-demand answer evaluation: regenerate the same turn with other models, then have a judge model
score every candidate (accuracy / completeness / clarity) so the user can pick the best answer.

Candidates are shown to the judge anonymously (A, B, C…) so provider/brand names can't bias scores.
The judge's output is advisory UI metadata — adopting a candidate is an explicit user action that
rewrites the assistant message through the normal persistence path. Runs only when the user asks
(this is a per-message action, not an always-on pipeline)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import string
import uuid

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import Conversation, Message
from backend.features import team
from backend.features.prompting import strip_think
from backend.providers import ai

log = logging.getLogger("orrery.evaluate")

MAX_EXTRA_CANDIDATES = 3
_CANDIDATE_CHARS = 7000   # per-candidate cap fed to the judge
_GEN_TIMEOUT = 180

_JUDGE_PROMPT = """You are an impartial evaluator. Below is a user's request and {n} candidate answers
labeled {labels}. Judge each answer on how well it serves the user.

Score each candidate 0-10 on: accuracy (correct, no fabrication), completeness (fully addresses the
request), clarity (well-organized, easy to use). Then give an overall 0-10 and one short comment.

Output ONLY a JSON object, no prose:
{{"scores": [{{"candidate": "A", "accuracy": 0, "completeness": 0, "clarity": 0, "overall": 0,
             "comment": "..."}}], "best": "A"}}

USER REQUEST:
{question}

{candidates}"""


async def _collect(model: str, messages: list[dict], system_prompt: str | None, effort: str | None) -> str:
    parts: list[str] = []
    async for delta in ai.stream_chat(model, messages, system_prompt, effort):
        if not isinstance(delta, ai.ReasoningDelta):
            parts.append(str(delta))
    return strip_think("".join(parts)).strip()


async def _load_turn(cid: uuid.UUID, mid: uuid.UUID) -> tuple[Conversation, Message, list[dict]] | None:
    """The conversation, the target assistant message, and the model-bound history before it."""
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        if conv is None or (owner is not None and conv.owner_id != owner):
            return None
        target = await s.get(Message, mid)
        if target is None or target.conversation_id != cid or target.role != "assistant":
            return None
        rows = (
            await s.execute(
                select(Message)
                .where(Message.conversation_id == cid, Message.created_at < target.created_at)
                .order_by(Message.created_at)
            )
        ).scalars().all()
        history = [{"role": m.role, "content": m.context or m.content} for m in rows]
        return conv, target, history


async def evaluate(conv_id: str, message_id: str, candidate_models: list[str], judge_model: str) -> dict:
    """Generate alternates, judge all candidates anonymously, return them ranked."""
    loaded = await _load_turn(uuid.UUID(conv_id), uuid.UUID(message_id))
    if loaded is None:
        raise ValueError("Message not found.")
    conv, target, history = loaded
    if not history or history[-1]["role"] != "user":
        raise ValueError("This message has no user prompt before it to re-answer.")
    if not judge_model:
        raise ValueError("Pick a judge model.")

    question = str(history[-1]["content"])
    candidates: list[dict] = [{"model": target.model or conv.model, "text": target.content, "current": True}]

    async def _one(m: str) -> dict:
        try:
            text = await asyncio.wait_for(_collect(m, history, conv.system_prompt, conv.effort), timeout=_GEN_TIMEOUT)
            return {"model": m, "text": text or "(empty answer)", "current": False}
        except Exception as exc:  # noqa: BLE001 — one failed candidate shouldn't sink the comparison
            return {"model": m, "text": "", "current": False, "error": str(exc)[:200]}

    extra = [m for m in candidate_models if m][:MAX_EXTRA_CANDIDATES]
    candidates += list(await asyncio.gather(*[_one(m) for m in extra])) if extra else []
    usable = [c for c in candidates if c.get("text")]
    if len(usable) < 2:
        raise ValueError("Fewer than two candidates produced an answer — nothing to compare.")

    letters = list(string.ascii_uppercase)
    for i, c in enumerate(usable):
        c["letter"] = letters[i]
    blocks = "\n\n".join(
        f"CANDIDATE {c['letter']}:\n{c['text'][:_CANDIDATE_CHARS]}" for c in usable
    )
    prompt = _JUDGE_PROMPT.format(
        n=len(usable), labels=", ".join(c["letter"] for c in usable),
        question=question[:_CANDIDATE_CHARS], candidates=blocks,
    )
    verdict_raw = await _collect(judge_model, [{"role": "user", "content": prompt}], None, "high")
    match = re.search(r"\{.*\}", verdict_raw, re.DOTALL)
    scores: dict[str, dict] = {}
    best = ""
    if match:
        try:
            data = json.loads(match.group(0))
            for srow in data.get("scores", []):
                if isinstance(srow, dict) and srow.get("candidate"):
                    scores[str(srow["candidate"]).strip().upper()] = srow
            best = str(data.get("best", "")).strip().upper()
        except (ValueError, TypeError):
            pass
    for c in usable:
        srow = scores.get(c["letter"], {})
        c["scores"] = {
            "accuracy": srow.get("accuracy"), "completeness": srow.get("completeness"),
            "clarity": srow.get("clarity"), "overall": srow.get("overall"),
        }
        c["comment"] = str(srow.get("comment", "") or "")[:400]
    usable.sort(key=lambda c: (c["scores"].get("overall") is not None, c["scores"].get("overall") or 0), reverse=True)
    failed = [c for c in candidates if not c.get("text")]
    return {
        "question": question[:2000],
        "judge": judge_model,
        "judged": bool(scores),
        "best": best or (usable[0]["letter"] if usable else ""),
        "candidates": usable,
        "failed": [{"model": c["model"], "error": c.get("error", "no answer")} for c in failed],
    }


async def adopt(conv_id: str, message_id: str, text: str, model: str = "") -> bool:
    """Replace the assistant message with the chosen candidate (explicit user action)."""
    if not (text or "").strip():
        return False
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        if conv is None or (owner is not None and conv.owner_id != owner):
            return False
        row = await s.get(Message, uuid.UUID(message_id))
        if row is None or row.conversation_id != conv.id or row.role != "assistant":
            return False
        row.content = text.strip()
        if model:
            row.model = model[:120]
        await s.commit()
        return True
