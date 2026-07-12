import uuid

import pytest

from backend.features import rag
from backend.core import migrations


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None


class _CaptureSession:
    def __init__(self, values=()):
        self.values = list(values)
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, statement):
        self.statements.append(statement)
        return _ScalarResult(self.values)


@pytest.mark.anyio
async def test_connected_ontologies_are_scoped_to_current_team_owner(monkeypatch):
    session = _CaptureSession([uuid.uuid4()])

    async def current_owner_id():
        return "member-a"

    monkeypatch.setattr(rag.team, "current_owner_id", current_owner_id)
    monkeypatch.setattr(rag, "get_sessionmaker", lambda: lambda: session)

    await rag.connected_collection_ids()

    sql = str(session.statements[0])
    assert "collections.connected" in sql
    assert "collections.kind" in sql
    assert "collections.owner_id" in sql
    assert session.statements[0].compile().params["owner_id_1"] == "member-a"


@pytest.mark.anyio
async def test_ownerless_connected_ontologies_fail_closed_in_team_mode(monkeypatch):
    """The team predicate is equality, so legacy NULL rows cannot leak workspace-wide."""
    session = _CaptureSession([])

    async def current_owner_id():
        return "member-a"

    monkeypatch.setattr(rag.team, "current_owner_id", current_owner_id)
    monkeypatch.setattr(rag, "get_sessionmaker", lambda: lambda: session)

    assert await rag.connected_collection_ids() == []
    assert "collections.owner_id" in str(session.statements[0])


@pytest.mark.anyio
async def test_solo_connected_ontologies_remain_workspace_wide(monkeypatch):
    session = _CaptureSession([uuid.uuid4()])

    async def current_owner_id():
        return None

    monkeypatch.setattr(rag.team, "current_owner_id", current_owner_id)
    monkeypatch.setattr(rag, "get_sessionmaker", lambda: lambda: session)

    assert len(await rag.connected_collection_ids()) == 1
    assert "collections.owner_id" not in str(session.statements[0])


@pytest.mark.anyio
async def test_collection_content_access_rejects_cross_owner_ids(monkeypatch):
    session = _CaptureSession([])

    async def current_owner_id():
        return "member-a"

    monkeypatch.setattr(rag.team, "current_owner_id", current_owner_id)
    monkeypatch.setattr(rag, "get_sessionmaker", lambda: lambda: session)

    with pytest.raises(PermissionError, match="Collection not found"):
        await rag._require_collection_access(str(uuid.uuid4()))

    sql = str(session.statements[0])
    assert "collections.id" in sql
    assert "collections.owner_id" in sql


def test_collection_owner_migration_only_backfills_unambiguous_parent_owners():
    statements = dict(migrations._VERSIONED_MIGRATIONS)["0007_collection_owner_backfill"]
    sql = "\n".join(statements).lower()

    assert "conversations" in sql and "projects" in sql
    assert "count(distinct owner_id) = 1" in sql
    assert "team_users" not in sql  # never guess that the first/admin user owns an orphan row
