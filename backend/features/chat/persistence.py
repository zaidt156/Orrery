"""Persisting assistant replies — including turning complete HTML documents into previewable files."""
from __future__ import annotations

import datetime
import json
import re
import uuid

from sqlalchemy import select, update

from backend.core.database import get_sessionmaker
from backend.core.models import Conversation, Message
from backend.features import files as file_library
from backend.features.chat import versioning

_HTML_DOC = re.compile(r"(<!doctype html.*?</html\s*>|<html[\s>].*?</html\s*>)", re.IGNORECASE | re.DOTALL)


def _html_artifact_from_reply(text: str) -> tuple[str, list[dict]] | None:
    """A complete HTML document inside a reply becomes a real previewable file (like documents),
    and the raw dump is replaced by a short line — users never asked to read source code."""
    match = _HTML_DOC.search(text or "")
    if not match or len(match.group(1)) < 700:
        return None
    html_doc = match.group(1)
    title = re.search(r"<title>(.*?)</title>", html_doc, re.IGNORECASE | re.DOTALL)
    slug = re.sub(r"[^a-z0-9]+", "-", (title.group(1).strip() if title else "page").lower()).strip("-")[:60] or "page"
    try:
        stored = file_library.store(f"{slug}.html", "text/html", html_doc.encode("utf-8"))
    except ValueError:
        return None
    # strip the fenced/naked dump around the document from the visible reply
    cleaned = _HTML_DOC.sub("", text)
    cleaned = re.sub(r"```(?:html)?\s*```", "", cleaned).strip()
    if not cleaned:
        cleaned = f"Built **{title.group(1).strip() if title else 'your page'}** — preview or download it below."
    return cleaned, [{"kind": "file", **stored}]


async def _deactivate_children(s, cid: uuid.UUID, parent_id: uuid.UUID | None) -> None:
    """Take every existing sibling under this parent off the active path (the newcomer replaces them)."""
    cond = Message.parent_id.is_(None) if parent_id is None else Message.parent_id == parent_id
    await s.execute(
        update(Message).where(Message.conversation_id == cid, cond).values(active=False)
    )


async def _persist_assistant(
    cid: uuid.UUID,
    text: str,
    model: str,
    artifacts: list[dict] | None = None,
    *,
    branch_from: uuid.UUID | None = None,
) -> str:
    """Save the reply. Default: thread onto the active path's tip (a normal turn). With branch_from
    (regenerate): save as the new ACTIVE sibling under that message, keeping the old reply switchable."""
    if not artifacts:
        converted = _html_artifact_from_reply(text)
        if converted:
            text, artifacts = converted
    async with get_sessionmaker()() as s:
        if branch_from is not None:
            await _deactivate_children(s, cid, branch_from)
            parent_id = branch_from
        else:
            rows = (
                await s.execute(select(Message).where(Message.conversation_id == cid))
            ).scalars().all()
            tip = versioning.leaf_id(rows)  # normally the user turn just saved
            parent_id = uuid.UUID(tip) if tip else None
        message = Message(
            conversation_id=cid,
            role="assistant",
            content=text,
            model=model,
            artifacts=json.dumps(artifacts) if artifacts else None,
            parent_id=parent_id,
            active=True,
        )
        s.add(message)
        conv = await s.get(Conversation, cid)
        if conv is not None:
            conv.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await s.commit()
        await s.refresh(message)
        return str(message.id)
