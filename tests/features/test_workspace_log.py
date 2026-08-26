"""The write log: what Orrery Work gives back in exchange for not reviewing diffs.

ADR-007 traded diff-then-apply away. The compensating control is this record, and a record is only
worth the trade if it cannot quietly miss a change. So the row is opened **before** the bytes move
and completed after — the same shape ADR-005 already uses for tool dispatch, and for the same
reason: it is what lets "never happened" be told apart from "outcome unknown".

The failure this design refuses to allow is a mutation with no row. A row with no mutation is
recoverable — it says `started`, and the digest proves the file was never touched. The reverse is
not recoverable at all, because nothing knows to look.
"""
import asyncio
import sys

import pytest

from backend.features import workspace_log, workspace_roots

pytestmark = [pytest.mark.db, pytest.mark.anyio]

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
async def attached(tmp_path):
    from sqlalchemy import delete

    from backend.core.database import get_sessionmaker
    from backend.core.migrations import run_migrations
    from backend.core.models import WorkspaceRoot, WorkspaceWrite

    await run_migrations()
    async with get_sessionmaker()() as s:
        await s.execute(delete(WorkspaceWrite))
        await s.execute(delete(WorkspaceRoot))
        await s.commit()

    project = tmp_path / "project"
    project.mkdir()
    root = await workspace_roots.attach(str(project))
    yield root

    async with get_sessionmaker()() as s:
        await s.execute(delete(WorkspaceWrite))
        await s.execute(delete(WorkspaceRoot))
        await s.commit()


def _change(**overrides):
    base = {"path": "src/main.py", "action": "modified",
            "digest_before": "a" * 64, "digest_after": "b" * 64, "bytes_after": 12}
    base.update(overrides)
    return base


# --- the record ------------------------------------------------------------------------------------

async def test_a_completed_write_is_recorded_with_both_digests(attached):
    entry = await workspace_log.begin(attached["id"], _change())
    await workspace_log.finish(entry, _change())

    [row] = await workspace_log.history(attached["id"])
    assert row["path"] == "src/main.py"
    assert row["action"] == "modified"
    assert row["digest_before"] == "a" * 64
    assert row["digest_after"] == "b" * 64
    assert row["status"] == "done"


async def test_the_row_exists_before_the_bytes_move(attached):
    """The ordering is the guarantee. If the process dies between the write and the record, an
    unlogged mutation is invisible forever — so the row is opened first and says so."""
    entry = await workspace_log.begin(attached["id"], _change())

    [row] = await workspace_log.history(attached["id"])
    assert row["status"] == "started"
    assert row["digest_before"] == "a" * 64
    assert row["digest_after"] is None      # nothing has happened to the file yet
    assert entry is not None


async def test_a_write_that_failed_is_recorded_as_failed_not_erased(attached):
    """Deleting the row would make a failed attempt indistinguishable from one that never happened,
    and an attempt to overwrite a file is worth knowing about even when it did not land."""
    entry = await workspace_log.begin(attached["id"], _change())
    await workspace_log.fail(entry, "disk full")

    [row] = await workspace_log.history(attached["id"])
    assert row["status"] == "failed"
    assert row["digest_after"] is None
    assert "disk full" in row["error"]


async def test_history_is_newest_first(attached):
    for name in ("one.txt", "two.txt", "three.txt"):
        entry = await workspace_log.begin(attached["id"], _change(path=name, action="created"))
        await workspace_log.finish(entry, _change(path=name, action="created"))

    assert [r["path"] for r in await workspace_log.history(attached["id"])] == [
        "three.txt", "two.txt", "one.txt"
    ]


async def test_history_is_bounded(attached):
    for i in range(12):
        entry = await workspace_log.begin(attached["id"], _change(path=f"f{i}.txt"))
        await workspace_log.finish(entry, _change(path=f"f{i}.txt"))

    assert len(await workspace_log.history(attached["id"], limit=5)) == 5


# --- ownership and lifetime --------------------------------------------------------------------------

async def test_the_log_of_a_root_that_is_not_yours_is_not_readable(attached, monkeypatch):
    entry = await workspace_log.begin(attached["id"], _change())
    await workspace_log.finish(entry, _change())

    async def someone_else():
        return "bob"

    monkeypatch.setattr(workspace_roots.team, "current_owner_id", someone_else)
    monkeypatch.setattr(workspace_log.team, "current_owner_id", someone_else)

    with pytest.raises(workspace_roots.UnknownRoot):
        await workspace_log.history(attached["id"])


async def test_detaching_a_folder_takes_its_log_with_it(attached):
    """The log describes changes to a folder. Keeping rows for a folder the user has told Orrery to
    forget is a record they did not ask to keep, pointing at paths Orrery can no longer resolve."""
    entry = await workspace_log.begin(attached["id"], _change())
    await workspace_log.finish(entry, _change())

    await workspace_roots.detach(attached["id"])

    from sqlalchemy import func, select

    from backend.core.database import get_sessionmaker
    from backend.core.models import WorkspaceWrite
    async with get_sessionmaker()() as s:
        remaining = (await s.execute(select(func.count()).select_from(WorkspaceWrite))).scalar_one()
    assert remaining == 0


async def test_recording_against_a_root_that_is_not_attached_is_refused(attached):
    import uuid

    with pytest.raises(workspace_roots.UnknownRoot):
        await workspace_log.begin(str(uuid.uuid4()), _change())


# --- the tools against the real log, not a stand-in --------------------------------------------------

async def test_a_write_through_the_registry_lands_in_the_real_log(attached, monkeypatch):
    """The tool tests use a fake log so they can run without a database. A fake can drift from the
    real signature and nothing notices — the whole feature would then write files and record
    nothing. This is the one test that proves the wiring, end to end, against real Postgres.
    """
    from backend.features import admin, approvals
    from backend.tools import registry

    async def enabled(_name):
        return True

    async def approved(_tool, _args, _approval_id=None):
        return {"allowed": True}

    monkeypatch.setattr(admin, "feature_enabled", enabled)
    monkeypatch.setattr(approvals, "gate", approved)

    root_path = (await workspace_roots.active_root())["path"]

    created = await registry.run_tool(
        "work_write", {"root_id": attached["id"], "path": "notes.md", "content": "# hi\n"}
    )
    assert created["ok"] is True, created

    from pathlib import Path
    assert (Path(root_path) / "notes.md").read_text(encoding="utf-8") == "# hi\n"

    seen = await registry.run_tool("work_changes", {"root_id": attached["id"]})
    assert seen["ok"] is True
    [row] = seen["changes"]
    assert (row["path"], row["action"], row["status"]) == ("notes.md", "created", "done")
    assert row["digest_before"] is None
    assert row["digest_after"] is not None
    assert row["bytes_after"] == len("# hi\n")


async def test_a_delete_through_the_registry_records_what_was_removed(attached, monkeypatch):
    from pathlib import Path

    from backend.features import admin, approvals
    from backend.tools import registry

    async def enabled(_name):
        return True

    async def approved(_tool, _args, _approval_id=None):
        return {"allowed": True}

    monkeypatch.setattr(admin, "feature_enabled", enabled)
    monkeypatch.setattr(approvals, "gate", approved)

    root_path = Path((await workspace_roots.active_root())["path"])
    (root_path / "doomed.txt").write_text("bye", encoding="utf-8")

    out = await registry.run_tool(
        "work_delete", {"root_id": attached["id"], "path": "doomed.txt"}
    )

    assert out["ok"] is True
    assert not (root_path / "doomed.txt").exists()
    [row] = await workspace_log.history(attached["id"])
    assert row["action"] == "deleted"
    assert row["digest_before"] is not None   # what was destroyed is still described
    assert row["digest_after"] is None
