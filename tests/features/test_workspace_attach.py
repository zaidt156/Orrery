"""Which folders may be attached at all.

ADR-007 puts the whole security model on one sentence: the attached folder is the boundary. That
sentence is only worth anything if the folder is a project. Attach `C:\\` and confinement is
technically intact and completely worthless — every check still passes, and the model has the disk.

So this is not a convenience validation. It is the assumption ADR-007 rests on, checked once, at
the only moment it can be: when the folder is chosen.
"""
import sys
from pathlib import Path

import pytest

from backend.features import workspace


def test_a_normal_project_folder_is_fine(tmp_path):
    project = tmp_path / "work" / "my-app"
    project.mkdir(parents=True)
    assert workspace.check_attachable(project) == project.resolve()


def test_a_folder_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(workspace.UnattachableRoot, match="does not exist"):
        workspace.check_attachable(tmp_path / "nope")


def test_a_file_is_not_a_folder(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(workspace.UnattachableRoot, match="not a folder"):
        workspace.check_attachable(target)


def test_the_whole_filesystem_is_refused():
    """The one that makes confinement meaningless while leaving every check passing."""
    root = "C:\\" if sys.platform == "win32" else "/"
    with pytest.raises(workspace.UnattachableRoot):
        workspace.check_attachable(root)


def test_the_home_directory_itself_is_refused(tmp_path, monkeypatch):
    """A whole home directory is documents, keys, browser profiles and every other project. Its
    subfolders are exactly what people want to attach, so only the directory itself is refused."""
    home = tmp_path / "home" / "someone"
    (home / "projects" / "app").mkdir(parents=True)
    monkeypatch.setattr(workspace.Path, "home", classmethod(lambda _cls: home))

    with pytest.raises(workspace.UnattachableRoot, match="home"):
        workspace.check_attachable(home)
    assert workspace.check_attachable(home / "projects" / "app")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system paths")
def test_windows_system_directories_are_refused():
    for path in ("C:\\Windows", "C:\\Windows\\System32", "C:\\Program Files"):
        with pytest.raises(workspace.UnattachableRoot):
            workspace.check_attachable(path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX system paths")
def test_posix_system_directories_are_refused():
    for path in ("/etc", "/usr", "/bin", "/var"):
        with pytest.raises(workspace.UnattachableRoot):
            workspace.check_attachable(path)


def test_the_refusal_says_what_to_do_instead(tmp_path):
    """A rejection the user can't act on just reads as the app being broken."""
    with pytest.raises(workspace.UnattachableRoot) as exc:
        workspace.check_attachable(tmp_path / "missing")
    assert "folder" in str(exc.value).lower()


def test_a_scratch_folder_in_the_systems_temp_directory_is_attachable(tmp_path):
    """macOS puts the per-user temp directory under /private/var/folders/… — inside two paths that
    are otherwise system-owned. A scratch folder there belongs to the user, not the OS, and refusing
    it made `check_attachable` reject an ordinary working folder on every Mac (and every macOS CI
    run, which is how this was found)."""
    import tempfile

    scratch = Path(tempfile.mkdtemp(dir=tmp_path))
    assert workspace.check_attachable(scratch) == scratch.resolve()


def test_the_macos_shaped_temp_path_is_not_read_as_a_system_directory(monkeypatch):
    """Pinned on every platform, not just macOS, so the intent survives a machine that cannot
    reproduce the shape."""
    import tempfile

    monkeypatch.setattr(tempfile, "gettempdir", lambda: "/private/var/folders/xy/T")

    assert not workspace._is_system_directory(Path("/private/var/folders/xy/T/pytest-0/project"))
    # …and the exemption stays narrow: the rest of /var is still the operating system's.
    assert workspace._is_system_directory(Path("/private/var/db/something"))
    assert workspace._is_system_directory(Path("/etc/ssh"))
