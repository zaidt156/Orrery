"""Generated-file storage + TTL cleanup (architecture plan #18)."""

import io
import os
import time
import zipfile

import pytest
from backend.features import files
from backend.features.sandbox import SandboxFile


def test_cleanup_removes_expired_only(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_DIR", tmp_path)
    old = tmp_path / "old.bin"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 99_999, time.time() - 99_999))  # well past the TTL
    fresh = tmp_path / "fresh.bin"
    fresh.write_bytes(b"y")

    removed = files.cleanup(ttl_hours=1)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_cleanup_disabled_when_ttl_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_DIR", tmp_path)
    f = tmp_path / "keep.bin"
    f.write_bytes(b"z")
    os.utime(f, (time.time() - 99_999, time.time() - 99_999))
    assert files.cleanup(ttl_hours=0) == 0
    assert f.exists()


def test_store_app_bundle_creates_zip_and_extracted_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_DIR", tmp_path)
    members = [
        SandboxFile("index.html", b"<html><body>Expense splitter</body></html>"),
        SandboxFile("assets/app.js", b"document.body.dataset.ready = 'yes';"),
        SandboxFile("styles.css", b"body { color: navy; }"),
    ]

    meta = files.store_app_bundle("expense-splitter.zip", members)

    assert meta["name"] == "expense-splitter.zip"
    assert meta["mime"] == "application/zip"
    assert meta["artifact_type"] == "app_bundle"
    assert meta["member_count"] == 3
    loaded_meta, archive = files.load(meta["id"])
    assert loaded_meta == meta
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert bundle.namelist() == ["assets/app.js", "index.html", "styles.css"]
        assert bundle.read("index.html") == members[0].data
    preview = tmp_path / "apps" / meta["id"]
    assert (preview / "index.html").read_bytes() == members[0].data
    assert (preview / "assets" / "app.js").read_bytes() == members[1].data


def test_store_app_bundle_rejects_untrusted_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_DIR", tmp_path)

    with pytest.raises(ValueError, match="unsafe"):
        files.store_app_bundle(
            "bad.zip",
            [SandboxFile("index.html", b"ok"), SandboxFile("../escape.txt", b"nope")],
        )

    assert not (tmp_path.parent / "escape.txt").exists()


def test_cleanup_removes_expired_app_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_DIR", tmp_path)
    meta = files.store_app_bundle(
        "tiny-app.zip",
        [SandboxFile("index.html", b"<html><body>Tiny app</body></html>")],
    )
    old = time.time() - 99_999
    os.utime(tmp_path / meta["id"], (old, old))

    files.cleanup(ttl_hours=1)

    assert not (tmp_path / meta["id"]).exists()
    assert not (tmp_path / f'{meta["id"]}.meta').exists()
    assert not (tmp_path / "apps" / meta["id"]).exists()


@pytest.mark.parametrize(
    "unsafe_name",
    ["../escape.txt", "/absolute.txt", "C:/drive.txt", "CON.txt", "bad?.txt", "dir\\file.txt"],
)
def test_store_app_bundle_rejects_platform_unsafe_paths(tmp_path, monkeypatch, unsafe_name):
    monkeypatch.setattr(files, "_DIR", tmp_path)

    with pytest.raises(ValueError, match="unsafe"):
        files.store_app_bundle(
            "bad.zip",
            [SandboxFile("index.html", b"ok"), SandboxFile(unsafe_name, b"nope")],
        )


def test_store_filegen_output_emits_one_app_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_DIR", tmp_path)
    artifacts = files.store_filegen_output({
        "kind": "app",
        "bundle_name": "tiny.zip",
        "files": [
            SandboxFile("index.html", b"<html><body>Tiny app content</body></html>"),
            SandboxFile("app.js", b"document.body.dataset.ready = 'yes';"),
            SandboxFile("styles.css", b"body { color: navy; }"),
        ],
    })

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "file"
    assert artifacts[0]["artifact_type"] == "app_bundle"
    assert artifacts[0]["name"] == "tiny.zip"


def test_cleanup_uses_artifact_age_not_preview_directory_age(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_DIR", tmp_path)
    meta = files.store_app_bundle(
        "fresh.zip",
        [SandboxFile("index.html", b"<html><body>Fresh app</body></html>")],
    )
    old = time.time() - 99_999
    preview = tmp_path / "apps" / meta["id"]
    os.utime(preview, (old, old))

    files.cleanup(ttl_hours=1)

    assert files.load(meta["id"]) is not None
    assert preview.is_dir()


def test_store_app_bundle_rolls_back_if_final_publish_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_DIR", tmp_path)
    path_type = type(tmp_path)
    original_replace = path_type.replace

    def fail_meta_publish(self, target):
        if self.name.endswith(".meta.tmp"):
            raise OSError("injected publish failure")
        return original_replace(self, target)

    monkeypatch.setattr(path_type, "replace", fail_meta_publish)

    with pytest.raises(OSError, match="injected"):
        files.store_app_bundle(
            "broken.zip",
            [SandboxFile("index.html", b"<html><body>Broken app</body></html>")],
        )

    assert not list(tmp_path.glob("*.meta"))
    assert not [path for path in tmp_path.iterdir() if path.name != "apps"]
    assert not list((tmp_path / "apps").iterdir())
