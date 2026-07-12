from pathlib import Path

from backend.features import filepreview
from backend.features import files as file_library


def test_office_preview_status_reports_pdf_when_libreoffice_is_available(monkeypatch):
    monkeypatch.setattr(filepreview, "_find_soffice", lambda: "/opt/libreoffice/soffice")

    assert filepreview.office_preview_status() == {
        "available": True,
        "engine": "libreoffice",
        "officePreview": "pdf",
        "message": "Faithful Office previews are available.",
    }


def test_office_preview_status_reports_html_fallback_when_unavailable(monkeypatch):
    monkeypatch.setattr(filepreview, "_find_soffice", lambda: None)

    assert filepreview.office_preview_status() == {
        "available": False,
        "engine": "libreoffice",
        "officePreview": "html",
        "message": "LibreOffice is not installed; Office files use the HTML fallback.",
    }


def test_office_pdf_reuses_cached_conversion(monkeypatch, tmp_path):
    cache_path = tmp_path / "artifact.digest.preview.pdf"
    calls = []

    monkeypatch.setattr(filepreview, "_find_soffice", lambda: "soffice")

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        source = Path(argv[-1])
        source.with_suffix(".pdf").write_bytes(b"%PDF-1.7 faithful")

    monkeypatch.setattr(filepreview.proc, "run", fake_run)

    assert filepreview._office_pdf("deck.pptx", b"pptx", cache_path=cache_path) == b"%PDF-1.7 faithful"
    assert cache_path.read_bytes() == b"%PDF-1.7 faithful"
    assert filepreview._office_pdf("deck.pptx", b"pptx", cache_path=cache_path) == b"%PDF-1.7 faithful"
    assert len(calls) == 1


def test_failed_office_conversion_does_not_poison_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "artifact.digest.preview.pdf"
    monkeypatch.setattr(filepreview, "_find_soffice", lambda: "soffice")

    def failed_run(*_args, **_kwargs):
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(filepreview.proc, "run", failed_run)

    assert filepreview._office_pdf("document.docx", b"docx", cache_path=cache_path) is None
    assert not cache_path.exists()


def test_oversized_office_pdf_is_returned_but_not_cached(monkeypatch, tmp_path):
    cache_path = tmp_path / "artifact.digest.preview.pdf"
    monkeypatch.setattr(filepreview, "_find_soffice", lambda: "soffice")
    monkeypatch.setattr(filepreview, "_MAX_CACHED_OFFICE_PDF_BYTES", 4)

    def fake_run(argv, **_kwargs):
        source = Path(argv[-1])
        source.with_suffix(".pdf").write_bytes(b"12345")

    monkeypatch.setattr(filepreview.proc, "run", fake_run)

    assert filepreview._office_pdf("deck.pptx", b"pptx", cache_path=cache_path) == b"12345"
    assert not cache_path.exists()


def test_preview_cache_path_is_content_addressed_and_removes_stale_variants(monkeypatch, tmp_path):
    file_id = "a" * 32
    monkeypatch.setattr(file_library, "_DIR", tmp_path)

    first = file_library.office_preview_cache_path(file_id, b"first version")
    first.write_bytes(b"old preview")
    second = file_library.office_preview_cache_path(file_id, b"second version")

    assert first != second
    assert not first.exists()
    assert second.parent == tmp_path
    assert second.name.startswith(f"{file_id}.")
    assert second.name.endswith(".preview.pdf")


def test_preview_cache_path_prunes_oldest_entries_to_a_fixed_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(file_library, "_DIR", tmp_path)
    monkeypatch.setattr(file_library, "_MAX_OFFICE_PREVIEW_CACHE_ITEMS", 2)
    old = tmp_path / f"{'1' * 32}.old.preview.pdf"
    newer = tmp_path / f"{'2' * 32}.new.preview.pdf"
    old.write_bytes(b"old")
    newer.write_bytes(b"newer")
    old.touch()
    newer.touch()
    old_mtime = old.stat().st_mtime - 10
    import os

    os.utime(old, (old_mtime, old_mtime))

    target = file_library.office_preview_cache_path("3" * 32, b"new")
    target.write_bytes(b"new")

    assert not old.exists()
    assert newer.exists()
    assert target.exists()
    assert len(list(tmp_path.glob("*.preview.pdf"))) == 2
