from fastapi.testclient import TestClient

from backend.api import create_app
from backend.features import artifacts, chat, exports, filepreview, team
from backend.features import files as file_library


TOKEN = "preview-test-token"


def _client() -> TestClient:
    return TestClient(create_app(TOKEN))


def test_file_preview_status_is_authenticated_and_safe(monkeypatch):
    monkeypatch.setattr(filepreview, "_find_soffice", lambda: r"C:\Program Files\LibreOffice\soffice.exe")

    assert _client().get("/api/file-preview/status").status_code == 401
    response = _client().get(
        "/api/file-preview/status",
        headers={"X-Orrery-Token": TOKEN},
    )

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "engine": "libreoffice",
        "officePreview": "pdf",
        "pdfRendererAvailable": True,
        "canInstall": False,
        "message": "Faithful Office previews are available.",
    }
    assert "Program Files" not in response.text


def test_file_preview_install_is_authenticated_admin_only(monkeypatch):
    calls = []

    async def member():
        return False

    monkeypatch.setattr(team, "is_admin", member)
    monkeypatch.setattr(filepreview, "install_office_preview", lambda acknowledged: calls.append(acknowledged))

    assert _client().post("/api/file-preview/install", json={"acknowledged": True}).status_code == 401
    response = _client().post(
        "/api/file-preview/install",
        headers={"X-Orrery-Token": TOKEN},
        json={"acknowledged": True},
    )

    assert response.status_code == 403
    assert calls == []


def test_file_preview_install_returns_fresh_probe(monkeypatch):
    async def admin():
        return True

    installed = {
        "available": True,
        "engine": "libreoffice",
        "officePreview": "pdf",
        "canInstall": False,
        "message": "Faithful Office previews are available.",
    }
    monkeypatch.setattr(team, "is_admin", admin)
    monkeypatch.setattr(filepreview, "install_office_preview", lambda acknowledged: installed if acknowledged else None)

    response = _client().post(
        "/api/file-preview/install",
        headers={"X-Orrery-Token": TOKEN},
        json={"acknowledged": True},
    )

    assert response.status_code == 200
    assert response.json() == installed


def test_file_preview_install_requires_explicit_consent(monkeypatch):
    async def admin():
        return True

    monkeypatch.setattr(team, "is_admin", admin)
    monkeypatch.setattr(filepreview, "_find_soffice", lambda: None)

    response = _client().post(
        "/api/file-preview/install",
        headers={"X-Orrery-Token": TOKEN},
        json={"acknowledged": False},
    )

    assert response.status_code == 400
    assert "Confirm the LibreOffice installation" in response.json()["detail"]


def test_office_preview_route_passes_content_cache_and_describes_fallback(monkeypatch, tmp_path):
    cached_pdf = tmp_path / "file.digest.preview.pdf"
    seen = {}
    monkeypatch.setattr(
        file_library,
        "load",
        lambda _file_id: ({"name": "report.docx", "mime": "application/vnd.openxmlformats"}, b"docx"),
    )
    monkeypatch.setattr(
        file_library,
        "office_preview_cache_path",
        lambda file_id, data: cached_pdf,
    )

    def html_fallback(name, mime, data, *, cache_path=None):
        seen["input"] = (name, mime, data, cache_path)
        return b"<html>fallback</html>", "text/html; charset=utf-8"

    monkeypatch.setattr(filepreview, "to_preview", html_fallback)

    response = _client().get(
        f"/api/files/{'a' * 32}/preview",
        headers={"X-Orrery-Token": TOKEN},
    )

    assert response.status_code == 200
    assert seen["input"][-1] == cached_pdf
    assert response.json()["renderer"] == "html-fallback"
    assert response.json()["hint"] == (
        "LibreOffice is unavailable or conversion failed; showing the HTML fallback."
    )


def test_office_pdf_page_render_is_still_reported_as_faithful(monkeypatch, tmp_path):
    monkeypatch.setattr(
        file_library,
        "load",
        lambda _file_id: ({"name": "report.docx", "mime": "application/vnd.openxmlformats"}, b"docx"),
    )
    monkeypatch.setattr(
        file_library,
        "office_preview_cache_path",
        lambda _file_id, _data: tmp_path / "report.preview.pdf",
    )
    rendered_pages = b"<html>" + (b"x" * 2048) + b'<main data-renderer="qt-pdf">pages</main></html>'
    monkeypatch.setattr(
        filepreview,
        "to_preview",
        lambda *_args, **_kwargs: (rendered_pages, "text/html; charset=utf-8"),
    )

    response = _client().get(
        f"/api/files/{'b' * 32}/preview",
        headers={"X-Orrery-Token": TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["renderer"] == "libreoffice"
    assert response.json()["hint"] is None


def test_partial_office_pdf_page_render_is_reported_truthfully(monkeypatch, tmp_path):
    monkeypatch.setattr(
        file_library,
        "load",
        lambda _file_id: ({"name": "report.docx", "mime": "application/vnd.openxmlformats"}, b"docx"),
    )
    monkeypatch.setattr(
        file_library,
        "office_preview_cache_path",
        lambda _file_id, _data: tmp_path / "report.preview.pdf",
    )
    partial = b'<main data-renderer="qt-pdf" data-preview-complete="false">partial pages</main>'
    monkeypatch.setattr(
        filepreview,
        "to_preview",
        lambda *_args, **_kwargs: (partial, "text/html; charset=utf-8"),
    )

    response = _client().get(
        f"/api/files/{'c' * 32}/preview",
        headers={"X-Orrery-Token": TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["renderer"] == "libreoffice-partial"
    assert "partial" in response.json()["hint"].lower()


def test_reply_pdf_preview_registers_webview_safe_content(monkeypatch):
    async def allow_access(*_args):
        return True

    async def pdf_preview(*_args):
        return exports.ExportResult(b"%PDF-valid", "application/pdf", "resume.pdf")

    seen = {}

    def webview_preview(name, mime, data, **_kwargs):
        seen["source"] = (name, mime, data)
        return b'<html data-renderer="qt-pdf">pages</html>', "text/html; charset=utf-8"

    def register(content, media_type="text/html"):
        seen["artifact"] = (content, media_type)
        return "preview-id"

    monkeypatch.setattr(chat, "can_access_conversation", allow_access)
    monkeypatch.setattr(exports, "preview_message", pdf_preview)
    monkeypatch.setattr(filepreview, "to_preview", webview_preview)
    monkeypatch.setattr(artifacts, "register", register)

    response = _client().get(
        "/api/conversations/c1/messages/m1/preview/pdf",
        headers={"X-Orrery-Token": TOKEN},
    )

    assert response.status_code == 200
    assert seen["source"] == ("resume.pdf", "application/pdf", b"%PDF-valid")
    assert seen["artifact"][1] == "text/html; charset=utf-8"
    assert response.json() == {
        "url": "/artifacts/preview-id",
        "kind": "pdf",
        "mime": "text/html; charset=utf-8",
    }
