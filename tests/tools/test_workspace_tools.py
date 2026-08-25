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
