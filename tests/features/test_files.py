"""Generated-file storage + TTL cleanup (architecture plan #18)."""

import os
import time

from backend.features import files


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
