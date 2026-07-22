from backend.features import rag


def test_chunk_text_splits_with_overlap():
    body = "".join(str(i % 10) for i in range(2000))
    chunks = rag.chunk_text(body, size=900, overlap=150)
    assert len(chunks) >= 2
    assert all(len(c) <= 900 for c in chunks)
    assert chunks[0][-150:] == chunks[1][:150]  # overlap carries context across chunks


def test_chunk_text_empty():
    assert rag.chunk_text("") == []
    assert rag.chunk_text("   ") == []


def test_extract_text_passthrough():
    assert rag._extract({"kind": "text", "content": "hello world"}) == "hello world"


def test_vec_literal():
    assert rag._vec([0.1, 0.25]) == "[0.1,0.25]"


def test_pdf_extracts_embedded_text(monkeypatch):
    import base64
    import io

    from reportlab.pdfgen import canvas
    from backend.features import sandbox

    monkeypatch.setattr(sandbox, "image_ready", lambda: False)

    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(72, 720, "Orrery searchable PDF")
    pdf.save()

    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    assert "Orrery searchable PDF" in rag._pdf_text(encoded)


def test_pdf_rejects_malformed_base64():
    import pytest

    with pytest.raises(rag.DocumentExtractionError, match="base64"):
        rag._pdf_text("data:application/pdf;base64,not-valid!!!")


def test_pdf_reports_scan_only_files_need_ocr(monkeypatch):
    import base64
    import io

    import pytest
    from reportlab.pdfgen import canvas

    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.showPage()
    pdf.save()
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")

    from backend.features import sandbox

    monkeypatch.setattr(sandbox, "image_ready", lambda: False)

    with pytest.raises(rag.DocumentExtractionError, match="enable local OCR"):
        rag._pdf_text(encoded)


def test_pdf_prefers_sandboxed_extraction(monkeypatch):
    import base64
    import io

    from reportlab.pdfgen import canvas

    from backend.features import sandbox

    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.showPage()
    pdf.save()
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")

    monkeypatch.setattr(sandbox, "image_ready", lambda: True)
    seen = []
    monkeypatch.setattr(
        sandbox,
        "extract_pdf_text",
        lambda raw: seen.append(raw) or "OCR recovered text",
    )

    assert rag._pdf_text(encoded) == "OCR recovered text"
    assert seen and seen[0].startswith(b"%PDF-")
