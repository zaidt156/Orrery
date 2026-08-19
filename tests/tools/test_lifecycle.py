"""Execution-evidence domain invariants that do not need PostgreSQL."""
from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

from backend.tools.lifecycle import (
    BoundedPresentation,
    TerminalOutcome,
    ToolExecutionIdentity,
    canonical_digest,
    canonical_json,
    safe_arguments,
)


def test_canonical_json_and_digest_are_stable_across_mapping_order():
    left = {"z": [3, 2, 1], "a": {"b": True, "a": None}}
    right = {"a": {"a": None, "b": True}, "z": [3, 2, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_digest(left) == canonical_digest(right)


def test_canonical_json_rejects_non_json_numbers():
    with pytest.raises(ValueError):
        canonical_json({"value": float("nan")})


def test_safe_arguments_redacts_nested_credentials_without_mutating_input():
    attempted = {
        "url": "postgresql://alice:hunter2@db.local/app",
        "headers": ["Authorization: Bearer very-secret-token"],
    }

    safe = safe_arguments(attempted)

    assert "hunter2" not in canonical_json(safe)
    assert "very-secret-token" not in canonical_json(safe)
    assert attempted["url"].endswith("@db.local/app")


def test_execution_identity_is_frozen_and_parent_matches_surface():
    conversation_id = uuid.uuid4()
    identity = ToolExecutionIdentity(
        surface="chat",
        owner_id=None,
        conversation_id=conversation_id,
        turn_id=uuid.uuid4(),
    )

    with pytest.raises(FrozenInstanceError):
        identity.surface = "agent"  # type: ignore[misc]

    with pytest.raises(ValueError, match="exactly one parent"):
        ToolExecutionIdentity(surface="chat", owner_id=None, turn_id=uuid.uuid4())

    with pytest.raises(ValueError, match="surface"):
        ToolExecutionIdentity(
            surface="agent",
            owner_id=None,
            conversation_id=conversation_id,
            turn_id=uuid.uuid4(),
        )


def test_unknown_started_outcome_can_never_be_retry_safe():
    with pytest.raises(ValueError, match="retry-safe"):
        TerminalOutcome(
            outcome="unknown",
            code="unknown_outcome",
            dispatch_state="started",
            retry_safe=True,
            message="The effect is unknown.",
        )


def test_bounded_presentation_preserves_exact_view_and_loss_facts():
    full = "0123456789" * 20
    presentation = BoundedPresentation.from_text(full, max_chars=80)

    assert len(presentation.text) <= 80
    assert presentation.truncated is True
    assert presentation.original_chars == len(full)
    assert presentation.omitted_chars == len(full) - len(presentation.text) + len(presentation.marker)
    assert presentation.full_digest == canonical_digest(full)
    assert presentation.presentation_digest == canonical_digest(presentation.text)


def test_short_presentation_is_exact_and_lossless():
    presentation = BoundedPresentation.from_text("small result", max_chars=80)

    assert presentation.text == "small result"
    assert presentation.truncated is False
    assert presentation.omitted_chars == 0
    assert presentation.full_digest == presentation.presentation_digest
