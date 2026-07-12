"""Sandbox readiness and containment invariants."""
from types import SimpleNamespace

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
    assert command[1:4] == ["run", "--rm", "--name"]
    assert command[4] == f"orrery-sbx-{result.run_id}"
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "640m"
    assert command[command.index("--memory-swap") + 1] == "640m"
    assert command[command.index("--cpus") + 1] == "1.0"
    assert command[command.index("--pids-limit") + 1] == "256"
    assert "--read-only" in command
    assert command[command.index("--tmpfs") + 1] == "/tmp:size=256m,exec"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert command[command.index("--user") + 1] == "1000:1000"
    assert command[-3:] == [sandbox.IMAGE, "python", "main.py"]
    assert result.manifest["limits"] == {
        "timeout_seconds": 60,
        "memory": "640m",
        "cpus": "1.0",
        "pids": "256",
        "max_output_files": 12,
        "max_total_output_bytes": 30_000_000,
        "max_file_bytes": 25_000_000,
    }


def test_collect_outputs_returns_at_most_twelve_files(tmp_path):
    for index in range(15):
        (tmp_path / f"result-{index:02d}.txt").write_text(str(index), encoding="utf-8")

    outputs = sandbox._collect_outputs(tmp_path)

    assert len(outputs) == 12
    assert [item.name for item in outputs] == [f"result-{index:02d}.txt" for index in range(12)]
