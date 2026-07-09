from __future__ import annotations

import datetime
import re
import uuid

from sqlalchemy import func, select

from backend.core.database import get_sessionmaker
from backend.core.models import Conversation, Project
from backend.features import rag, team

MAX_NAME = 160
MAX_DESCRIPTION = 2_000
MAX_INSTRUCTIONS = 8_000

_CREATE_PROJECT = re.compile(r"\b(create|start|set\s+up|make)\b", re.IGNORECASE)
_PROJECT_NAME_PATTERNS = (
    re.compile(
        r"\b(?:project\s+workspace|project|workspace|folder)\s+(?:called|named)\s+['\"]?(.+?)['\"]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:create|start|set\s+up|make)\s+(?:a\s+|an\s+|new\s+)*"
        r"(?:project\s+workspace|project|workspace|folder)(?:\s+(?:for|about|called|named))?\s+['\"]?(.+?)['\"]?$",
        re.IGNORECASE,
    ),
)


def _clean(value: str | None, limit: int) -> str:
    return " ".join((value or "").strip().split())[:limit]


def _clean_multiline(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text[:limit]


def name_from_prompt(text: str) -> str | None:
    """Extract a conservative project name from a clear project-creation request."""
    if not text or not _CREATE_PROJECT.search(text):
        return None
    for pattern in _PROJECT_NAME_PATTERNS:
        match = pattern.search(text.strip())
        if not match:
            continue
        name = _clean(match.group(1).strip(" .,:;!?\"'"), MAX_NAME)
        name = re.sub(r"^(the|a|an)\s+", "", name, flags=re.IGNORECASE)
        if len(name) >= 2:
            return name[:1].upper() + name[1:]
    return "New project"


def _uuid(value: str) -> uuid.UUID:
    return uuid.UUID(str(value))


def _project_dict(project: Project, conversation_count: int = 0) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description or "",
        "instructions": project.instructions or "",
        "conversation_count": conversation_count,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _conversation_dict(conv: Conversation) -> dict:
    return {
        "id": str(conv.id),
        "project_id": str(conv.project_id) if conv.project_id else None,
        "title": conv.title,
        "model": conv.model,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


def _owned_by(row, owner_id: str | None) -> bool:
    return owner_id is None or getattr(row, "owner_id", None) == owner_id


async def list_projects() -> list[dict]:
    owner = await team.current_owner_id()  # team mode: only this user's projects; solo: None (all)
    async with get_sessionmaker()() as s:
        pq = select(Project).order_by(Project.updated_at.desc(), Project.created_at.desc())
        if owner is not None:
            pq = pq.where(Project.owner_id == owner)
        projects = (await s.execute(pq)).scalars().all()
        cq = select(Conversation).where(Conversation.project_id.is_not(None))
        if owner is not None:
            cq = cq.where(Conversation.owner_id == owner)
        conversations = (
            await s.execute(
                cq.order_by(Conversation.project_id, Conversation.updated_at.desc())
            )
        ).scalars().all()
        grouped: dict[str, list[dict]] = {}
        for conv in conversations:
            grouped.setdefault(str(conv.project_id), []).append(_conversation_dict(conv))
        # Counts come straight from the already-loaded grouping — no separate GROUP BY round trip.
        out = []
        for project in projects:
            convs = grouped.get(str(project.id), [])
            item = _project_dict(project, len(convs))
            item["conversations"] = convs
            out.append(item)
        return out


async def create_project(name: str, description: str = "", instructions: str = "") -> dict:
    cleaned_name = _clean(name, MAX_NAME)
    if not cleaned_name:
        cleaned_name = "Untitled project"
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        project = Project(
            name=cleaned_name,
            description=_clean_multiline(description, MAX_DESCRIPTION) or None,
            instructions=_clean_multiline(instructions, MAX_INSTRUCTIONS) or None,
            owner_id=owner,
        )
        s.add(project)
        await s.commit()
        await s.refresh(project)
        return _project_dict(project, 0)


async def get_project(project_id: str) -> dict | None:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        project = await s.get(Project, _uuid(project_id))
        if project is None:
            return None
        if not _owned_by(project, owner):  # team mode: can't open another user's project
            return None
        cq = select(Conversation).where(Conversation.project_id == project.id)
        if owner is not None:
            cq = cq.where(Conversation.owner_id == owner)
        conversations = (
            await s.execute(
                cq.order_by(Conversation.updated_at.desc())
            )
        ).scalars().all()
        data = _project_dict(project, len(conversations))
        data["conversations"] = [_conversation_dict(conv) for conv in conversations]
        cid = str(project.collection_id) if project.collection_id else None
    data["files"] = await rag.documents(cid) if cid else []
    return data


async def update_project(
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    instructions: str | None = None,
) -> dict | None:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        project = await s.get(Project, _uuid(project_id))
        if project is None:
            return None
        if not _owned_by(project, owner):
            return None
        if name is not None:
            cleaned_name = _clean(name, MAX_NAME)
            if cleaned_name:
                project.name = cleaned_name
        if description is not None:
            project.description = _clean_multiline(description, MAX_DESCRIPTION) or None
        if instructions is not None:
            project.instructions = _clean_multiline(instructions, MAX_INSTRUCTIONS) or None
        project.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await s.commit()
        await s.refresh(project)
        count = (
            await s.execute(
                select(func.count(Conversation.id)).where(
                    Conversation.project_id == project.id,
                    *((Conversation.owner_id == owner,) if owner is not None else ()),
                )
            )
        ).scalar_one()
        return _project_dict(project, count)


async def delete_project(project_id: str) -> bool:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        project = await s.get(Project, _uuid(project_id))
        if project is None:
            return False
        if not _owned_by(project, owner):  # team mode: can't delete another user's project
            return False
        await s.delete(project)
        await s.commit()
        return True


async def set_conversation_project(conversation_id: str, project_id: str | None) -> dict | None:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, _uuid(conversation_id))
        if conv is None:
            return None
        if not _owned_by(conv, owner):
            return None
        project = None
        if project_id:
            project = await s.get(Project, _uuid(project_id))
            if project is None or not _owned_by(project, owner):
                return None
            conv.project_id = project.id
            project.updated_at = datetime.datetime.now(datetime.timezone.utc)
        else:
            conv.project_id = None
        conv.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await s.commit()
        await s.refresh(conv)
        return _conversation_dict(conv)


async def ensure_collection(project_id: str) -> str | None:
    """Return the project's RAG collection id, creating one on first file upload."""
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        project = await s.get(Project, _uuid(project_id))
        if project is None:
            return None
        if not _owned_by(project, owner):
            return None
        if project.collection_id:
            return str(project.collection_id)
        name = project.name or "project"
    col = await rag.create_collection(f"Project · {name[:80]}")
    async with get_sessionmaker()() as s:
        project = await s.get(Project, _uuid(project_id))
        if project is None:
            return col["id"]
        if not _owned_by(project, owner):
            return None
        project.collection_id = _uuid(col["id"])
        await s.commit()
    return col["id"]


async def collection_id_for(project_id: uuid.UUID | str | None) -> str | None:
    if not project_id:
        return None
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        project = await s.get(Project, _uuid(str(project_id)))
        if project is None or not _owned_by(project, owner):
            return None
        return str(project.collection_id) if project.collection_id else None


async def add_files(project_id: str, files: list[dict]) -> dict:
    """Ingest project files (any type) into the project's collection for chat context."""
    cid = await ensure_collection(project_id)
    if cid is None:
        return {"added": 0, "files": []}
    added = await rag.add_documents(cid, files)
    return {"added": added, "files": await rag.documents(cid)}


async def list_files(project_id: str) -> list[dict]:
    cid = await collection_id_for(project_id)
    return await rag.documents(cid) if cid else []


async def delete_file(project_id: str, source: str) -> bool:
    cid = await collection_id_for(project_id)
    if not cid:
        return False
    return (await rag.delete_source(cid, source)) > 0


async def trusted_context(project_id: uuid.UUID | str | None) -> str | None:
    if not project_id:
        return None
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        project = await s.get(Project, _uuid(str(project_id)))
        if project is None:
            return None
        if not _owned_by(project, owner):
            return None
        parts = [f"Project: {project.name}"]
        if project.description:
            parts.append(f"Project description:\n{project.description.strip()}")
        if project.instructions:
            parts.append(f"Standing project instructions:\n{project.instructions.strip()}")
        return "\n\n".join(parts)
