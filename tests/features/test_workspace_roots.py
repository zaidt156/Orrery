"""Attaching a folder, remembering it, and keeping it to its owner.

The identity half of Orrery Work: which folder, whose, and which one is current. The boundary half
lives in `test_workspace_confinement.py` and has no database in it at all — the separation is
deliberate, so the security-critical code stays testable without one.
"""
import asyncio
import sys

import pytest

from backend.features import workspace, workspace_roots

# Real persistence, so this needs the PostgreSQL `docker compose up -d` provides.
pytestmark = [pytest.mark.db, pytest.mark.anyio]

# psycopg async needs the SelectorEventLoop on Windows (same as the app itself)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
async def clean():
    """A known-empty table. Roots persist by design, so a leftover from another test is a root."""
    from sqlalchemy import delete

    from backend.core.database import get_sessionmaker
    from backend.core.migrations import run_migrations
    from backend.core.models import WorkspaceRoot

    await run_migrations()
    async with get_sessionmaker()() as s:
        await s.execute(delete(WorkspaceRoot))
        await s.commit()
    yield
    async with get_sessionmaker()() as s:
        await s.execute(delete(WorkspaceRoot))
        await s.commit()


async def test_attaching_a_folder_makes_it_the_current_one(clean, tmp_path):
    project = tmp_path / "my-app"
    project.mkdir()

    attached = await workspace_roots.attach(str(project))

    assert attached["active"] is True
    assert attached["label"] == "my-app"          # the folder's own name, not the whole path
    assert (await workspace_roots.active_root())["id"] == attached["id"]


async def test_only_one_folder_is_current_at_a_time(clean, tmp_path):
    """"The attached folder" has to have one answer, or every tool needs to ask which."""
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()

    await workspace_roots.attach(str(first))
    await workspace_roots.attach(str(second))

    assert (await workspace_roots.active_root())["path"] == str(second.resolve())
    assert [r["active"] for r in await workspace_roots.list_roots()].count(True) == 1


async def test_re_attaching_a_known_folder_reuses_it_instead_of_duplicating(clean, tmp_path):
    project = tmp_path / "my-app"
    project.mkdir()

    first = await workspace_roots.attach(str(project))
    await workspace_roots.attach(str(tmp_path))          # switch away
    again = await workspace_roots.attach(str(project))

    assert again["id"] == first["id"]
    assert len(await workspace_roots.list_roots()) == 2


async def test_a_remembered_folder_can_be_made_current_again(clean, tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    kept = await workspace_roots.attach(str(first))
    await workspace_roots.attach(str(second))

    await workspace_roots.activate(kept["id"])

    assert (await workspace_roots.active_root())["id"] == kept["id"]


async def test_detaching_forgets_the_folder_without_touching_it(clean, tmp_path):
    project = tmp_path / "my-app"
    project.mkdir()
    (project / "keep.txt").write_text("still here", encoding="utf-8")
    attached = await workspace_roots.attach(str(project))

    await workspace_roots.detach(attached["id"])

    assert await workspace_roots.list_roots() == []
    assert (project / "keep.txt").read_text(encoding="utf-8") == "still here"


async def test_the_whole_disk_is_refused_before_anything_is_written_down(clean, tmp_path, monkeypatch):
    """The vet runs first, so a root that empties confinement never reaches the database."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(workspace.Path, "home", classmethod(lambda _cls: home))

    with pytest.raises(workspace.UnattachableRoot):
        await workspace_roots.attach(str(home))

    assert await workspace_roots.list_roots() == []


async def test_a_tool_asking_for_the_root_with_nothing_attached_is_told_what_to_do(clean):
    with pytest.raises(workspace_roots.UnknownRoot, match="Attach the folder"):
        await workspace_roots.root_path()


async def test_a_root_that_is_not_yours_reads_as_one_that_does_not_exist(clean, tmp_path, monkeypatch):
    """Distinguishing "someone else's" from "no such thing" would let a team member enumerate which
    folders their colleagues have attached."""
    project = tmp_path / "my-app"
    project.mkdir()
    monkeypatch.setattr(workspace_roots.team, "current_owner_id", _owner("alice"))
    attached = await workspace_roots.attach(str(project))

    monkeypatch.setattr(workspace_roots.team, "current_owner_id", _owner("bob"))

    with pytest.raises(workspace_roots.UnknownRoot, match="not attached"):
        await workspace_roots.root_path(attached["id"])
    assert await workspace_roots.list_roots() == []
    assert await workspace_roots.active_root() is None


async def test_a_malformed_root_id_is_refused_rather_than_raising_at_the_caller(clean):
    with pytest.raises(workspace_roots.UnknownRoot):
        await workspace_roots.root_path("not-a-uuid")


def _owner(value):
    async def current_owner_id():
        return value
    return current_owner_id
