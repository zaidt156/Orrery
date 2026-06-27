"""Task-route telemetry for production hardening.

These records are deliberately small and sanitized: route decisions, sandbox policy, and outcome
categories only. They never store the user's prompt, attachments, generated code, or document text.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import desc, func, select, update

from backend.core.database import get_sessionmaker
from backend.core.models import TaskRouteEvent
from backend.features.taskrouter import TaskPlan
from backend.security import secrets

log = logging.getLogger("orrery.route_telemetry")

OUTCOMES = {
    "planned",
    "completed",
    "failed",
    "unavailable",
    "sandbox_success",
    "sandbox_fallback",
    "sandbox_failed",
    "deterministic_success",
    "deterministic_failed",
}


def sandbox_policy(plan: TaskPlan) -> str:
    if plan.sandbox_required:
        return "required"
    if plan.sandbox_preferred:
        return "preferred"
    return "none"


def clean_detail(detail: str | None) -> str | None:
    if not detail:
        return None
    return secrets.redact_secrets(str(detail).replace("\n", " ").strip())[:500] or None


def event_payload(
    plan: TaskPlan,
    *,
    conversation_id: str | uuid.UUID | None,
    has_attachments: bool,
    outcome: str = "planned",
    detail: str | None = None,
) -> dict:
    """Build the DB payload. Kept pure so tests can prove we do not store prompt text."""
    if outcome not in OUTCOMES:
        outcome = "failed"
    conv = uuid.UUID(str(conversation_id)) if conversation_id else None
    return {
        "conversation_id": conv,
        "route": plan.route,
        "label": plan.label[:80],
        "output_mode": plan.output_mode,
        "skills": ",".join(plan.skills)[:300],
        "confidence": max(0.0, min(1.0, float(plan.confidence or 0.0))),
        "has_attachments": bool(has_attachments),
        "sandbox_policy": sandbox_policy(plan),
        "outcome": outcome,
        "detail": clean_detail(detail),
    }


async def record_plan(
    conversation_id: str | uuid.UUID | None,
    plan: TaskPlan,
    *,
    has_attachments: bool = False,
) -> str | None:
    """Persist a route decision. Best-effort: telemetry must never break chat."""
    try:
        row = TaskRouteEvent(**event_payload(plan, conversation_id=conversation_id, has_attachments=has_attachments))
        async with get_sessionmaker()() as s:
            s.add(row)
            await s.commit()
            return str(row.id)
    except Exception as exc:  # noqa: BLE001
        log.debug("route telemetry plan skipped: %s", type(exc).__name__)
        return None


async def record_outcome(event_id: str | None, outcome: str, detail: str | None = None) -> None:
    """Update the route decision with a sanitized final outcome."""
    if not event_id:
        return
    if outcome not in OUTCOMES:
        outcome = "failed"
    try:
        async with get_sessionmaker()() as s:
            await s.execute(
                update(TaskRouteEvent)
                .where(TaskRouteEvent.id == uuid.UUID(str(event_id)))
                .values(outcome=outcome, detail=clean_detail(detail))
            )
            await s.commit()
    except Exception as exc:  # noqa: BLE001
        log.debug("route telemetry outcome skipped: %s", type(exc).__name__)


async def summary(limit: int = 20) -> dict:
    """Return aggregate route telemetry for Settings/debug views."""
    limit = max(1, min(int(limit or 20), 100))
    async with get_sessionmaker()() as s:
        route_rows = (
            await s.execute(
                select(TaskRouteEvent.route, func.count(TaskRouteEvent.id))
                .group_by(TaskRouteEvent.route)
                .order_by(TaskRouteEvent.route)
            )
        ).all()
        outcome_rows = (
            await s.execute(
                select(TaskRouteEvent.outcome, func.count(TaskRouteEvent.id))
                .group_by(TaskRouteEvent.outcome)
                .order_by(TaskRouteEvent.outcome)
            )
        ).all()
        recent_rows = (
            await s.execute(
                select(TaskRouteEvent)
                .order_by(desc(TaskRouteEvent.created_at))
                .limit(limit)
            )
        ).scalars().all()
    return {
        "routes": {route: int(count) for route, count in route_rows},
        "outcomes": {outcome: int(count) for outcome, count in outcome_rows},
        "recent": [
            {
                "id": str(row.id),
                "conversation_id": str(row.conversation_id) if row.conversation_id else None,
                "route": row.route,
                "label": row.label,
                "output_mode": row.output_mode,
                "skills": [item for item in (row.skills or "").split(",") if item],
                "confidence": float(row.confidence or 0.0),
                "has_attachments": bool(row.has_attachments),
                "sandbox_policy": row.sandbox_policy,
                "outcome": row.outcome,
                "detail": row.detail,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in recent_rows
        ],
    }
