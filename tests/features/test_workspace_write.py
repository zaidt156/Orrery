"""Writing to the attached folder — the only irreversible thing Orrery Work does.

ADR-007 traded diff-review away for a write log. That trade only pays if two things hold: the write
itself never lands outside the root, and every write is describable afterwards without asking the
model what it did. This file covers the first half and the facts the second half is built from; the
durable record lives in `test_workspace_log.py`.

The observed-version rule is the interesting one. `edit_file` takes the digest of the content the
caller actually read, and refuses if the file has changed since. That is not concurrency theatre —
it removes the class of failure where a model reads a file, thinks for thirty seconds while a build
or another edit rewrites it, and then writes back a version derived from something that is gone.
"""
import pytest

from backend.features import workspace, workspace_write


@pytest.fixture
def root(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / "keys.txt").write_text("sk-do-not-touch", encoding="utf-8")
    return project


# --- creating and overwriting ---------------------------------------------------------------------

def test_writing_a_new_file_creates_it_and_says_so(root):
    out = workspace_write.write_file(root, "notes.md", "# Notes\n")

    assert (root / "notes.md").read_text(encoding="utf-8") == "# Notes\n"
    assert out["action"] == "created"
    assert out["path"] == "notes.md"
    assert out["digest_before"] is None      # nothing was there to have a digest
    assert out["digest_after"] == workspace_write.digest_of("# Notes\n".encode())


def test_writing_over_an_existing_file_reports_it_as_a_modification(root):
    before = (root / "src" / "main.py").read_bytes()

    out = workspace_write.write_file(root, "src/main.py", "print('bye')\n")

    assert out["action"] == "modified"
    assert out["digest_before"] == workspace_write.digest_of(before)
    assert out["digest_after"] != out["digest_before"]


def test_writing_creates_missing_parent_directories(root):
    """A model asked to add `src/api/routes.py` should not have to mkdir first — but the new
    directories are inside the root like everything else."""
    workspace_write.write_file(root, "src/api/routes.py", "x = 1\n")

    assert (root / "src" / "api" / "routes.py").read_text(encoding="utf-8") == "x = 1\n"


def test_writing_outside_the_root_is_refused_and_changes_nothing(root, tmp_path):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace_write.write_file(root, "../secrets/keys.txt", "overwritten")

    assert (tmp_path / "secrets" / "keys.txt").read_text(encoding="utf-8") == "sk-do-not-touch"


def test_writing_over_a_directory_is_refused(root):
    with pytest.raises(IsADirectoryError):
        workspace_write.write_file(root, "src", "not a file")


def test_a_write_larger_than_the_cap_is_refused_before_anything_is_written(root):
    with pytest.raises(ValueError, match="too large"):
        workspace_write.write_file(root, "big.txt", "x" * (workspace_write.MAX_WRITE_BYTES + 1))

    assert not (root / "big.txt").exists()


def test_a_write_is_atomic_so_a_failure_cannot_leave_half_a_file(root, monkeypatch):
    """Writing in place means a crash mid-write leaves a truncated file and the original gone. The
    content goes to a temporary file in the same directory and is then moved into place."""
    original = (root / "src" / "main.py").read_text(encoding="utf-8")
    real_replace = workspace_write.os.replace

    def fail_on_move(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(workspace_write.os, "replace", fail_on_move)
    with pytest.raises(OSError):
        workspace_write.write_file(root, "src/main.py", "half written")
    monkeypatch.setattr(workspace_write.os, "replace", real_replace)

    assert (root / "src" / "main.py").read_text(encoding="utf-8") == original
    leftovers = [p.name for p in (root / "src").iterdir() if p.name != "main.py"]
    assert leftovers == [], f"a temporary file was left behind: {leftovers}"


# --- editing against what was actually read ---------------------------------------------------------

def test_an_edit_matching_the_observed_digest_is_applied(root):
    seen = workspace.read_file(root, "src/main.py")
    observed = workspace_write.digest_of(seen["text"].encode())

    out = workspace_write.edit_file(root, "src/main.py", observed, "print('edited')\n")

    assert (root / "src" / "main.py").read_text(encoding="utf-8") == "print('edited')\n"
    assert out["action"] == "modified"


def test_an_edit_against_a_stale_digest_is_refused(root):
    """The whole point: the model read a file, something else rewrote it, and the edit it computed
    is derived from content that no longer exists. Refuse rather than clobber."""
    stale = workspace_write.digest_of(b"print('hi')\n")
    (root / "src" / "main.py").write_text("print('someone else got here')\n", encoding="utf-8")

    with pytest.raises(workspace_write.StaleContent):
        workspace_write.edit_file(root, "src/main.py", stale, "print('edited')\n")

    assert (root / "src" / "main.py").read_text(encoding="utf-8") == "print('someone else got here')\n"


def test_the_stale_refusal_says_what_to_do_about_it(root):
    stale = workspace_write.digest_of(b"whatever")

    with pytest.raises(workspace_write.StaleContent, match="read it again"):
        workspace_write.edit_file(root, "src/main.py", stale, "x")


def test_editing_a_file_that_does_not_exist_is_not_a_silent_create(root):
    """`edit` means "change what is there". Creating on a miss would let a mistyped path invent a
    file somewhere nobody looks."""
    with pytest.raises(FileNotFoundError):
        workspace_write.edit_file(root, "src/nope.py", workspace_write.digest_of(b""), "x")


def test_an_edit_outside_the_root_is_refused(root):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace_write.edit_file(root, "../secrets/keys.txt", workspace_write.digest_of(b""), "x")


# --- deleting ---------------------------------------------------------------------------------------

def test_deleting_a_file_removes_it_and_records_what_was_there(root):
    before = (root / "src" / "main.py").read_bytes()

    out = workspace_write.delete_file(root, "src/main.py")

    assert not (root / "src" / "main.py").exists()
    assert out["action"] == "deleted"
    assert out["digest_before"] == workspace_write.digest_of(before)
    assert out["digest_after"] is None


def test_deleting_a_directory_is_refused(root):
    """One file at a time. Removing a tree is a much larger hammer than this tool's log can honestly
    describe — it goes through `work_run`, where the user sees the command."""
    with pytest.raises(IsADirectoryError):
        workspace_write.delete_file(root, "src")

    assert (root / "src").is_dir()


def test_deleting_something_that_is_not_there_says_so(root):
    with pytest.raises(FileNotFoundError):
        workspace_write.delete_file(root, "src/nope.py")


def test_deleting_outside_the_root_is_refused(root, tmp_path):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace_write.delete_file(root, "../secrets/keys.txt")

    assert (tmp_path / "secrets" / "keys.txt").exists()


# --- the facts the log is built from ---------------------------------------------------------------

def test_every_operation_reports_the_same_shape(root):
    """The log records one row per mutation, so all three have to describe themselves the same way
    or the recording code grows a branch per operation and drifts."""
    created = workspace_write.write_file(root, "a.txt", "one")
    modified = workspace_write.write_file(root, "a.txt", "two")
    deleted = workspace_write.delete_file(root, "a.txt")

    for out in (created, modified, deleted):
        assert set(out) == {"path", "action", "digest_before", "digest_after", "bytes_after"}
    assert [o["action"] for o in (created, modified, deleted)] == ["created", "modified", "deleted"]
    assert deleted["bytes_after"] == 0


def test_a_digest_is_of_the_bytes_not_the_text(root):
    """Line endings and encoding differences are real differences. Digesting the decoded string
    would call two genuinely different files identical."""
    assert workspace_write.digest_of(b"a\r\n") != workspace_write.digest_of(b"a\n")


# --- abuse cases ------------------------------------------------------------------------------------

def _can_symlink(tmp_path) -> bool:
    try:
        (tmp_path / "_probe_target").write_text("x", encoding="utf-8")
        (tmp_path / "_probe_link").symlink_to(tmp_path / "_probe_target")
        return True
    except (OSError, NotImplementedError):
        return False


def test_a_write_through_a_symlink_pointing_outside_the_root_is_refused(root, tmp_path):
    """The classic escape, on the write path this time. `../` is the obvious attempt; a link is the
    one that passes a string check and lands somewhere else entirely."""
    if not _can_symlink(tmp_path):
        pytest.skip("this environment cannot create symlinks")
    (root / "escape.txt").symlink_to(tmp_path / "secrets" / "keys.txt")

    with pytest.raises(workspace.PathOutsideRoot):
        workspace_write.write_file(root, "escape.txt", "overwritten")

    assert (tmp_path / "secrets" / "keys.txt").read_text(encoding="utf-8") == "sk-do-not-touch"


def test_a_delete_through_a_symlink_pointing_outside_the_root_is_refused(root, tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("this environment cannot create symlinks")
    (root / "escape.txt").symlink_to(tmp_path / "secrets" / "keys.txt")

    with pytest.raises(workspace.PathOutsideRoot):
        workspace_write.delete_file(root, "escape.txt")

    assert (tmp_path / "secrets" / "keys.txt").exists()


def test_a_write_into_a_directory_that_is_a_link_out_of_the_root_is_refused(root, tmp_path):
    """Not the leaf but a parent — `outbound/new.txt` looks like a child right up until `outbound`
    turns out to point somewhere else."""
    if not _can_symlink(tmp_path):
        pytest.skip("this environment cannot create symlinks")
    (root / "outbound").symlink_to(tmp_path / "secrets", target_is_directory=True)

    with pytest.raises(workspace.PathOutsideRoot):
        workspace_write.write_file(root, "outbound/planted.txt", "x")

    assert not (tmp_path / "secrets" / "planted.txt").exists()


def test_the_recorded_path_is_the_resolved_one_not_the_one_that_was_typed(root):
    """The log is an audit record, so it has to describe what happened rather than echo back what
    was asked for. `src/../src/main.py` and `src/main.py` are the same file and must read the same
    in the record, or two rows describe one file and neither is obviously canonical."""
    out = workspace_write.write_file(root, "src/../src/main.py", "print('x')\n")

    assert out["path"] == "src/main.py"
