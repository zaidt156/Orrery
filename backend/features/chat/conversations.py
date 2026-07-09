"""Conversation CRUD + per-message reasoning/attachment persistence.

Team mode: every read/write checks ownership (_owned_by) — a member can never see, open, or delete
another user's chats (security enforced here, not in the UI).
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import Conversation, Message, Project
from backend.features import rag, team
from backend.features.chat import versioning
from backend.features.chat_context import (
    DEFAULT_CONTEXT_WINDOW, _effective_context_window, _message_artifacts,
)
from backend.providers import ai


def _owned_by(row, owner_id: str | None) -> bool:
    return owner_id is None or getattr(row, "owner_id", None) == owner_id


async def can_access_conversation(conv_id: str) -> bool:
    """True when the current solo/team user can access this conversation.

    Raises PermissionError for a locked team client via team.current_owner_id().
    """
    try:
        cid = uuid.UUID(conv_id)
    except ValueError:
        return False
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        return bool(conv is not None and _owned_by(conv, owner))


async def list_conversations() -> list[dict]:
    owner = await team.current_owner_id()  # team mode: only this user's chats; solo: None (all)
    async with get_sessionmaker()() as s:
        q = select(Conversation).order_by(Conversation.updated_at.desc())
        if owner is not None:
            q = q.where(Conversation.owner_id == owner)
        rows = (await s.execute(q)).scalars().all()
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
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        project_uuid = None
        if project_id:
            project = await s.get(Project, uuid.UUID(project_id))
            if project is None or not _owned_by(project, owner):
                raise ValueError("Project not found")
            project_uuid = project.id
        conv = Conversation(
            project_id=project_uuid,
            model=model,
            system_prompt=system_prompt or None,
            effort=effort or None,
            context_window=min(int(context_window), ai.model_context_window(model)) if context_window else context_window,
            owner_id=owner,
        )
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        return {"id": str(conv.id), "project_id": str(conv.project_id) if conv.project_id else None,
                "title": conv.title, "model": conv.model,
                "system_prompt": conv.system_prompt, "effort": conv.effort,
                "context_window": _effective_context_window(conv.context_window), "messages": []}


async def get_conversation(conv_id: str) -> dict | None:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        if conv is None:
            return None
        if owner is not None and conv.owner_id != owner:  # team mode: can't open another user's chat
            return None
        msgs = (
            await s.execute(
                select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
            )
        ).scalars().all()
        # The visible thread is the ACTIVE path through the version tree; each message carries its
        # ‹ › switcher metadata (1-based index, sibling count, sibling ids in time order).
        path = versioning.active_path(msgs)
        vmap = versioning.version_map(msgs)
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
                    "reasoning": _load_reasoning(m.reasoning),
                    "version": vmap.get(str(m.id), {}).get("version", 1),
                    "versions": vmap.get(str(m.id), {}).get("versions", 1),
                    "siblings": vmap.get(str(m.id), {}).get("siblings", [str(m.id)]),
                }
                for m in path
            ],
        }


def _load_reasoning(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def attachment_text(conv_id: str, source: str) -> str | None:
    """Extracted text of an uploaded attachment (from the chat's index) for the preview panel."""
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        if conv is None or not _owned_by(conv, owner) or not conv.collection_id:
            return None
        collection = str(conv.collection_id)
    text = await rag.document_text(collection, source)
    return text or None


async def save_reasoning(conv_id: str, message_id: str, reasoning: dict) -> bool:
    """Persist the reasoning-panel snapshot for one assistant message so it survives reloads."""
    try:
        payload = json.dumps(reasoning)[:200_000]  # bounded; this is UI metadata, not the answer
    except (TypeError, ValueError):
        return False
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        message = await s.get(Message, uuid.UUID(message_id))
        if message is None or str(message.conversation_id) != str(uuid.UUID(conv_id)):
            return False
        conv = await s.get(Conversation, message.conversation_id)
        if conv is None or not _owned_by(conv, owner):
            return False
        message.reasoning = payload
        await s.commit()
        return True


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
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        if conv is None:
            return None
        if not _owned_by(conv, owner):
            return None
        if model is not _UNSET and model:
            conv.model = model
        if system_prompt is not _UNSET:
            conv.system_prompt = (system_prompt or None)
        if effort is not _UNSET:
            conv.effort = (effort or None)
        if context_window is not _UNSET:
            conv.context_window = context_window
        if conv.context_window:  # clamp to the (possibly new) model's real maximum
            conv.context_window = min(int(conv.context_window), ai.model_context_window(conv.model))
        if project_id is not _UNSET:
            if project_id:
                project = await s.get(Project, uuid.UUID(project_id))
                if project is None or not _owned_by(project, owner):
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
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        if conv is None:
            return False
        if owner is not None and conv.owner_id != owner:  # team mode: can't delete another user's chat
            return False
        await s.delete(conv)
        await s.commit()
        return True
