import uuid

import pytest

from backend.core.models import Conversation, Project
from backend.features import chat, projects, team


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, key):
        return self.rows.get((model, uuid.UUID(str(key))))

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        return None


def _sessionmaker(fake):
    return lambda: fake


@pytest.mark.anyio
async def test_current_owner_id_denies_locked_team_client(monkeypatch):
    async def team_mode_on():
        return True

    async def locked_user():
        return None

    monkeypatch.setattr(team, "team_mode", team_mode_on)
    monkeypatch.setattr(team, "current_user", locked_user)

    with pytest.raises(PermissionError, match="Team access key required"):
        await team.current_owner_id()


@pytest.mark.anyio
async def test_conversation_access_rejects_another_owner(monkeypatch):
    cid = uuid.UUID("00000000-0000-0000-0000-000000000101")
    conv = Conversation(id=cid, model="openai/test", owner_id="owner-b")
    fake = FakeSession({(Conversation, cid): conv})

    async def owner_a():
        return "owner-a"

    monkeypatch.setattr(chat.team, "current_owner_id", owner_a)
    monkeypatch.setattr(chat.conversations, "get_sessionmaker", lambda: _sessionmaker(fake))

    assert await chat.can_access_conversation(str(cid)) is False


@pytest.mark.anyio
async def test_create_conversation_rejects_foreign_project(monkeypatch):
    pid = uuid.UUID("00000000-0000-0000-0000-000000000202")
    project = Project(id=pid, name="Private project", owner_id="owner-b")
    fake = FakeSession({(Project, pid): project})

    async def owner_a():
        return "owner-a"

    monkeypatch.setattr(chat.team, "current_owner_id", owner_a)
    monkeypatch.setattr(chat.conversations, "get_sessionmaker", lambda: _sessionmaker(fake))

    with pytest.raises(ValueError, match="Project not found"):
        await chat.create_conversation("openai/test", None, project_id=str(pid))

    assert fake.added == []
    assert fake.commits == 0


@pytest.mark.anyio
async def test_set_conversation_project_rejects_foreign_project(monkeypatch):
    cid = uuid.UUID("00000000-0000-0000-0000-000000000303")
    pid = uuid.UUID("00000000-0000-0000-0000-000000000404")
    conv = Conversation(id=cid, model="openai/test", owner_id="owner-a")
    project = Project(id=pid, name="Other project", owner_id="owner-b")
    fake = FakeSession({(Conversation, cid): conv, (Project, pid): project})

    async def owner_a():
        return "owner-a"

    monkeypatch.setattr(projects.team, "current_owner_id", owner_a)
    monkeypatch.setattr(projects, "get_sessionmaker", lambda: _sessionmaker(fake))

    assert await projects.set_conversation_project(str(cid), str(pid)) is None
    assert conv.project_id is None
    assert fake.commits == 0
