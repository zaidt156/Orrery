from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QT_PREVIEW_IMPORTS = ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtPdf")


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_requirements_install_qtpdf_runtime_on_windows_and_macos():
    requirements = _text("requirements.txt")

    assert 'PySide6>=6.10; sys_platform == "win32" or sys_platform == "darwin"' in requirements


def test_electron_backend_installers_bundle_qtpdf_without_excluding_pyside():
    for script in ("scripts/build-windows-installer.ps1", "scripts/build-macos-installer.sh"):
        content = _text(script)
        for module in QT_PREVIEW_IMPORTS:
            assert module in content, f"{script} must bundle {module}"
        assert "exclude-module PySide6" not in content
        assert '"--exclude-module" "PySide6"' not in content
        assert "QtPdf" in content and "preview renderer" in content


def test_portable_release_builds_bundle_and_assert_qtpdf():
    for script in ("scripts/build-windows-onedir.ps1", "scripts/build-macos-app.sh"):
        content = _text(script)
        for module in QT_PREVIEW_IMPORTS:
            assert module in content, f"{script} must bundle {module}"
        assert "QtPdf" in content and "preview renderer" in content


def test_packaging_probe_checks_the_pdf_preview_capability():
    app = _text("app.py")

    assert "pdf_renderer_available" in app
    assert "PDF preview renderer" in app
