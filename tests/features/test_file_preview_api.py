from fastapi.testclient import TestClient

from backend.api import create_app
from backend.features import filepreview
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
        "message": "Faithful Office previews are available.",
    }
    assert "Program Files" not in response.text


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
