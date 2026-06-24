from __future__ import annotations

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import Feedback


async def submit(category: str, message: str, contact: str | None, context: str | None) -> dict:
    async with get_sessionmaker()() as s:
        row = Feedback(
            category=category or "general",
            message=message.strip(),
            contact=(contact or "").strip() or None,
            context=(context or "").strip() or None,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return {"id": str(row.id), "created_at": row.created_at.isoformat()}


async def recent(limit: int = 100) -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(select(Feedback).order_by(Feedback.created_at.desc()).limit(limit))
        ).scalars().all()
        return [
            {"id": str(r.id), "created_at": r.created_at.isoformat(), "category": r.category,
             "message": r.message, "contact": r.contact}
            for r in rows
        ]
