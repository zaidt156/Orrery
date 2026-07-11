"""Learn durable facts about the user from chat turns — as LIFE.md PROPOSALS only.

Nothing here writes memory directly: every learning lands in the same hash-pinned proposal
queue the Settings page reviews, so the owner approves the exact diff (life.py security model).
A cheap heuristic gates the extra model call, and a cooldown keeps the queue quiet.
"""
from __future__ import annotations

import datetime
import json
import logging
import re

from backend.features import life

log = logging.getLogger("orrery")

# first-person signals that a message might carry something worth remembering
_PERSONAL_RX = re.compile(
    r"\b(i am|i'm|im\b|my name|call me|i work|i live|i prefer|i like|i love|i hate|i use|"
    r"i want you to|i need you to|always|never|remember|from now on|my company|my team|"
    r"my goal|my project)\b",
    re.IGNORECASE,
)
_SECTION = "## Learned from conversations"
_COOLDOWN = datetime.timedelta(minutes=10)
_last_proposal: dict[str | None, datetime.datetime] = {}


def worth_learning(user_text: str) -> bool:
    text = (user_text or "").strip()
    return bool(text) and len(text) <= 4000 and bool(_PERSONAL_RX.search(text))


def merge_facts(current: str, facts: list[str]) -> str | None:
    """Fold new facts under the learned-section header; None when nothing new survives."""
    lines: list[str] = []
    for fact in facts[:3]:
        text = str(fact or "").strip().strip("-• ").rstrip(".")
        if not text or len(text) > 280:
            continue
        line = f"- {text}."
        if text.lower() not in current.lower():
            lines.append(line)
    if not lines:
        return None
    block = "\n".join(lines)
    if _SECTION in current:
        return current.replace(_SECTION, f"{_SECTION}\n{block}", 1)
    return f"{current.rstrip()}\n\n{_SECTION}\n{block}\n"


def _parse_facts(raw: str) -> list[str]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    facts = data.get("facts") if isinstance(data, dict) else None
    return [f for f in facts if isinstance(f, str)] if isinstance(facts, list) else []


async def _extract(user_text: str, model: str) -> list[str]:
    from backend.providers import ai

    system = (
        "You maintain a user's private memory file. From the user's message, extract at most "
        "3 short durable facts about the USER themselves (identity, role, preferences, standing "
        "instructions). Ignore one-off task content. Reply with STRICT JSON only: "
        '{"facts": ["..."]} — an empty list if nothing is worth remembering for months.'
    )
    out: list[str] = []
    async for delta in ai.stream_chat(model, [{"role": "user", "content": user_text[:4000]}], system):
        out.append(delta)
    return _parse_facts("".join(out))


async def consider_turn(*, owner_id: str | None, user_text: str, model: str) -> None:
    """Fire-and-forget per chat turn. Must never raise into (or slow) the chat path."""
    try:
        if not model or not worth_learning(user_text):
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        last = _last_proposal.get(owner_id)
        if last is not None and now - last < _COOLDOWN:
            return
        pending = await life.list_proposals_for_owner(owner_id, status="pending")
        if any(p.get("source_id") == "chat-learning" for p in pending):
            return  # one chat-learning proposal in the queue at a time
        _last_proposal[owner_id] = now
        current = life.read_document(owner_id=owner_id).content
        merged = merge_facts(current, await _extract(user_text, model))
        if merged is None:
            return
        await life.propose_for_owner(
            merged,
            owner_id=owner_id,
            reason="Learned from a conversation — review and approve in Settings › Life Memory",
            source_type="system",
            source_id="chat-learning",
        )
        log.info("life_learn proposal created")
    except Exception:  # noqa: BLE001 — memory learning must never break a chat turn
        log.debug("life_learn skipped", exc_info=True)
