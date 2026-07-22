"""Sandbox readiness and containment invariants."""
from types import SimpleNamespace

import pytest

from backend.features import sandbox


def _reset():
    sandbox._ready_cache = None


def test_image_ready_caches_the_probe(monkeypatch):
    _reset()
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return True

    monkeypatch.setattr(sandbox, "_probe_image_ready", fake_probe)

    assert sandbox.image_ready() is True
    assert sandbox.image_ready() is True
    assert sandbox.image_ready() is True
    assert calls["n"] == 1  # probed once, then served from cache


def test_image_ready_refresh_forces_reprobe(monkeypatch):
    _reset()
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return True

    monkeypatch.setattr(sandbox, "_probe_image_ready", fake_probe)

    assert sandbox.image_ready() is True
    assert sandbox.image_ready(refresh=True) is True
    assert calls["n"] == 2  # refresh bypasses the cache


def test_image_ready_negative_result_is_cached_too(monkeypatch):
    _reset()
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return False

    monkeypatch.setattr(sandbox, "_probe_image_ready", fake_probe)

    assert sandbox.image_ready() is False
    assert sandbox.image_ready() is False
    assert calls["n"] == 1  # a missing image is also cached (re-checked sooner via a shorter TTL)


def test_probe_requires_the_current_sandbox_image_version(monkeypatch):
    monkeypatch.setattr(
        sandbox.proc,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"1\n", stderr=b""),
    )
    assert sandbox._probe_image_ready() is False

    monkeypatch.setattr(
        sandbox.proc,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=(sandbox.SANDBOX_VERSION + "\n").encode(), stderr=b""
        ),
    )
    assert sandbox._probe_image_ready() is True


def test_run_code_applies_the_locked_down_container_contract(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(sandbox.proc, "run", fake_run)

    result = sandbox.run_code("print('ok')")

    assert result.ok is True
    assert len(calls) == 1
    command, options = calls[0]
    assert options["timeout"] == 60
    assert command[1:6] == ["run", "--rm", "--pull", "never", "--name"]
    assert command[6] == f"orrery-sbx-{result.run_id}"
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "640m"
    assert command[command.index("--memory-swap") + 1] == "640m"
    assert command[command.index("--cpus") + 1] == "1.0"
    assert command[command.index("--pids-limit") + 1] == "256"
    assert command[command.index("--ulimit") + 1] == "nofile=256:256"
    assert "--read-only" in command
    assert command[command.index("--tmpfs") + 1] == "/tmp:rw,noexec,nosuid,nodev,size=256m"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert "seccomp=builtin" in command
    assert command[command.index("--user") + 1] == "1000:1000"
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert any("target=/runner,readonly" in mount for mount in mounts)
    assert any("target=/work/input,readonly" in mount for mount in mounts)
    assert any("target=/work/workspace" in mount and "readonly" not in mount for mount in mounts)
    assert any("target=/work/out" in mount and "readonly" not in mount for mount in mounts)
    assert not any("target=/work," in mount for mount in mounts)
    assert command[-3:] == [sandbox.IMAGE, "python", "/runner/main.py"]
    assert result.manifest["limits"] == {
        "timeout_seconds": 60,
        "memory": "640m",
        "cpus": "1.0",
        "pids": "256",
        "max_output_files": 12,
        "max_total_output_bytes": 30_000_000,
        "max_file_bytes": 25_000_000,
        "max_input_file_bytes": 50_000_000,
    }


def test_collect_outputs_rejects_more_than_twelve_files(tmp_path):
    for index in range(15):
        (tmp_path / f"result-{index:02d}.txt").write_text(str(index), encoding="utf-8")

    with pytest.raises(sandbox.SandboxError, match="too many"):
        sandbox._collect_outputs(tmp_path)


def test_collect_outputs_preserves_safe_relative_paths(tmp_path):
    first = tmp_path / "app" / "assets" / "logo.svg"
    second = tmp_path / "app" / "icons" / "logo.svg"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    outputs = sandbox._collect_outputs(tmp_path)

    assert [(item.name, item.data) for item in outputs] == [
        ("app/assets/logo.svg", b"first"),
        ("app/icons/logo.svg", b"second"),
    ]


def test_collect_outputs_rejects_symbolic_links(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("do not collect through a link", encoding="utf-8")
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symbolic links are unavailable on this platform")

    with pytest.raises(sandbox.SandboxError, match="symbolic link"):
        sandbox._collect_outputs(tmp_path)


def test_pdf_ocr_mounts_the_source_read_only(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        out_mount = next(value for index, value in enumerate(command) if command[index - 1] == "--mount" and "target=/work/out" in value)
        out_dir = out_mount.split("source=", 1)[1].split(",target=", 1)[0]
        from pathlib import Path
        Path(out_dir, "document.txt").write_text("read by OCR", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sandbox.proc, "run", fake_run)

    assert sandbox.extract_pdf_text(b"%PDF-test") == "read by OCR"
    command = calls[0]
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert any("target=/work/input,readonly" in mount for mount in mounts)
    assert command[-3:] == [sandbox.IMAGE, "python", "/runner/extract_pdf.py"]
