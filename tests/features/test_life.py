from __future__ import annotations

import os
import datetime
import uuid

import pytest

from backend.features import life
from backend.core.models import LifeProposal, LifeRevision


TEMPLATE = "# Orrery Life\n\nUser-owned durable memory.\n"


def test_bootstrap_creates_runtime_copy_once_and_never_overwrites(tmp_path):
    template = tmp_path / "template.md"
    template.write_text(TEMPLATE, encoding="utf-8")
    data_root = tmp_path / "data"

    first = life.bootstrap(data_root=data_root, template_path=template)
    first.path.write_bytes(b"# My Life\n\nKeep this.\n")
    second = life.bootstrap(data_root=data_root, template_path=template)

    assert first.path == data_root / "LIFE.md"
    assert second.content == "# My Life\n\nKeep this.\n"
    assert second.revision == life.content_hash(second.content)


def test_team_owner_has_isolated_canonical_file(tmp_path):
    owner = "4d36e96e-e325-11ce-bfc1-08002be10318"

    path = life.canonical_path(owner_id=owner, data_root=tmp_path)

    assert path == tmp_path / "users" / owner / "LIFE.md"


def test_prepare_proposal_binds_exact_base_and_target(tmp_path):
    template = tmp_path / "template.md"
    template.write_text(TEMPLATE, encoding="utf-8")
    current = life.bootstrap(data_root=tmp_path / "data", template_path=template)

    prepared = life.prepare_proposal(
        current=current.content,
        proposed=current.content + "\n## Preference\n\nUse concise answers.\n",
    )

    assert prepared.base_hash == current.revision
    assert prepared.target_hash == life.content_hash(prepared.content)
    assert "+Use concise answers." in prepared.diff


def test_apply_exact_rejects_stale_base_without_modifying_file(tmp_path):
    template = tmp_path / "template.md"
    template.write_text(TEMPLATE, encoding="utf-8")
    data_root = tmp_path / "data"
    original = life.bootstrap(data_root=data_root, template_path=template)
    proposal = life.prepare_proposal(original.content, original.content + "\nNew fact.\n")
    original.path.write_bytes(b"# Changed outside Orrery\n")

    with pytest.raises(life.LifeConflictError, match="changed since this proposal"):
        life.apply_exact(
            proposal.content,
            base_hash=proposal.base_hash,
            target_hash=proposal.target_hash,
            data_root=data_root,
        )

    assert original.path.read_text(encoding="utf-8") == "# Changed outside Orrery\n"


def test_apply_exact_is_revisioned_and_rollbackable(tmp_path):
    template = tmp_path / "template.md"
    template.write_text(TEMPLATE, encoding="utf-8")
    data_root = tmp_path / "data"
    original = life.bootstrap(data_root=data_root, template_path=template)
    proposal = life.prepare_proposal(original.content, original.content + "\n## Goal\n\nShip Orrery.\n")

    applied = life.apply_exact(
        proposal.content,
        base_hash=proposal.base_hash,
        target_hash=proposal.target_hash,
        data_root=data_root,
    )
    rolled_back = life.rollback_exact(
        proposal.base_hash,
        base_hash=applied.revision,
        data_root=data_root,
    )

    assert applied.content == proposal.content
    assert rolled_back.content == original.content
    assert life.history_path(proposal.target_hash, data_root=data_root).is_file()
    assert life.history_path(proposal.base_hash, data_root=data_root).is_file()


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer abcdefghijklmnop",
        # assembled at runtime so secret scanners don't flag this FAKE fixture as a real token
        "Slack bot token: " + "xoxb-" + "123456789-abcdefghijklmnop",
        "Google refresh token: 1//0gAbCdEfGhIjKlMnOp",
        "-----BEGIN PRIVATE KEY-----",
        "postgresql://ada:super-secret@localhost/private",
    ],
)
def test_secret_material_is_rejected(secret):
    with pytest.raises(life.LifeSecretError):
        life.prepare_proposal(TEMPLATE, TEMPLATE + "\n" + secret)


def test_oversized_and_nul_content_are_rejected():
    with pytest.raises(life.LifeValidationError):
        life.prepare_proposal(TEMPLATE, "x" * (life.MAX_LIFE_BYTES + 1))
    with pytest.raises(life.LifeValidationError):
        life.prepare_proposal(TEMPLATE, "contains\x00nul")


def test_symlink_target_is_rejected_when_supported(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    target = data_root / "LIFE.md"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(life.LifePathError):
        life.bootstrap(data_root=data_root, template_path=outside)

    assert outside.read_text(encoding="utf-8") == "outside\n"


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, results=()):
        self.results = list(results)
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def refresh(self, row):
        if row.id is None:
            row.id = uuid.uuid4()

    async def execute(self, _statement):
        return _FakeResult(self.results.pop(0))


def _sessionmaker(session):
    return lambda: session


@pytest.mark.anyio
async def test_background_proposal_uses_explicit_snapshotted_owner(monkeypatch, tmp_path):
    from backend.core import database

    owner = "4d36e96e-e325-11ce-bfc1-08002be10318"
    current = life.LifeDocument(tmp_path / "LIFE.md", TEMPLATE, life.content_hash(TEMPLATE))
    fake = _FakeSession()
    monkeypatch.setattr(life, "read_document", lambda **kwargs: current)
    monkeypatch.setattr(database, "get_sessionmaker", lambda: _sessionmaker(fake))

    result = await life.propose_for_owner(
        TEMPLATE + "\n## Learned\n\nPrefer local execution.\n",
        owner_id=owner,
        reason="Agent learned a durable preference",
        source_type="agent",
        source_id="run-123",
    )

    row = fake.added[0]
    assert row.owner_id == owner
    assert row.source_type == "agent"
    assert row.status == "pending"
    assert result["target_hash"] == life.content_hash(row.proposed_content)


@pytest.mark.anyio
async def test_approval_applies_exact_hash_and_records_revision(monkeypatch, tmp_path):
    from backend.core import database
    from backend.features import team

    owner = "4d36e96e-e325-11ce-bfc1-08002be10318"
    proposed = TEMPLATE + "\n## Goal\n\nShip safely.\n"
    base_hash = life.content_hash(TEMPLATE)
    target_hash = life.content_hash(proposed)
    now = datetime.datetime.now(datetime.timezone.utc)
    row = LifeProposal(
        id=uuid.uuid4(), owner_id=owner, base_hash=base_hash, target_hash=target_hash,
        proposed_content=proposed, diff="+Ship safely.", reason="Goal", source_type="agent",
        source_id="run-1", status="pending", expires_at=now + datetime.timedelta(days=1),
        created_at=now,
    )
    fake = _FakeSession([row, None])
    current = life.LifeDocument(tmp_path / "LIFE.md", TEMPLATE, base_hash)
    applied = life.LifeDocument(tmp_path / "LIFE.md", proposed, target_hash)
    seen = {}

    async def current_owner():
        return owner

    def apply_exact(content, **kwargs):
        seen.update({"content": content, **kwargs})
        return applied

    monkeypatch.setattr(team, "current_owner_id", current_owner)
    monkeypatch.setattr(database, "get_sessionmaker", lambda: _sessionmaker(fake))
    monkeypatch.setattr(life, "read_document", lambda **kwargs: current)
    monkeypatch.setattr(life, "apply_exact", apply_exact)

    result = await life.approve_for_current_user(str(row.id), target_hash=target_hash)

    assert result["status"] == "applied"
    assert seen == {
        "content": proposed,
        "base_hash": base_hash,
        "target_hash": target_hash,
        "owner_id": owner,
    }
    revision = next(item for item in fake.added if isinstance(item, LifeRevision))
    assert revision.content_hash == target_hash
    assert revision.previous_hash == base_hash


@pytest.mark.anyio
async def test_approval_rejects_digest_not_shown_to_user(monkeypatch):
    from backend.core import database
    from backend.features import team

    now = datetime.datetime.now(datetime.timezone.utc)
    row = LifeProposal(
        id=uuid.uuid4(), owner_id=None, base_hash="a" * 64, target_hash="b" * 64,
        proposed_content=TEMPLATE, diff="change", reason="", source_type="agent",
        status="pending", expires_at=now + datetime.timedelta(days=1), created_at=now,
    )
    fake = _FakeSession([row])

    async def solo_owner():
        return None

    monkeypatch.setattr(team, "current_owner_id", solo_owner)
    monkeypatch.setattr(database, "get_sessionmaker", lambda: _sessionmaker(fake))

    with pytest.raises(life.LifeConflictError, match="displayed"):
        await life.approve_for_current_user(str(row.id), target_hash="c" * 64)

    assert row.status == "pending"
    assert fake.commits == 0
