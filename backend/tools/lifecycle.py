"""Durable, append-only evidence for calls crossing the shared tool boundary.

The immutable call row answers *what was authorized*. Ordered events answer *what happened*.
Nothing in this module grants authority; registry guards still make every admission decision.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlalchemy import func, select

from backend.security import secrets

Surface = Literal["chat", "agent", "automation"]
DispatchState = Literal["never_dispatched", "started", "unknown"]
Outcome = Literal["succeeded", "failed", "denied", "cancelled", "timed_out", "unknown"]

_ARGUMENT_LIMIT = 128_000
_EVENT_PAYLOAD_LIMIT = 128_000
_DEFAULT_PRESENTATION_LIMIT = 20_000
_TERMINAL_KINDS = {"call_rejected", "terminal_outcome"}
_REPEAT_MILESTONES = {3, 5, 8}


def canonical_json(value: Any) -> str:
    """Return the one UTF-8-stable JSON representation used by evidence digests."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def safe_arguments(value: Any) -> Any:
    """Copy JSON-like values while recursively removing credential-shaped text."""
    if isinstance(value, dict):
        return {str(key): safe_arguments(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_arguments(item) for item in value]
    if isinstance(value, str):
        return secrets.redact_secrets(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return secrets.redact_secrets(str(value))


@dataclass(frozen=True, slots=True)
class ToolExecutionIdentity:
    """Caller-provided lineage. Parent ownership is re-checked from PostgreSQL on insert."""

    surface: Surface
    owner_id: str | None
    turn_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None
    call_id: uuid.UUID = field(default_factory=uuid.uuid4)
    parent_call_id: uuid.UUID | None = None
    provider_call_id: str | None = None
    grant_snapshot_ref: str | None = None
    config_snapshot_ref: str | None = None

    def __post_init__(self) -> None:
        parents = {
            "chat": self.conversation_id,
            "agent": self.agent_run_id,
            "automation": self.workflow_run_id,
        }
        if sum(value is not None for value in parents.values()) != 1:
            raise ValueError("A tool execution needs exactly one parent.")
        if parents[self.surface] is None:
            raise ValueError("The execution surface must match its parent.")


@dataclass(frozen=True, slots=True)
class TerminalOutcome:
    outcome: Outcome
    code: str
    dispatch_state: DispatchState
    retry_safe: bool
    message: str = ""

    def __post_init__(self) -> None:
        if self.retry_safe and self.dispatch_state != "never_dispatched":
            raise ValueError("A started or unknown effect cannot be retry-safe.")
        if self.outcome == "succeeded" and self.dispatch_state != "started":
            raise ValueError("A successful tool body must have started.")

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BoundedPresentation:
    """The exact bounded text shown downstream, with honest loss metadata."""

    text: str
    original_chars: int
    omitted_chars: int
    truncated: bool
    full_digest: str
    presentation_digest: str
    marker: str = ""

    @classmethod
    def from_text(cls, value: str, *, max_chars: int = _DEFAULT_PRESENTATION_LIMIT):
        text = str(value)
        if max_chars < 64:
            raise ValueError("Presentation limit must be at least 64 characters.")
        if len(text) <= max_chars:
            digest = canonical_digest(text)
            return cls(text, len(text), 0, False, digest, digest)

        marker = ""
        omitted = len(text) - max_chars
        for _ in range(3):
            marker = f"\n… {omitted} characters omitted …\n"
            kept = max_chars - len(marker)
            if kept < 2:
                raise ValueError("Presentation limit is too small for loss metadata.")
            head = (kept + 1) // 2
            tail = kept - head
            omitted = len(text) - head - tail
        shown = text[:head] + marker + (text[-tail:] if tail else "")
        return cls(
            shown,
            len(text),
            omitted,
            True,
            canonical_digest(text),
            canonical_digest(shown),
            marker,
        )

    @classmethod
    def from_value(cls, value: Any, *, max_chars: int = _DEFAULT_PRESENTATION_LIMIT):
        return cls.from_text(canonical_json(value), max_chars=max_chars)

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def _bounded_canonical(value: Any, limit: int) -> tuple[str, str]:
    encoded = canonical_json(value)
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError(f"Evidence payload exceeds the {limit}-byte limit.")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ToolCallLifecycle:
    """One append-only lifecycle writer. Instances are single-call, not shared."""

    def __init__(
        self,
        identity: ToolExecutionIdentity,
        tool_key: str,
        arguments: Any,
        *,
        arguments_state: Literal["validated", "rejected"],
    ) -> None:
        self.identity = identity
        self.tool_key = tool_key[:80]
        self.arguments = safe_arguments(arguments)
        self.arguments_state = arguments_state
        self.arguments_json, self.arguments_digest = _bounded_canonical(
            self.arguments, _ARGUMENT_LIMIT
        )

    async def admit(self) -> None:
        await _create_call(self, "call_admitted", {"code": "admitted"})

    async def reject(
        self, outcome: TerminalOutcome, presentation: BoundedPresentation
    ) -> None:
        await _create_call(
            self,
            "call_rejected",
            {"outcome": outcome.payload(), "presentation": presentation.payload()},
        )

    async def repeated_call_warning(self) -> str | None:
        count = await _consecutive_identical_count(self)
        if count not in _REPEAT_MILESTONES:
            return None
        return (
            f"You have made this identical tool call {count} times in this turn. "
            "Inspect the latest result or change the arguments before repeating it."
        )

    async def body_started(self) -> None:
        await _append_events(self.identity.call_id, self.identity.owner_id, [
            ("body_started", {"code": "body_started"}),
        ])

    async def complete(
        self, outcome: TerminalOutcome, presentation: BoundedPresentation
    ) -> None:
        await _append_events(self.identity.call_id, self.identity.owner_id, [
            ("result", {"presentation": presentation.payload()}),
            ("terminal_outcome", {"outcome": outcome.payload()}),
        ])

    async def cancelled(self) -> None:
        outcome = TerminalOutcome(
            outcome="cancelled",
            code="cancelled",
            dispatch_state="started",
            retry_safe=False,
            message="The caller cancelled while the tool body was active.",
        )
        presentation = BoundedPresentation.from_value({
            "ok": False,
            "code": outcome.code,
            "error": outcome.message,
            "retry_safe": False,
        })
        await self.complete(outcome, presentation)


# Workflow nodes execute through a fixed `execute(inputs, config)` signature, so they cannot be
# handed an identity as an argument. The engine sets it around each node instead. Chat and Agents
# pass theirs explicitly and never read this.
_ambient: contextvars.ContextVar[ToolExecutionIdentity | None] = contextvars.ContextVar(
    "orrery_tool_identity", default=None
)


def current_identity() -> ToolExecutionIdentity | None:
    return _ambient.get()


def set_identity(value: ToolExecutionIdentity | None):
    """Returns the token to reset with; always reset in a `finally`."""
    return _ambient.set(value)


def reset_identity(token) -> None:
    _ambient.reset(token)


def start(
    identity: ToolExecutionIdentity,
    tool_key: str,
    arguments: Any,
    *,
    arguments_state: Literal["validated", "rejected"],
) -> ToolCallLifecycle:
    return ToolCallLifecycle(identity, tool_key, arguments, arguments_state=arguments_state)


_MISSING = object()


async def _parent_owner(session, identity: ToolExecutionIdentity) -> str | None | object:
    from backend.core.models import AgentRun, Conversation, Workflow, WorkflowRun

    if identity.surface == "chat":
        parent = await session.get(Conversation, identity.conversation_id)
        return _MISSING if parent is None else parent.owner_id
    if identity.surface == "agent":
        parent = await session.get(AgentRun, identity.agent_run_id)
        return _MISSING if parent is None else parent.owner_id
    # `.first()`, not `.scalar_one_or_none()`: a solo-mode workflow has a NULL owner, and a scalar
    # lookup cannot tell that apart from "no such run" - which refused every automation tool call
    # in the default single-user configuration.
    row = (await session.execute(
        select(Workflow.owner_id)
        .join(WorkflowRun, WorkflowRun.workflow_id == Workflow.id)
        .where(WorkflowRun.id == identity.workflow_run_id)
    )).first()
    return _MISSING if row is None else row[0]


async def _create_call(writer: ToolCallLifecycle, first_kind: str, payload: dict[str, Any]) -> None:
    from backend.core.database import get_sessionmaker
    from backend.core.models import ToolCallContext, ToolLifecycleEvent

    payload_json, payload_digest = _bounded_canonical(payload, _EVENT_PAYLOAD_LIMIT)
    identity = writer.identity
    context_value = {
        "surface": identity.surface,
        "owner_id": identity.owner_id,
        "conversation_id": str(identity.conversation_id) if identity.conversation_id else None,
        "agent_run_id": str(identity.agent_run_id) if identity.agent_run_id else None,
        "workflow_run_id": str(identity.workflow_run_id) if identity.workflow_run_id else None,
        "turn_id": str(identity.turn_id),
        "call_id": str(identity.call_id),
        "parent_call_id": str(identity.parent_call_id) if identity.parent_call_id else None,
        "provider_call_id": identity.provider_call_id,
        "tool_key": writer.tool_key,
        "safe_arguments": writer.arguments,
        "arguments_state": writer.arguments_state,
        "grant_snapshot_ref": identity.grant_snapshot_ref,
        "config_snapshot_ref": identity.config_snapshot_ref,
    }
    async with get_sessionmaker()() as session:
        owner = await _parent_owner(session, identity)
        if owner is _MISSING or owner != identity.owner_id:
            raise PermissionError("Tool evidence parent was not found.")
        session.add(ToolCallContext(
            id=identity.call_id,
            owner_id=identity.owner_id,
            surface=identity.surface,
            conversation_id=identity.conversation_id,
            agent_run_id=identity.agent_run_id,
            workflow_run_id=identity.workflow_run_id,
            turn_id=identity.turn_id,
            provider_call_id=identity.provider_call_id,
            parent_call_context_id=identity.parent_call_id,
            tool_key=writer.tool_key,
            safe_arguments=writer.arguments_json,
            arguments_state=writer.arguments_state,
            arguments_digest=writer.arguments_digest,
            grant_snapshot_ref=identity.grant_snapshot_ref,
            config_snapshot_ref=identity.config_snapshot_ref,
            context_digest=canonical_digest(context_value),
        ))
        session.add(ToolLifecycleEvent(
            call_context_id=identity.call_id,
            sequence=1,
            kind=first_kind,
            payload=payload_json,
            payload_digest=payload_digest,
        ))
        await session.commit()


async def _locked_context(session, call_id: uuid.UUID, owner_id: str | None):
    from backend.core.models import ToolCallContext

    owner_clause = (
        ToolCallContext.owner_id.is_(None)
        if owner_id is None
        else ToolCallContext.owner_id == owner_id
    )
    return (await session.execute(
        select(ToolCallContext)
        .where(ToolCallContext.id == call_id, owner_clause)
        .with_for_update()
    )).scalar_one_or_none()


async def _append_events(
    call_id: uuid.UUID,
    owner_id: str | None,
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    from backend.core.database import get_sessionmaker
    from backend.core.models import ToolLifecycleEvent

    encoded = [
        (kind, *_bounded_canonical(payload, _EVENT_PAYLOAD_LIMIT))
        for kind, payload in events
    ]
    async with get_sessionmaker()() as session:
        context = await _locked_context(session, call_id, owner_id)
        if context is None:
            raise LookupError("Tool call evidence was not found.")
        prior = (await session.execute(
            select(ToolLifecycleEvent)
            .where(ToolLifecycleEvent.call_context_id == call_id)
            .order_by(ToolLifecycleEvent.sequence)
        )).scalars().all()
        if any(item.kind in _TERMINAL_KINDS for item in prior):
            raise RuntimeError("Tool call evidence is already terminal.")
        sequence = prior[-1].sequence if prior else 0
        for kind, payload_json, payload_digest in encoded:
            sequence += 1
            session.add(ToolLifecycleEvent(
                call_context_id=call_id,
                sequence=sequence,
                kind=kind,
                payload=payload_json,
                payload_digest=payload_digest,
            ))
        await session.commit()


async def _consecutive_identical_count(writer: ToolCallLifecycle) -> int:
    from backend.core.database import get_sessionmaker
    from backend.core.models import ToolCallContext, ToolLifecycleEvent

    identity = writer.identity
    parent_clause = {
        "chat": ToolCallContext.conversation_id == identity.conversation_id,
        "agent": ToolCallContext.agent_run_id == identity.agent_run_id,
        "automation": ToolCallContext.workflow_run_id == identity.workflow_run_id,
    }[identity.surface]
    async with get_sessionmaker()() as session:
        rows = (await session.execute(
            select(ToolCallContext)
            .where(
                ToolCallContext.turn_id == identity.turn_id,
                parent_clause,
                ToolCallContext.id != identity.call_id,
            )
            .order_by(ToolCallContext.created_at.desc(), ToolCallContext.id.desc())
            .limit(max(_REPEAT_MILESTONES))
        )).scalars().all()
        count = 1
        for row in rows:
            terminal = (await session.execute(
                select(func.count())
                .select_from(ToolLifecycleEvent)
                .where(
                    ToolLifecycleEvent.call_context_id == row.id,
                    ToolLifecycleEvent.kind.in_(_TERMINAL_KINDS),
                )
            )).scalar_one()
            if not terminal:
                continue
            if row.tool_key != writer.tool_key or row.arguments_digest != writer.arguments_digest:
                break
            count += 1
        return count


async def reconcile_incomplete_calls() -> dict[str, int]:
    """Close crash-interrupted streams without ever calling a tool body again."""
    from backend.core.database import get_sessionmaker
    from backend.core.models import ToolCallContext, ToolLifecycleEvent

    async with get_sessionmaker()() as session:
        terminal_ids = select(ToolLifecycleEvent.call_context_id).where(
            ToolLifecycleEvent.kind.in_(_TERMINAL_KINDS)
        )
        rows = (await session.execute(
            select(ToolCallContext).where(ToolCallContext.id.not_in(terminal_ids))
        )).scalars().all()

    recovered = {"never_dispatched": 0, "unknown_outcome": 0}
    for row in rows:
        async with get_sessionmaker()() as session:
            started = (await session.execute(
                select(func.count())
                .select_from(ToolLifecycleEvent)
                .where(
                    ToolLifecycleEvent.call_context_id == row.id,
                    ToolLifecycleEvent.kind == "body_started",
                )
            )).scalar_one() > 0
        dispatch_state: DispatchState = "started" if started else "never_dispatched"
        code = "unknown_outcome" if started else "recovered_not_dispatched"
        outcome = TerminalOutcome(
            outcome="unknown",
            code=code,
            dispatch_state=dispatch_state,
            retry_safe=not started,
            message=(
                "The tool body started, but no durable result exists; do not retry automatically."
                if started
                else "The call was admitted but its body never started."
            ),
        )
        try:
            await _append_events(row.id, row.owner_id, [
                ("terminal_outcome", {"outcome": outcome.payload(), "recovered": True}),
            ])
        except RuntimeError:
            continue
        recovered["unknown_outcome" if started else "never_dispatched"] += 1
    return recovered
