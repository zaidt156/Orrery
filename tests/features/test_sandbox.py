"""Sandbox readiness and containment invariants."""
from pathlib import Path
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


def _mount_source(command: list[str], target: str) -> Path:
    mount = next(
        value
        for index, value in enumerate(command)
        if command[index - 1] == "--mount" and target in value
    )
    return Path(mount.split("source=", 1)[1].split(",target=", 1)[0])


def test_office_extraction_runs_in_the_container_with_a_read_only_source(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["inputs"] = sorted(p.name for p in _mount_source(command, "target=/work/input").iterdir())
        (_mount_source(command, "target=/work/out") / "document.txt").write_text(
            "worker text", encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sandbox.proc, "run", fake_run)

    assert sandbox.extract_office_text("Quarterly Report.DOCX", b"PK\x03\x04fake") == "worker text"

    command = seen["command"]
    input_names = seen["inputs"]
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert any("target=/work/input,readonly" in mount for mount in mounts)
    assert command[command.index("--network") + 1] == "none"
    assert command[-3:] == [sandbox.IMAGE, "python", "/runner/extract_office.py"]
    # The container sees a fixed name derived from the validated suffix, never the uploaded filename.
    assert input_names == ["document.docx"]


@pytest.mark.parametrize("name", ["report.pdf", "archive.zip", "notes", "notes.docx.exe", ".docx"])
def test_office_extraction_refuses_types_the_worker_does_not_handle(monkeypatch, name):
    monkeypatch.setattr(
        sandbox.proc, "run", lambda *a, **k: pytest.fail("the container must not start")
    )

    with pytest.raises(sandbox.SandboxError, match="Unsupported Office document type"):
        sandbox.extract_office_text(name, b"PK\x03\x04fake")


def test_office_extraction_reports_a_failed_run_rather_than_returning_empty_text(monkeypatch):
    monkeypatch.setattr(
        sandbox.proc,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom"),
    )

    with pytest.raises(sandbox.SandboxError):
        sandbox.extract_office_text("notes.xlsx", b"PK\x03\x04fake")


# --- rendering an untrusted PDF inside the container ---------------------------------------------
#
# PDF page rasterization ran in-process with QtPdf: Orrery parsed an untrusted, attacker-supplied
# document with the application's own privileges. The container already carries pypdfium2 for OCR,
# so the parse belongs there. These cover the wiring; a real container run is a CI fixture.

def _renderer_result(pages: dict[str, bytes], manifest: dict) -> sandbox.SandboxResult:
    import json as _json

    files = [sandbox.SandboxFile(name=name, data=data) for name, data in pages.items()]
    files.append(sandbox.SandboxFile(
        name="manifest.json", data=_json.dumps(manifest).encode("utf-8")))
    return sandbox.SandboxResult(ok=True, stdout="", stderr="", exit_code=0, timed_out=False,
                                 files=files)


def test_render_pdf_pages_returns_pages_in_order(monkeypatch):
    """Page order is the whole point of a paginated preview, and /work/out is not ordered."""
    captured = {}

    def fake_run_entry(content, name, argv, *, input_files=None):
        captured["input_files"] = input_files
        captured["argv"] = argv
        return _renderer_result(
            # deliberately out of order: the caller must sort, not trust the listing
            {"page-002.png": b"second", "page-001.png": b"first", "page-003.png": b"third"},
            {"total_pages": 3, "reason": None, "written": 3},
        )

    monkeypatch.setattr(sandbox, "_run_entry", fake_run_entry)

    pages, total, reason = sandbox.render_pdf_pages(b"%PDF-1.4 fake", max_pages=24)

    assert pages == [b"first", b"second", b"third"]
    assert total == 3
    assert reason is None
    assert "document.pdf" in captured["input_files"], "the PDF must go in as an input file"
    assert captured["input_files"]["document.pdf"] == b"%PDF-1.4 fake"


def test_render_pdf_pages_passes_its_limits_into_the_container(monkeypatch):
    """The budget has to be enforced where the rendering happens, not after it comes back."""
    import json as _json

    captured = {}

    def fake_run_entry(content, name, argv, *, input_files=None):
        captured["config"] = _json.loads(input_files["render.json"].decode("utf-8"))
        return _renderer_result({}, {"total_pages": 0, "reason": None, "written": 0})

    monkeypatch.setattr(sandbox, "_run_entry", fake_run_entry)

    sandbox.render_pdf_pages(b"%PDF", max_pages=7, widths=(900, 400), max_total_bytes=1234,
                             max_height=1500)

    assert captured["config"]["max_pages"] == 7
    assert captured["config"]["widths"] == [900, 400]
    assert captured["config"]["max_total_bytes"] == 1234
    assert captured["config"]["max_height"] == 1500


def test_render_pdf_pages_reports_why_it_stopped_early(monkeypatch):
    """A truncated preview must say so; silently short output reads as a complete document."""
    def fake_run_entry(content, name, argv, *, input_files=None):
        return _renderer_result({"page-001.png": b"only"},
                                {"total_pages": 40, "reason": "page limit", "written": 1})

    monkeypatch.setattr(sandbox, "_run_entry", fake_run_entry)

    pages, total, reason = sandbox.render_pdf_pages(b"%PDF", max_pages=1)

    assert pages == [b"only"]
    assert total == 40
    assert reason == "page limit"


def test_render_pdf_pages_raises_when_the_container_fails(monkeypatch):
    """A failed sandbox must not look like a PDF with no pages."""
    def fake_run_entry(content, name, argv, *, input_files=None):
        return sandbox.SandboxResult(ok=False, stdout="", stderr="pdfium exploded",
                                     exit_code=1, timed_out=False, files=[])

    monkeypatch.setattr(sandbox, "_run_entry", fake_run_entry)

    with pytest.raises(sandbox.SandboxError):
        sandbox.render_pdf_pages(b"%PDF", max_pages=4)


def test_render_pdf_pages_raises_when_the_manifest_is_missing(monkeypatch):
    """Without the manifest we cannot tell a truncated render from a complete one."""
    def fake_run_entry(content, name, argv, *, input_files=None):
        return sandbox.SandboxResult(ok=True, stdout="", stderr="", exit_code=0, timed_out=False,
                                     files=[sandbox.SandboxFile(name="page-001.png", data=b"x")])

    monkeypatch.setattr(sandbox, "_run_entry", fake_run_entry)

    with pytest.raises(sandbox.SandboxError):
        sandbox.render_pdf_pages(b"%PDF", max_pages=4)
