"""The exact-request invariant (ADR-005 slice 1).

The audit's standard is not "a request was logged". It is that the stored record reconstructs to the
same structure the adapter was given - otherwise the transcript is a claim, not evidence.
"""
import uuid

import pytest

from backend.providers import envelope


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _envelope(**overrides):
    base = dict(
        provider="openai", model="openai/gpt-4o", effort="high", effort_defaulted=False,
        privacy_mode="basic", system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "hello"}], tool_catalog=["web_search"],
    )
    base.update(overrides)
    return envelope.RequestEnvelope(**base)


def test_a_stored_envelope_proves_the_request_that_was_sent():
    frozen = _envelope()
    stored = __import__("json").dumps(frozen.canonical())

    assert envelope.proves(stored, frozen)


def test_any_difference_in_the_request_breaks_the_proof():
    """Each of these is a different request; none may pass as the same one."""
    stored = __import__("json").dumps(_envelope().canonical())

    for changed in (
        _envelope(model="openai/gpt-4o-mini"),
        _envelope(effort="low"),
        _envelope(system_prompt="You are terse."),
        _envelope(messages=[{"role": "user", "content": "hello "}]),   # one trailing space
        _envelope(messages=[{"role": "user", "content": "hello"}, {"role": "user", "content": "!"}]),
        _envelope(tool_catalog=["web_search", "run_shell"]),
        _envelope(privacy_mode="strict"),
        _envelope(effort_defaulted=True),
    ):
        assert not envelope.proves(stored, changed), f"{changed.model}/{changed.effort} passed"


def test_the_digest_ignores_key_order_but_not_content():
    """Canonical serialization: the same request written differently is still the same request."""
    a = _envelope(messages=[{"role": "user", "content": "hi"}])
    b = _envelope(messages=[{"content": "hi", "role": "user"}])

    assert a.digest() == b.digest()
    assert a.digest() != _envelope(messages=[{"role": "user", "content": "hi!"}]).digest()


def test_a_corrupt_or_unrelated_record_does_not_prove_anything():
    for junk in ("", "not json", "{}", '{"provider": "openai"}', "[]"):
        assert not envelope.proves(junk, _envelope())


def test_reconstruct_round_trips_every_field():
    frozen = _envelope(effort=None, effort_defaulted=True, tool_catalog=None, system_prompt=None)
    rebuilt = envelope.reconstruct(__import__("json").dumps(frozen.canonical()))

    assert rebuilt == frozen


@pytest.mark.anyio
async def test_capture_does_nothing_when_no_surface_asked_for_it():
    """Opt-in: a caller that never set a recording must not start writing request bodies."""
    assert envelope.recording() is None
    assert await envelope.capture(_envelope()) is None


@pytest.mark.anyio
async def test_a_recording_is_scoped_and_resets(monkeypatch):
    token = envelope.set_recording(envelope.RequestRecording(
        surface="agent", owner_id=None, agent_run_id=uuid.uuid4(), turn_id=uuid.uuid4(),
    ))
    try:
        assert envelope.recording().surface == "agent"
    finally:
        envelope.reset_recording(token)

    assert envelope.recording() is None


@pytest.mark.anyio
async def test_a_failed_write_never_breaks_the_model_call(monkeypatch):
    """An unrecorded request is a gap in evidence; a chat that dies for an audit row is worse."""
    def boom():
        raise RuntimeError("database down")

    monkeypatch.setattr("backend.core.database.get_sessionmaker", boom)
    token = envelope.set_recording(envelope.RequestRecording(
        surface="agent", owner_id=None, agent_run_id=uuid.uuid4(), turn_id=uuid.uuid4(),
    ))
    try:
        assert await envelope.capture(_envelope()) is None   # logged, not raised
    finally:
        envelope.reset_recording(token)
