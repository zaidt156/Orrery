from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QT_PREVIEW_IMPORTS = ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtPdf")
# The Electron-wrapped installer scripts went with the shell; these two build the portable
# no-install downloads and are the only packaging paths left.
RELEASE_BUILD_SCRIPTS = ("scripts/build-windows-onedir.ps1", "scripts/build-macos-app.sh")


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_requirements_install_qtpdf_runtime_on_every_platform():
    """PySide6 is here for QtPdf, not for a window.

    It used to carry a win32/darwin marker because only those platforms had a desktop shell. The
    workspace is served to the user's own browser now, so a marker would leave Linux users with no
    PDF previews for no reason.
    """
    lines = [line.strip() for line in _text("requirements.txt").splitlines()]

    assert "PySide6>=6.10" in lines


def test_portable_release_builds_bundle_and_assert_qtpdf():
    for script in RELEASE_BUILD_SCRIPTS:
        content = _text(script)
        for module in QT_PREVIEW_IMPORTS:
            assert module in content, f"{script} must bundle {module}"
        assert "QtPdf" in content and "preview renderer" in content


def test_release_builds_do_not_carry_the_dead_window_runtime():
    """pywebview and Qt WebEngine were the window; QtPdf is the preview renderer and stays.

    Re-adding either would ship a browser engine nobody looks at now that the workspace opens in
    the user's own browser - and pywebview is not installed any more, so it fails the build.
    """
    for script in RELEASE_BUILD_SCRIPTS:
        content = _text(script)

        assert "pywebview" not in content
        assert "collect-all webview" not in content
        assert "PySide6.QtWebEngineCore" in content


def test_packaging_probe_checks_the_pdf_preview_capability():
    app = _text("app.py")

    assert "pdf_renderer_available" in app
    assert "PDF preview renderer" in app
