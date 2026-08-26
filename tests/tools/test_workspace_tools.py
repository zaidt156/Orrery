"""Orrery Work's read tools, as the registry actually runs them.

The point of routing these through the registry rather than calling `workspace.py` directly is that
scope, the ADR-004 deny hook, the approval gate and ADR-005 evidence then apply to Orrery Work
exactly as they do to everything else — Orrery Work adds capability, not a second execution path
(ADR-007 §3). These check the registry contract holds: a refusal comes back as data, never as an
exception, and a path that leaves the root is refused *by the tool*, not merely by the layer under it.
"""
import pytest

from backend.features import workspace_roots
from backend.tools import registry, workspace_tools  # noqa: F401 — imported for registration

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def orrery_work_enabled(monkeypatch):
    """Orrery Work ships off by default (ADR-007 is a real reduction in the boundary), so the tests
    that exercise the tool body have to turn it on — and the gating test below turns it back off,
    which is only a meaningful assertion because of this."""
    from backend.features import admin

    async def enabled(name):
        return name != "never"

    monkeypatch.setattr(admin, "feature_enabled", enabled)


@pytest.fixture
def root(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (project / "README.md").write_text("# Project\n", encoding="utf-8")
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / "keys.txt").write_text("sk-do-not-read", encoding="utf-8")

    async def attached(_root_id=None):
        return str(project.resolve())

    monkeypatch.setattr(workspace_roots, "root_path", attached)
    monkeypatch.setattr(workspace_tools.workspace_roots, "root_path", attached)
    return project


async def test_the_three_read_tools_are_registered():
    keys = {t["key"] for t in registry.list_tools()}
    assert {"work_read", "work_glob", "work_grep"} <= keys


async def test_read_returns_the_file(root):
    out = await registry.run_tool("work_read", {"path": "src/main.py"})

    assert out["ok"] is True
    assert "print('hello')" in out["text"]


async def test_a_path_outside_the_root_comes_back_as_data_not_an_exception(root):
    """The registry's contract: `run_tool` never raises. A tool that let one through would take
    down whatever loop was driving it instead of letting the model correct itself."""
    out = await registry.run_tool("work_read", {"path": "../secrets/keys.txt"})

    assert out["ok"] is False
    assert "outside" in out["error"].lower()
    assert "sk-do-not-read" not in str(out)


async def test_glob_lists_matching_files(root):
    out = await registry.run_tool("work_glob", {"pattern": "src/*.py"})

    assert out["ok"] is True
    assert out["paths"] == ["src/main.py"]


async def test_grep_finds_a_line(root):
    out = await registry.run_tool("work_grep", {"expression": "hello"})

    assert out["ok"] is True
    assert out["matches"][0]["path"] == "src/main.py"


async def test_a_bad_expression_is_reported_rather_than_thrown(root):
    out = await registry.run_tool("work_grep", {"expression": "unclosed (group"})

    assert out["ok"] is False
    assert "expression" in out["error"]


async def test_with_no_folder_attached_the_tool_says_how_to_attach_one(root, monkeypatch):
    async def nothing_attached(_root_id=None):
        raise workspace_roots.UnknownRoot("No folder is attached yet. Attach the folder you want "
                                          "worked on in Orrery Work.")

    monkeypatch.setattr(workspace_tools.workspace_roots, "root_path", nothing_attached)

    out = await registry.run_tool("work_read", {"path": "src/main.py"})

    assert out["ok"] is False
    assert "Attach the folder" in out["error"]


async def test_the_read_tools_are_read_risk_and_do_not_claim_to_write():
    """`writes` drives the approval gate. A read tool marked as writing would ask for approval it
    doesn't need; one marked wrongly the other way is how a write slips past the gate."""
    for key in ("work_read", "work_glob", "work_grep"):
        tool = registry.get_tool(key)
        assert tool.writes is False
        assert tool.risk == "sensitive_read"   # an attached folder is the user's real files
        assert tool.feature_flag == "orrery_work"


async def test_the_tools_are_gated_by_the_orrery_work_flag(root, monkeypatch):
    from backend.features import admin

    async def disabled(_name):
        return False

    monkeypatch.setattr(admin, "feature_enabled", disabled)

    out = await registry.run_tool("work_read", {"path": "src/main.py"})

    assert out["ok"] is False
    assert out["code"] == "feature_disabled"


# --- running a command ----------------------------------------------------------------------------

async def test_run_needs_approval_and_does_not_run_without_it(root):
    """The gate is the whole point of routing this through the registry. Without an approval the
    command must not have started — not "started and been reported"."""
    out = await registry.run_tool("work_run", {"root_id": "abc", "command": "echo hello"})

    assert out["ok"] is False
    assert out["code"] == "approval_required"
    assert "echo hello" in out["approval"]["summary"]   # the command, not "Run a tool"


async def test_run_is_remembered_per_folder_not_as_a_blanket_grant():
    """Approving `ls` in one folder must not pre-approve anything in another. Blanket is too broad
    to be honest; per-command is too narrow to live with, since a build is dozens of them."""
    from backend.features import approvals

    one = approvals._remember_key("work_run", {"root_id": "folder-one", "command": "ls"})
    two = approvals._remember_key("work_run", {"root_id": "folder-two", "command": "ls"})

    assert one != two
    assert one == approvals._remember_key("work_run", {"root_id": "folder-one", "command": "pytest"})


async def test_run_will_not_accept_whatever_folder_happens_to_be_current(root):
    """A remembered approval must not survive the user attaching a different folder, which is only
    guaranteed if the dangerous tool names its boundary instead of inheriting it."""
    out = await registry.run_tool("work_run", {"command": "echo hello"})

    assert out["ok"] is False
    assert out["code"] == "validation_failed"


async def test_run_reports_that_it_writes_so_the_gate_applies():
    tool = registry.get_tool("work_run")

    assert tool.writes is True
    assert tool.risk in {"external_write", "destructive"}
    assert tool.feature_flag == "orrery_work"


async def test_an_approved_command_actually_runs(root, monkeypatch):
    from backend.features import approvals

    async def approved(_tool, _args, _approval_id=None):
        return {"allowed": True}

    monkeypatch.setattr(approvals, "gate", approved)

    out = await registry.run_tool(
        "work_run", {"root_id": "abc", "command": "python -c \"print('ran')\""}
    )

    assert out["ok"] is True
    assert "ran" in out["stdout"]
    assert out["cwd"] == str(root.resolve())


async def test_a_machine_destroying_command_is_refused_as_data(root, monkeypatch):
    from backend.features import approvals

    async def approved(_tool, _args, _approval_id=None):
        return {"allowed": True}

    monkeypatch.setattr(approvals, "gate", approved)

    out = await registry.run_tool("work_run", {"root_id": "abc", "command": "rm -rf /"})

    assert out["ok"] is False
    assert "destroys the machine" in out["error"]


# --- changing files -----------------------------------------------------------------------------
#
# These are the irreversible ones. What matters at this layer is not that the bytes land — that is
# covered in test_workspace_write.py — but that the gate applies, that the record is written, and
# that a refusal comes back as data with the file untouched.

def _approve_everything(monkeypatch):
    from backend.features import approvals

    async def approved(_tool, _args, _approval_id=None):
        return {"allowed": True}

    monkeypatch.setattr(approvals, "gate", approved)


@pytest.fixture
def logged(monkeypatch):
    """A stand-in for the durable log, so the tool contract can be checked without a database."""
    entries = []

    async def begin(root_id, change):
        entries.append({"root_id": root_id, **change, "status": "started"})
        return str(len(entries) - 1)

    async def finish(entry_id, change):
        entries[int(entry_id)].update(change, status="done")

    async def fail(entry_id, reason):
        entries[int(entry_id)].update(status="failed", error=reason)

    monkeypatch.setattr(workspace_tools.workspace_log, "begin", begin)
    monkeypatch.setattr(workspace_tools.workspace_log, "finish", finish)
    monkeypatch.setattr(workspace_tools.workspace_log, "fail", fail)
    return entries


async def test_the_write_tools_are_registered():
    keys = {t["key"] for t in registry.list_tools()}
    assert {"work_write", "work_edit", "work_delete", "work_changes"} <= keys


async def test_writing_needs_approval_and_names_the_file(root):
    out = await registry.run_tool(
        "work_write", {"root_id": "abc", "path": "notes.md", "content": "# hi"}
    )

    assert out["ok"] is False
    assert out["code"] == "approval_required"
    assert "notes.md" in out["approval"]["summary"]
    assert not (root / "notes.md").exists()   # refused means nothing was written


async def test_an_approved_write_lands_and_is_recorded(root, logged, monkeypatch):
    _approve_everything(monkeypatch)

    out = await registry.run_tool(
        "work_write", {"root_id": "abc", "path": "notes.md", "content": "# hi"}
    )

    assert out["ok"] is True
    assert (root / "notes.md").read_text(encoding="utf-8") == "# hi"
    assert [(e["path"], e["action"], e["status"]) for e in logged] == [("notes.md", "created", "done")]


async def test_a_write_that_fails_still_leaves_a_record(root, logged, monkeypatch):
    """The record exists to answer "what did it try to do", not only "what worked". A failed attempt
    that vanished from the log would be indistinguishable from one that never happened."""
    _approve_everything(monkeypatch)

    out = await registry.run_tool(
        "work_write", {"root_id": "abc", "path": "src", "content": "over a directory"}
    )

    assert out["ok"] is False
    assert logged[0]["status"] == "failed"
    assert logged[0]["path"] == "src"


async def test_a_path_outside_the_root_is_refused_and_never_recorded(root, logged, monkeypatch):
    """The boundary check runs before the record is opened, so a refused path leaves no row — it was
    never a change to this folder in the first place."""
    _approve_everything(monkeypatch)

    out = await registry.run_tool(
        "work_write", {"root_id": "abc", "path": "../secrets/keys.txt", "content": "x"}
    )

    assert out["ok"] is False
    assert "outside" in out["error"].lower()
    assert logged == []


async def test_an_edit_carries_the_digest_of_what_was_read(root, logged, monkeypatch):
    from backend.features import workspace_write
    _approve_everything(monkeypatch)
    observed = workspace_write.digest_of((root / "src" / "main.py").read_bytes())

    out = await registry.run_tool(
        "work_edit",
        {"root_id": "abc", "path": "src/main.py", "observed_digest": observed,
         "content": "print('edited')\n"},
    )

    assert out["ok"] is True
    assert (root / "src" / "main.py").read_text(encoding="utf-8") == "print('edited')\n"


async def test_an_edit_against_stale_content_comes_back_as_data(root, logged, monkeypatch):
    _approve_everything(monkeypatch)

    out = await registry.run_tool(
        "work_edit",
        {"root_id": "abc", "path": "src/main.py", "observed_digest": "0" * 64, "content": "x"},
    )

    assert out["ok"] is False
    assert "read it again" in out["error"]
    assert (root / "src" / "main.py").read_text(encoding="utf-8") == "print('hello')\n"


async def test_deleting_is_destructive_so_it_can_never_be_pre_approved():
    """security.md §4: deletes are the canonical case for an approval gate that always asks. The
    registry already refuses to remember a `destructive` tool — this is what opts delete into that."""
    from backend.features import approvals

    assert registry.get_tool("work_delete").risk == "destructive"
    assert registry.get_tool("work_delete").risk in approvals.GATED_RISKS


async def test_writing_is_remembered_per_folder_not_across_all_of_them():
    from backend.features import approvals

    here = approvals._remember_key("work_write", {"root_id": "folder-one", "path": "a"})
    there = approvals._remember_key("work_write", {"root_id": "folder-two", "path": "a"})

    assert here != there
    assert here == approvals._remember_key("work_write", {"root_id": "folder-one", "path": "b"})


async def test_the_write_tools_require_a_folder_rather_than_inheriting_one(root):
    """Same reason as work_run: an approval remembered for a folder must not survive the user
    attaching a different one."""
    for key, args in (
        ("work_write", {"path": "a.txt", "content": "x"}),
        ("work_edit", {"path": "a.txt", "observed_digest": "0" * 64, "content": "x"}),
        ("work_delete", {"path": "a.txt"}),
    ):
        out = await registry.run_tool(key, args)
        assert out["code"] == "validation_failed", f"{key} accepted a call with no root_id"


async def test_the_change_log_can_be_read_back(root, monkeypatch):
    """A log nobody can read is not a compensating control. ADR-007 traded diff review for this."""
    async def history(root_id, limit=50):
        return [{"path": "notes.md", "action": "created", "status": "done"}]

    monkeypatch.setattr(workspace_tools.workspace_log, "history", history)

    out = await registry.run_tool("work_changes", {"root_id": "abc"})

    assert out["ok"] is True
    assert out["changes"][0]["path"] == "notes.md"
