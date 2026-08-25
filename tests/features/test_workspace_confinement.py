"""Orrery Work's path boundary, attacked before any tool is allowed to use it.

ADR-007 trades isolation for confinement: commands run on the host with the user's privileges, and
the only thing standing between the model and the rest of the filesystem is that every path resolves
inside the attached folder. That makes `resolve_in_root` the most security-critical function in the
feature, so it is written and attacked on its own, before a single tool can call it.

The rule these tests encode: resolve the REAL path first, then check. Checking a string and
resolving afterwards is the classic ordering bug — a symlink passes the string test and then points
somewhere else entirely.
"""
import os
import sys

import pytest

from backend.features import workspace


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "project"
    (r / "src").mkdir(parents=True)
    (r / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    (r / "README.md").write_text("# hi", encoding="utf-8")
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / "keys.txt").write_text("sk-do-not-read", encoding="utf-8")
    return r


# --- what must work ------------------------------------------------------------------------------

def test_a_relative_path_inside_the_root_resolves(root):
    assert workspace.resolve_in_root(root, "src/main.py") == (root / "src" / "main.py").resolve()


def test_a_path_that_does_not_exist_yet_still_resolves(root):
    """Creating a file needs a resolvable target before the file exists."""
    assert workspace.resolve_in_root(root, "src/new_file.py") == (root / "src" / "new_file.py").resolve()


def test_the_root_itself_resolves(root):
    assert workspace.resolve_in_root(root, ".") == root.resolve()


def test_an_absolute_path_inside_the_root_resolves(root):
    inside = str((root / "README.md").resolve())
    assert workspace.resolve_in_root(root, inside) == (root / "README.md").resolve()


def test_backslashes_are_accepted_on_any_platform(root):
    """A model writing Windows-style separators is not an attack."""
    assert workspace.resolve_in_root(root, "src\\main.py") == (root / "src" / "main.py").resolve()


# --- what must be refused ------------------------------------------------------------------------

def test_dot_dot_traversal_is_refused(root):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace.resolve_in_root(root, "../secrets/keys.txt")


def test_deeply_buried_traversal_is_refused(root):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace.resolve_in_root(root, "src/../../secrets/keys.txt")


def test_an_absolute_path_outside_the_root_is_refused(root, tmp_path):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace.resolve_in_root(root, str(tmp_path / "secrets" / "keys.txt"))


def test_an_empty_path_is_refused(root):
    for candidate in ("", "   ", None):
        with pytest.raises(workspace.PathOutsideRoot):
            workspace.resolve_in_root(root, candidate)


def test_a_null_byte_is_refused(root):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace.resolve_in_root(root, "src/main.py\x00.txt")


@pytest.mark.parametrize("candidate", [
    r"\\?\C:\Windows\System32\drivers\etc\hosts",
    r"\\.\PhysicalDrive0",
    r"\\server\share\file.txt",
])
def test_windows_device_and_unc_paths_are_refused(root, candidate):
    """These bypass normal path semantics, so they are refused on every platform, not just Windows."""
    with pytest.raises(workspace.PathOutsideRoot):
        workspace.resolve_in_root(root, candidate)


def test_a_sibling_directory_sharing_the_root_prefix_is_refused(root, tmp_path):
    """`/tmp/project-evil` starts with `/tmp/project` as a STRING but is not inside it.

    A prefix comparison on strings instead of path components is the other classic way this is got
    wrong, and it is silent.
    """
    sibling = tmp_path / "project-evil"
    sibling.mkdir()
    (sibling / "loot.txt").write_text("x", encoding="utf-8")

    with pytest.raises(workspace.PathOutsideRoot):
        workspace.resolve_in_root(root, str(sibling / "loot.txt"))


# --- links: resolve first, then check --------------------------------------------------------

def _can_symlink(tmp_path) -> bool:
    try:
        (tmp_path / "_probe_target").write_text("x", encoding="utf-8")
        (tmp_path / "_probe_link").symlink_to(tmp_path / "_probe_target")
        return True
    except (OSError, NotImplementedError):
        return False


def test_a_symlink_pointing_outside_the_root_is_refused(root, tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("this environment cannot create symlinks")
    escape = root / "escape"
    escape.symlink_to(tmp_path / "secrets", target_is_directory=True)

    with pytest.raises(workspace.PathOutsideRoot):
        workspace.resolve_in_root(root, "escape/keys.txt")


def test_a_symlink_pointing_inside_the_root_is_allowed(root, tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("this environment cannot create symlinks")
    link = root / "shortcut.py"
    link.symlink_to(root / "src" / "main.py")

    assert workspace.resolve_in_root(root, "shortcut.py") == (root / "src" / "main.py").resolve()


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows construct")
def test_a_junction_pointing_outside_the_root_is_refused(root, tmp_path):
    target = tmp_path / "secrets"
    link = root / "junction"
    if os.system(f'mklink /J "{link}" "{target}" >nul 2>&1') != 0:
        pytest.skip("could not create a junction in this environment")

    with pytest.raises(workspace.PathOutsideRoot):
        workspace.resolve_in_root(root, "junction/keys.txt")


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitivity is the Windows behaviour")
def test_a_case_differing_path_inside_the_root_is_still_inside(root):
    """Windows paths are case-insensitive; a case-folded path is not an escape and must not read
    as one, or ordinary use breaks."""
    assert workspace.resolve_in_root(root, "SRC/MAIN.PY") == (root / "src" / "main.py").resolve()
