"""Render generated binary files into webview-safe inline HTML previews.

Browsers cannot display Office files directly, and packaged Qt WebEngine can show valid PDFs as a
blank frame. Office files therefore use local conversion or a basic HTML fallback, while Windows
PDFs use the bundled QtPdf renderer.
We read the real file (python-pptx / openpyxl / python-docx) and render it as HTML —
slide cards for decks, tables for spreadsheets, and a document view for Word.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import html
import io
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from backend.core import proc
from backend.features.office_render import (  # noqa: F401 - re-exported for callers/tests
    # shared with the container-side renderers; some names exist here only so existing
    # callers and tests keep reading them through `filepreview`.
    _MAX_OFFICE_COLUMNS,
    _MAX_OFFICE_ROWS,
    _MAX_PREVIEW_CHARS,
    _MAX_PREVIEW_OUTPUT_BYTES,
    _PreviewBudget,
    _docx_html,
    _finish_html,
    _notice_html,
    _pptx_html,
    _warning,
    _xlsx_html,
)

log = logging.getLogger("orrery.filepreview")

_MAX_CACHED_OFFICE_PDF_BYTES = 8_000_000
_MAX_PDF_PREVIEW_PAGES = 24
_MAX_PDF_PREVIEW_PNG_BYTES = 5_000_000
_MAX_PREVIEW_INPUT_BYTES = 7_000_000
_MAX_SOURCE_INPUT_BYTES = 1_000_000
_MAX_OFFICE_ARCHIVE_ENTRIES = 2_000
_MAX_OFFICE_UNCOMPRESSED_BYTES = 32_000_000
_MAX_OFFICE_MEMBER_BYTES = 8_000_000
_INSTALL_TIMEOUT_SECONDS = 900

_PDF_RENDER_WIDTHS = (1000, 850, 700, 560, 440, 320, 240)

LIBREOFFICE_WINGET_ID = "TheDocumentFoundation.LibreOffice"
LIBREOFFICE_BREW_CASK = "libreoffice"

_install_lock = threading.Lock()
_preview_slot = threading.BoundedSemaphore(1)
_preview_flights_lock = threading.Lock()
_preview_flights: dict[str, "_PreviewFlight"] = {}




def _find_soffice() -> str | None:
    found = proc.find_executable("soffice") or shutil.which("libreoffice")
    if found:
        return found
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def _installer_command() -> list[str] | None:
    """Return the platform's fixed LibreOffice install command, never user input."""
    system = platform.system()
    if system == "Windows":
        winget = shutil.which("winget")
        if not winget:
            return None
        return [
            winget,
            "install",
            "--id",
            LIBREOFFICE_WINGET_ID,
            "--exact",
            "--source",
            "winget",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
            "--silent",
        ]
    if system == "Darwin":
        brew = proc.find_executable("brew")
        if not brew:
            return None
        return [brew, "install", "--cask", LIBREOFFICE_BREW_CASK]
    return None


def office_preview_status() -> dict:
    """Return a safe live probe result; never expose the executable path."""
    office_available = _find_soffice() is not None
    renderer_available = pdf_renderer_available()
    if office_available and renderer_available:
        return {
            "available": True,
            "engine": "libreoffice",
            "officePreview": "pdf",
            "pdfRendererAvailable": True,
            "canInstall": False,
            "message": "Faithful Office previews are available.",
        }
    if office_available:
        return {
            "available": False,
            "engine": "libreoffice",
            "officePreview": "html",
            "pdfRendererAvailable": False,
            "canInstall": False,
            "message": "The PDF preview renderer is unavailable; Office files use the HTML fallback.",
        }
    return {
        "available": False,
        "engine": "libreoffice",
        "officePreview": "html",
        "pdfRendererAvailable": renderer_available,
        "canInstall": renderer_available and _installer_command() is not None,
        "message": "LibreOffice is not installed; Office files use the HTML fallback.",
    }


def install_office_preview(acknowledged: bool = False) -> dict:
    """Install LibreOffice from a fixed official package and return a fresh probe."""
    if not acknowledged:
        raise ValueError("Confirm the LibreOffice installation before continuing.")
    if not pdf_renderer_available():
        raise ValueError("The packaged PDF preview renderer is unavailable; reinstall or update Orrery.")
    if _find_soffice():
        return office_preview_status()
    command = _installer_command()
    if command is None:
        raise ValueError(
            "One-click LibreOffice installation requires WinGet on Windows or Homebrew on macOS."
        )
    if not _install_lock.acquire(blocking=False):
        raise ValueError("A LibreOffice installation is already running.")
    try:
        # Re-probe after acquiring the lock in case another request completed first.
        if _find_soffice():
            return office_preview_status()
        result = proc.run(
            command,
            cwd=tempfile.gettempdir(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=_INSTALL_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("LibreOffice installation failed. Check the package manager and retry.")
        status = office_preview_status()
        if not status["available"]:
            raise ValueError("LibreOffice installation finished, but the preview engine was not detected.")
        return status
    except subprocess.TimeoutExpired:
        raise ValueError("LibreOffice installation timed out.") from None
    except OSError:
        raise ValueError("LibreOffice installation could not be started.") from None
    finally:
        _install_lock.release()


def is_office_file(name: str) -> bool:
    return Path(name).suffix.lower() in {".pptx", ".docx", ".xlsx", ".xlsm"}


@dataclass
class _PreviewFlight:
    event: threading.Event
    result: object = None
    error: Exception | None = None


def _run_preview_job(key: str, job):
    """Serialize expensive preview jobs and share one result for identical concurrent work."""
    with _preview_flights_lock:
        flight = _preview_flights.get(key)
        leader = flight is None
        if leader:
            flight = _PreviewFlight(threading.Event())
            _preview_flights[key] = flight
    assert flight is not None
    if leader:
        try:
            with _preview_slot:
                flight.result = job()
        except Exception as exc:
            flight.error = exc
        finally:
            with _preview_flights_lock:
                flight.event.set()
                _preview_flights.pop(key, None)
    else:
        flight.event.wait()
    if flight.error is not None:
        raise flight.error
    return flight.result


def _converted_pdf_limit() -> int:
    return min(_MAX_CACHED_OFFICE_PDF_BYTES, _MAX_PREVIEW_INPUT_BYTES)


def _valid_pdf_bytes(data: bytes) -> bool:
    """Validate a converted PDF before it is rendered, returned, or persisted."""
    if not data or len(data) > _converted_pdf_limit():
        return False
    stripped = data.lstrip()
    if not stripped.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
        return False
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=False)
        return not reader.is_encrypted and len(reader.pages) > 0
    except Exception:  # noqa: BLE001 - malformed or unsupported PDFs are rejected
        return False


def _read_valid_pdf(path: Path) -> bytes | None:
    """Stat before reading so oversized converter/cache output never enters memory."""
    try:
        size = path.stat().st_size
        if size <= 0 or size > _converted_pdf_limit():
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) != size or not _valid_pdf_bytes(data):
        return None
    return data


def _office_pdf_job(name: str, data: bytes, *, cache_path: Path | None = None) -> bytes | None:
    if cache_path is not None and cache_path.is_file():
        cached = _read_valid_pdf(cache_path)
        if cached is not None:
            return cached
        try:
            cache_path.unlink(missing_ok=True)
        except OSError:
            pass
    soffice = _find_soffice()
    if not soffice:
        return None
    suffix = Path(name).suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="orrery-preview-") as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / f"input{suffix}"
        profile = tmp_path / "libreoffice-profile"
        profile.mkdir()
        source.write_bytes(data)
        try:
            proc.run(
                [
                    soffice,
                    "--headless",
                    "--nologo",
                    "--nofirststartwizard",
                    f"-env:UserInstallation={profile.resolve().as_uri()}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(tmp_path),
                    str(source),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=45,
            )
        except Exception:  # noqa: BLE001
            return None
        pdf = source.with_suffix(".pdf")
        if not pdf.is_file():
            return None
        converted = _read_valid_pdf(pdf)
        if converted is None:
            return None
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_name(f"{cache_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(converted)
                temporary.replace(cache_path)
            except OSError:
                pass
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return converted


def _office_pdf(name: str, data: bytes, *, cache_path: Path | None = None) -> bytes | None:
    source_key = str(cache_path.resolve()) if cache_path is not None else hashlib.sha256(data).hexdigest()
    key = f"office:{Path(name).suffix.lower()}:{source_key}"
    return _run_preview_job(
        key,
        lambda: _office_pdf_job(name, data, cache_path=cache_path),
    )












def _inert_fallback(name: str, data: bytes, message: str, *, truncated: bool = False) -> bytes:
    input_truncated = len(data) > _MAX_SOURCE_INPUT_BYTES
    sample = data[:_MAX_SOURCE_INPUT_BYTES]
    text = sample.decode("utf-8", errors="replace")
    char_truncated = len(text) > _MAX_PREVIEW_CHARS
    text = text[:_MAX_PREVIEW_CHARS]
    escaped = html.escape(text)
    body = (
        f'<main data-renderer="inert-fallback">{_warning(message)}'
        f'<div class="source"><pre>{escaped}</pre></div></main>'
    )
    return _finish_html(name, body, truncated=truncated or input_truncated or char_truncated)


def _office_archive_issue(data: bytes, name: str = "") -> str | None:
    if len(data) > _MAX_PREVIEW_INPUT_BYTES:
        return "Office file input exceeded the safe preview limit."
    if Path(name).suffix.lower() == ".xlsm":
        return "Macro-enabled Office files are not sent to the host converter."
    if data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return "Encrypted Office packages are not sent to the host converter."
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            entries = package.infolist()
            if len(entries) > _MAX_OFFICE_ARCHIVE_ENTRIES:
                return "Office archive contained too many entries for a safe preview."
            total = 0
            normalized_names: set[str] = set()
            for entry in entries:
                normalized = entry.filename.replace("\\", "/").lstrip("/").lower()
                normalized_names.add(normalized)
                if entry.flag_bits & 0x1:
                    return "Encrypted Office packages are not sent to the host converter."
                if entry.file_size > _MAX_OFFICE_MEMBER_BYTES:
                    return "Office archive contained an oversized compressed member."
                total += entry.file_size
                if total > _MAX_OFFICE_UNCOMPRESSED_BYTES:
                    return "Office archive expanded beyond the safe preview limit."

            if {"encryptioninfo", "encryptedpackage"} & normalized_names:
                return "Encrypted Office packages are not sent to the host converter."
            if any(
                member.endswith("vbaproject.bin")
                or "/vba/" in f"/{member}/"
                or "macrosheet" in member
                for member in normalized_names
            ):
                return "Office packages containing macros are not sent to the host converter."

            content_types = next(
                (entry for entry in entries if entry.filename.replace("\\", "/").lstrip("/").lower() == "[content_types].xml"),
                None,
            )
            if content_types is not None:
                content = package.read(content_types).lower()
                if b"macroenabled" in content or b"vba" in content:
                    return "Macro-enabled Office packages are not sent to the host converter."

            from defusedxml import ElementTree as SafeElementTree

            for entry in entries:
                if not entry.filename.lower().endswith(".rels"):
                    continue
                try:
                    relationships = SafeElementTree.fromstring(package.read(entry))
                except Exception:  # noqa: BLE001 - malformed relationship XML fails closed
                    return "Office relationship metadata could not be safely parsed."
                for relationship in relationships.iter():
                    target_mode = next(
                        (
                            value
                            for key, value in relationship.attrib.items()
                            if key.rsplit("}", 1)[-1].lower() == "targetmode"
                        ),
                        "",
                    )
                    if target_mode.lower() == "external":
                        return "Office packages with an external relationship are not sent to the host converter."
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError):
        return "Preview unavailable because the Office file could not be parsed."
    return None


def _bounded_pdf_page_png(render_at_width, *, remaining: int) -> bytes | None:
    """Render a page at progressively lower resolutions until it fits the remaining budget."""
    if remaining <= 0:
        return None
    for width in _PDF_RENDER_WIDTHS:
        png = render_at_width(width)
        if png and len(png) <= remaining:
            return png
    return None


@dataclass(frozen=True)
class _PdfRender:
    pages: tuple[bytes, ...]
    total_pages: int
    complete: bool
    reason: str | None = None


def pdf_renderer_available() -> bool:
    """Whether PDF pages can be rasterized at all - in the bounded worker, or failing that, here.

    Asked by the Office-preview status route. Since the worker became the preferred renderer, a
    machine with Docker but no packaged Qt is fully capable, and reporting otherwise would send a
    user to reinstall Orrery to fix something that already works.
    """
    from backend.features import sandbox

    return bool(sandbox.image_ready()) or _host_pdf_renderer_available()


def _host_pdf_renderer_available() -> bool:
    """Return whether the local QtPdf renderer can be imported in this runtime."""
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize  # noqa: F401
        from PySide6.QtGui import QImage  # noqa: F401
        from PySide6.QtPdf import QPdfDocument  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def _render_pdf_pngs_uncached(data: bytes) -> _PdfRender | None:
    """Rasterize an untrusted PDF's pages, preferring the offline bounded worker.

    A PDF from a chat attachment or a document collection is attacker-controlled input, and PDF
    parsers are a classic way in. Rendering it in this process gave that parser the application's
    own privileges: the keychain, the database, the user's files. The sandbox container already
    carries pypdfium2 for OCR, so the parse belongs there - no network, read-only root, non-root
    user, dropped capabilities, and hard memory/PID/time caps.

    A sandbox FAILURE is not a reason to parse on the host. That would make the boundary optional
    for exactly the documents most likely to break a parser, so a failed render means no preview.
    The host renderer survives only for a machine with no sandbox image at all; that fallback is
    explicit and temporary (PLAN.md Workstream 2).
    """
    from backend.features import sandbox

    if sandbox.image_ready():
        try:
            pages, total_pages, reason = sandbox.render_pdf_pages(
                data,
                max_pages=_MAX_PDF_PREVIEW_PAGES,
                widths=_PDF_RENDER_WIDTHS,
                max_total_bytes=_MAX_PDF_PREVIEW_PNG_BYTES,
            )
        except sandbox.SandboxError:
            log.warning("PDF preview refused: the bounded worker could not render the document")
            return None
        if not pages:
            # A budget that stopped the render is still worth reporting; nothing at all is not.
            if reason in {"byte limit", "page limit"}:
                return _PdfRender((), total_pages, False, reason)
            return None
        complete = len(pages) == total_pages and reason is None
        return _PdfRender(tuple(pages), total_pages, complete, reason)
    return _render_pdf_pngs_with_host(data)


def _render_pdf_pngs_with_host(data: bytes) -> _PdfRender | None:
    """Rasterize PDF pages with QtPdf, in this process, when no sandbox image exists.

    The packaged Qt WebEngine PDF viewer can show a blank document even when the PDF is valid.
    QtPdf is already part of Orrery's Windows desktop runtime, so rendering pages here avoids that
    viewer dependency without adding a network service. When QtPdf is unavailable or cannot fit a
    page inside the preview budget, the caller receives bounded explanatory HTML instead of a raw
    PDF that the packaged webview cannot display.
    """
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
        from PySide6.QtPdf import QPdfDocument
    except (ImportError, OSError):
        return None

    source_data = QByteArray(data)
    source = QBuffer(source_data)
    if not source.open(QIODevice.OpenModeFlag.ReadOnly):
        return None
    document = QPdfDocument()
    try:
        load_error = document.load(source)
        if load_error not in (None, QPdfDocument.Error.None_) or document.pageCount() < 1:
            return None
        total_pages = document.pageCount()
        pages: list[bytes] = []
        total = 0
        reason = "page limit" if total_pages > _MAX_PDF_PREVIEW_PAGES else None
        for page_number in range(min(total_pages, _MAX_PDF_PREVIEW_PAGES)):
            points = document.pagePointSize(page_number)
            if points.width() <= 0 or points.height() <= 0:
                reason = "page rendering failed"
                break

            def render_at_width(width: int) -> bytes | None:
                height = max(1, round(width * points.height() / points.width()))
                if height > 1800:
                    width = max(1, round(width * 1800 / height))
                    height = 1800
                image = document.render(page_number, QSize(width, height))
                if image.isNull():
                    return None
                output = QBuffer()
                if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                    return None
                try:
                    if not image.save(output, "PNG"):
                        return None
                    return bytes(output.data())
                finally:
                    output.close()

            png = _bounded_pdf_page_png(
                render_at_width,
                remaining=_MAX_PDF_PREVIEW_PNG_BYTES - total,
            )
            if png is None:
                reason = "byte limit"
                break
            pages.append(png)
            total += len(png)
        if not pages:
            if reason in {"byte limit", "page limit"}:
                return _PdfRender((), total_pages, False, reason)
            return None
        complete = len(pages) == total_pages and reason is None
        return _PdfRender(tuple(pages), total_pages, complete, reason)
    except Exception:  # noqa: BLE001 - malformed PDFs fall back to the native response
        return None
    finally:
        document.close()
        source.close()


def _render_pdf_pngs(data: bytes) -> _PdfRender | None:
    key = f"pdf:{hashlib.sha256(data).hexdigest()}"
    return _run_preview_job(key, lambda: _render_pdf_pngs_uncached(data))


def _rendered_pdf_html(name: str, data: bytes) -> bytes | None:
    rendered = _render_pdf_pngs(data)
    if rendered is None:
        return None
    cards = []
    for page_number, png in enumerate(rendered.pages, start=1):
        encoded = base64.b64encode(png).decode("ascii")
        cards.append(
            f'<section class="pdf-page" aria-label="Page {page_number}">'
            f'<img src="data:image/png;base64,{encoded}" alt="PDF page {page_number}">'
            f'<div class="pdf-page-label">Page {page_number}</div></section>'
        )
    count = len(cards)
    complete = "true" if rendered.complete else "false"
    truncation_reason = ""
    if not rendered.complete and rendered.reason:
        reason = re.sub(r"[^a-z0-9]+", "-", rendered.reason.lower()).strip("-")
        truncation_reason = f' data-preview-truncation-reason="{html.escape(reason)}"'
    body = (
        f'<main class="pdf-doc" data-renderer="qt-pdf" data-preview-complete="{complete}"{truncation_reason}>'
        f'<div class="meta">PDF preview · {count} of {rendered.total_pages} rendered page(s) '
        f'· {html.escape(name)}</div>{"".join(cards)}</main>'
    )
    return _finish_html(name, body, truncated=not rendered.complete)


def _pdf_html(name: str, data: bytes) -> bytes:
    rendered = _rendered_pdf_html(name, data)
    if rendered is None:
        return _notice_html(
            name,
            "PDF preview is unavailable in the embedded viewer. Download the original file to open it.",
        )
    return rendered




































def _csv_html(name: str, data: bytes) -> bytes:
    import csv as _csv

    input_truncated = len(data) > _MAX_SOURCE_INPUT_BYTES
    text = data[:_MAX_SOURCE_INPUT_BYTES].decode("utf-8-sig", errors="replace")
    delimiter = "\t" if Path(name).suffix.lower() == ".tsv" else ","
    try:
        sample = text[:4096]
        if sample.strip():
            delimiter = _csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except _csv.Error:
        pass
    budget = _PreviewBudget()
    rows_html = []
    for row_index, row in enumerate(_csv.reader(io.StringIO(text), delimiter=delimiter)):
        if row_index >= _MAX_OFFICE_ROWS or not budget.node():
            budget.truncated = True
            break
        if len(row) > _MAX_OFFICE_COLUMNS:
            budget.truncated = True
        tag = "th" if row_index == 0 else "td"
        cells = []
        for value in row[:_MAX_OFFICE_COLUMNS]:
            if not budget.cell():
                break
            cells.append(f"<{tag}>{html.escape(budget.text(value))}</{tag}>")
        if cells:
            rows_html.append(f"<tr>{''.join(cells)}</tr>")
    if not rows_html:
        return _source_html(name, data)
    body = (
        f'<main data-renderer="csv-table"><div class="meta">Table preview · {html.escape(name)}</div>'
        f'<div class="sheet"><table>{"".join(rows_html)}</table></div></main>'
    )
    return _finish_html(name, body, truncated=budget.truncated or input_truncated)


def _markdown_html(name: str, data: bytes) -> bytes:
    from markdown_it import MarkdownIt

    input_truncated = len(data) > _MAX_SOURCE_INPUT_BYTES
    text = data[:_MAX_SOURCE_INPUT_BYTES].decode("utf-8", errors="replace")
    char_truncated = len(text) > _MAX_PREVIEW_CHARS
    text = text[:_MAX_PREVIEW_CHARS]
    # html=False escapes any raw HTML in the document; the image rule is disabled so a preview
    # never fetches a remote resource (the markdown source of the image shows instead).
    parser = MarkdownIt("commonmark", {"html": False, "linkify": False})
    parser.enable(["table", "strikethrough"])
    parser.disable("image")
    rendered = parser.render(text)
    body = (
        f'<main data-renderer="markdown"><div class="meta">Markdown preview · {html.escape(name)}</div>'
        f'<div class="doc">{rendered}</div></main>'
    )
    return _finish_html(name, body, truncated=input_truncated or char_truncated)


def _source_html(name: str, data: bytes) -> bytes:
    input_truncated = len(data) > _MAX_SOURCE_INPUT_BYTES
    text = data[:_MAX_SOURCE_INPUT_BYTES].decode("utf-8", errors="replace")
    char_truncated = len(text) > _MAX_PREVIEW_CHARS
    text = text[:_MAX_PREVIEW_CHARS]
    body = (
        f'<main data-renderer="inert-source"><div class="meta">Source preview · {html.escape(name)}</div>'
        f'<div class="source"><pre>{html.escape(text)}</pre></div></main>'
    )
    return _finish_html(name, body, truncated=input_truncated or char_truncated)


def to_preview(
    name: str,
    mime: str,
    data: bytes,
    *,
    cache_path: Path | None = None,
) -> tuple[bytes, str]:
    """Return webview-safe preview content and its media type."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if len(data) > _MAX_PREVIEW_INPUT_BYTES:
        return (
            _inert_fallback(
                name,
                data,
                "Preview unavailable because the file exceeded the safe input limit.",
                truncated=True,
            ),
            "text/html; charset=utf-8",
        )
    if ext == "pdf":
        return _pdf_html(name, data), "text/html; charset=utf-8"
    if ext in ("pptx", "docx", "xlsx", "xlsm"):
        archive_issue = _office_archive_issue(data, name)
        if archive_issue:
            return (
                _inert_fallback(name, data, archive_issue, truncated=True),
                "text/html; charset=utf-8",
            )
        pdf = _office_pdf(name, data, cache_path=cache_path)
        if pdf:
            rendered_pdf = _rendered_pdf_html(name, pdf)
            if rendered_pdf is not None:
                return rendered_pdf, "text/html; charset=utf-8"
    try:
        if ext == "pptx":
            return _pptx_html(data), "text/html; charset=utf-8"
        if ext in ("xlsx", "xlsm"):
            return _xlsx_html(data), "text/html; charset=utf-8"
        if ext == "docx":
            return _docx_html(data), "text/html; charset=utf-8"
        if ext in ("csv", "tsv"):
            return _csv_html(name, data), "text/html; charset=utf-8"
        if ext in ("md", "markdown"):
            return _markdown_html(name, data), "text/html; charset=utf-8"
        if ext in ("tex", "bib", "sty", "cls"):
            return _source_html(name, data), "text/html; charset=utf-8"
    except Exception:  # noqa: BLE001 — on any parse failure, fall back to the raw bytes
        return (
            _inert_fallback(name, data, "Preview unavailable because the file could not be parsed."),
            "text/html; charset=utf-8",
        )

    source_extensions = {
        "bib", "cls", "css", "html", "htm", "js", "json",
        "py", "svg", "sty", "tex", "txt", "xhtml", "xml", "yaml", "yml",
    }
    normalized_mime = mime.lower().split(";", 1)[0].strip()
    if ext in source_extensions or normalized_mime in {
        "application/javascript",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/html",
    }:
        return _source_html(name, data), "text/html; charset=utf-8"
    if normalized_mime in {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}:
        return data, normalized_mime
    if normalized_mime.startswith("audio/") or normalized_mime.startswith("video/"):
        return data, normalized_mime
    return (
        _inert_fallback(name, data, "Preview unavailable for this file type."),
        "text/html; charset=utf-8",
    )
