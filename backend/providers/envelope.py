"""The exact request handed to a model adapter, captured and provable afterwards (ADR-005 slice 1).

The audit's point is not that a request was logged somewhere. It is that the record can be
*reconstructed* and shown to be the same structure the adapter actually received — otherwise a
transcript is a claim about the past rather than evidence of it.

What is captured is the request as it exists at the adapter boundary: after privacy redaction, after
route selection, with the effort the provider will really see. Not HTTP wire bytes — those carry
transport auth headers, and comparing them would make the invariant a secret-handling problem
instead of a correctness one. Credentials are resolved below this layer and never appear here.

Sensitive text the user intentionally sent is part of this record, by design: it is owner-private,
lives in the same PostgreSQL trust domain as the conversation, and is deleted with its parent.

Capture is opt-in per surface through `recording()`. A surface that has not been wired records
nothing, so this cannot silently start storing requests for callers that never asked.
"""
from __future__ import annotations

import contextvars
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("orrery.envelope")

# A request body larger than this is not stored; its digest still is, so the invariant can prove
# identity even when the body is too large to keep beside every other run.
_BODY_LIMIT_BYTES = 512_000


@dataclass(frozen=True, slots=True)
class RequestRecording:
    """Where a captured envelope belongs. Set by the surface driving the model step."""

    surface: str
    owner_id: str | None
    turn_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None
    # Orrery describes its tools inside the system prompt rather than through a provider tool
    # schema, so this stays None unless a surface has a real catalog to declare.
    tool_catalog: list[str] | None = None


_current: contextvars.ContextVar[RequestRecording | None] = contextvars.ContextVar(
    "orrery_request_recording", default=None
)


def recording() -> RequestRecording | None:
    return _current.get()


def set_recording(value: RequestRecording | None):
    """Returns the token to reset with; use try/finally so a step never leaks into the next."""
    return _current.set(value)


def reset_recording(token) -> None:
    _current.reset(token)


@dataclass(frozen=True, slots=True)
class RequestEnvelope:
    """The canonical structure. Field order is irrelevant; the digest is order-independent."""

    provider: str
    model: str
    effort: str | None
    effort_defaulted: bool
    privacy_mode: str
    system_prompt: str | None
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_catalog: list[str] | None = None

    def canonical(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "effort": self.effort,
            "effort_defaulted": self.effort_defaulted,
            "privacy_mode": self.privacy_mode,
            "system_prompt": self.system_prompt,
            "messages": [dict(m) for m in self.messages],
            "tool_catalog": list(self.tool_catalog) if self.tool_catalog is not None else None,
        }

    def digest(self) -> str:
        from backend.tools.lifecycle import canonical_digest

        return canonical_digest(self.canonical())


def reconstruct(stored_body: str) -> RequestEnvelope:
    """Rebuild an envelope from what was persisted. Raises if the record is not an envelope."""
    import json

    data = json.loads(stored_body)
    return RequestEnvelope(
        provider=data["provider"],
        model=data["model"],
        effort=data["effort"],
        effort_defaulted=bool(data["effort_defaulted"]),
        privacy_mode=data["privacy_mode"],
        system_prompt=data["system_prompt"],
        messages=list(data["messages"]),
        tool_catalog=data["tool_catalog"],
    )


def proves(stored_body: str, frozen: RequestEnvelope) -> bool:
    """The invariant: what was stored rebuilds to the same structure that was sent.

    Digest equality over a canonical serialization, so key order and whitespace cannot make two
    different requests look alike or one request look like two.
    """
    try:
        return reconstruct(stored_body).digest() == frozen.digest()
    except (ValueError, KeyError, TypeError):
        return False


async def capture(envelope: RequestEnvelope) -> uuid.UUID | None:
    """Persist the envelope for the current recording, if a surface asked for one.

    Never raises into the model path: an unrecorded request is a gap in evidence, but a chat that
    dies because its audit row failed is a worse outcome, and the gap is logged rather than hidden.
    """
    target = recording()
    if target is None:
        return None

    from backend.core.database import get_sessionmaker
    from backend.core.models import ModelRequestEnvelope
    from backend.tools.lifecycle import canonical_json

    body = canonical_json(envelope.canonical())
    digest = envelope.digest()
    too_large = len(body.encode("utf-8")) > _BODY_LIMIT_BYTES
    try:
        async with get_sessionmaker()() as session:
            row = ModelRequestEnvelope(
                owner_id=target.owner_id,
                surface=target.surface,
                conversation_id=target.conversation_id,
                agent_run_id=target.agent_run_id,
                workflow_run_id=target.workflow_run_id,
                turn_id=target.turn_id,
                provider=envelope.provider,
                model=envelope.model,
                effort=envelope.effort,
                body="" if too_large else body,
                body_retained=not too_large,
                body_digest=digest,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id
    except Exception as exc:  # noqa: BLE001 - see docstring
        log.warning("model request envelope not recorded: %s", type(exc).__name__)
        return None
