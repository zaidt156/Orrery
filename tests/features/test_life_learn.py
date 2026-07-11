import pytest

from backend.features import life, life_learn


def test_worth_learning_gates_on_personal_signals():
    assert life_learn.worth_learning("I'm Zaid and I prefer short answers")
    assert life_learn.worth_learning("From now on always answer in English")
    assert not life_learn.worth_learning("What is the capital of France?")
    assert not life_learn.worth_learning("")
    assert not life_learn.worth_learning("I am " + "x" * 5000)


def test_merge_facts_creates_section_and_dedupes():
    current = "# Orrery Life\n\nSomething.\n"
    merged = life_learn.merge_facts(current, ["Prefers short answers", "Works at Acme"])
    assert life_learn._SECTION in merged
    assert "- Prefers short answers." in merged
    again = life_learn.merge_facts(merged, ["Prefers short answers"])
    assert again is None  # nothing new survives → no proposal

    third = life_learn.merge_facts(merged, ["Uses UK spelling"])
    assert third.count(life_learn._SECTION) == 1
    assert "- Uses UK spelling." in third


def test_parse_facts_tolerates_wrapped_json():
    raw = 'Sure! Here you go:\n{"facts": ["Name is Zaid", 42, "Builds Orrery"]}\nDone.'
    assert life_learn._parse_facts(raw) == ["Name is Zaid", "Builds Orrery"]
    assert life_learn._parse_facts("no json here") == []
    assert life_learn._parse_facts('{"facts": "not-a-list"}') == []


def test_fresh_flag_on_seed_and_personal_content():
    assert life.is_fresh(life.SEED_CONTENT)
    assert not life.is_fresh("# Orrery Life\n\n## Who you are\n- Name: Zaid\n")


@pytest.mark.anyio
async def test_consider_turn_creates_a_pending_proposal(monkeypatch):
    life_learn._last_proposal.clear()
    captured = {}

    class Doc:
        content = "# Orrery Life\n"

    async def fake_pending(owner_id, *, status=None):
        return []

    async def fake_propose(content, *, owner_id, reason, source_type, source_id):
        captured.update(content=content, owner_id=owner_id, source_type=source_type, source_id=source_id)
        return {"id": "p1"}

    async def fake_stream(model, messages, system_prompt=None, effort=None, usage_out=None):
        yield '{"facts": ["Prefers concise answers"]}'

    monkeypatch.setattr(life_learn.life, "read_document", lambda owner_id=None: Doc())
    monkeypatch.setattr(life_learn.life, "list_proposals_for_owner", fake_pending)
    monkeypatch.setattr(life_learn.life, "propose_for_owner", fake_propose)

    from backend.providers import ai
    monkeypatch.setattr(ai, "stream_chat", fake_stream)

    await life_learn.consider_turn(owner_id=None, user_text="Remember I prefer concise answers", model="openai/test")

    assert "- Prefers concise answers." in captured["content"]
    assert captured["source_type"] == "system"
    assert captured["source_id"] == "chat-learning"


@pytest.mark.anyio
async def test_consider_turn_skips_impersonal_and_cooldown(monkeypatch):
    life_learn._last_proposal.clear()
    calls = []

    async def fake_pending(owner_id, *, status=None):
        return []

    async def fake_propose(content, **kwargs):
        calls.append(content)
        return {"id": "p1"}

    async def fake_stream(model, messages, system_prompt=None, effort=None, usage_out=None):
        yield '{"facts": ["Something"]}'

    monkeypatch.setattr(life_learn.life, "read_document", lambda owner_id=None: type("D", (), {"content": "# L\n"})())
    monkeypatch.setattr(life_learn.life, "list_proposals_for_owner", fake_pending)
    monkeypatch.setattr(life_learn.life, "propose_for_owner", fake_propose)
    from backend.providers import ai
    monkeypatch.setattr(ai, "stream_chat", fake_stream)

    await life_learn.consider_turn(owner_id=None, user_text="What's 2+2?", model="m")
    assert calls == []  # impersonal → no model call, no proposal

    await life_learn.consider_turn(owner_id=None, user_text="Remember I always use tabs", model="m")
    await life_learn.consider_turn(owner_id=None, user_text="Remember I always use spaces", model="m")
    assert len(calls) == 1  # second attempt inside the cooldown window is dropped
