"""Render generated binary files into inline HTML previews.

Browsers can't display .pptx/.xlsx/.docx in an iframe, so the preview comes back blank.
We read the real file (python-pptx / openpyxl / python-docx) and render it as HTML —
slide cards for decks, tables for spreadsheets, a document for Word. PDFs and images are
returned untouched (the webview renders those natively).
"""

from __future__ import annotations

import html
import io
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from backend.core import proc

_MAX_CACHED_OFFICE_PDF_BYTES = 8_000_000

_PAGE_CSS = """
*{box-sizing:border-box} body{background:#1b2030;margin:0;padding:24px 20px 56px;
  font-family:Arial,Helvetica,sans-serif;color:#172033}
.meta{color:#9aa6bd;font-size:12px;text-align:center;margin-bottom:16px}
.slide{position:relative;width:100%;max-width:880px;aspect-ratio:16/9;margin:0 auto 20px;background:#fff;
  border-radius:12px;box-shadow:0 10px 34px rgba(0,0,0,.40);padding:44px 52px;overflow:hidden}
.slide h2{font-size:28px;line-height:1.2;margin:0 0 18px;color:#0b1020}
.slide ul{margin:0;padding-left:24px} .slide li{font-size:20px;line-height:1.5;margin:9px 0}
.slide .snum{position:absolute;right:16px;bottom:12px;font-size:12px;color:#9aa6bd}
.sheet{max-width:1040px;margin:0 auto 22px} .sheet h3{color:#cdd8f0;font-size:15px;margin:0 0 8px}
table{border-collapse:collapse;width:100%;background:#fff;border-radius:8px;overflow:hidden}
th,td{border:1px solid #c6cfdd;padding:7px 9px;text-align:left;font-size:13px;vertical-align:top}
th{background:#26314f;color:#fff}
.doc{max-width:820px;margin:0 auto;background:#fff;border-radius:10px;padding:40px 48px}
.doc h1{font-size:26px;color:#0b1020;margin:0 0 14px} .doc h2{font-size:20px;color:#0b1020;margin:18px 0 8px}
.doc p{font-size:15px;line-height:1.6;margin:0 0 12px} .doc li{font-size:15px;line-height:1.6;margin:4px 0}
.source{max-width:1040px;margin:0 auto;background:#fff;border-radius:10px;padding:28px 32px}
.source pre{white-space:pre-wrap;word-break:break-word;margin:0;font:13px/1.55 Consolas,Menlo,monospace;color:#172033}
"""


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


def office_preview_status() -> dict:
    """Return a safe live probe result; never expose the executable path."""
    if _find_soffice():
        return {
            "available": True,
            "engine": "libreoffice",
            "officePreview": "pdf",
            "message": "Faithful Office previews are available.",
        }
    return {
        "available": False,
        "engine": "libreoffice",
        "officePreview": "html",
        "message": "LibreOffice is not installed; Office files use the HTML fallback.",
    }


def is_office_file(name: str) -> bool:
    return Path(name).suffix.lower() in {".pptx", ".docx", ".xlsx", ".xlsm"}


def _office_pdf(name: str, data: bytes, *, cache_path: Path | None = None) -> bytes | None:
    if cache_path is not None and cache_path.is_file():
        try:
            return cache_path.read_bytes()
        except OSError:
            pass
    soffice = _find_soffice()
    if not soffice:
        return None
    suffix = Path(name).suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="orrery-preview-") as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / f"input{suffix}"
        source.write_bytes(data)
        try:
            proc.run(
                [
                    soffice,
                    "--headless",
                    "--nologo",
                    "--nofirststartwizard",
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
        converted = pdf.read_bytes()
        if cache_path is not None and len(converted) <= _MAX_CACHED_OFFICE_PDF_BYTES:
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


def _page(title: str, body: str) -> bytes:
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)} preview</title><style>{_PAGE_CSS}</style></head>"
        f"<body>{body}</body></html>"
    ).encode("utf-8")


def _pptx_html(data: bytes) -> bytes:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    cards = []
    for index, slide in enumerate(prs.slides, start=1):
        title = ""
        title_shape = None
        try:
            if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
                title = slide.shapes.title.text.strip()
                title_shape = slide.shapes.title
        except (AttributeError, ValueError):
            pass
        bullets: list[str] = []
        for shape in slide.shapes:
            if shape is title_shape or not getattr(shape, "has_text_frame", False):
                continue
            for paragraph in shape.text_frame.paragraphs:
                text = paragraph.text.strip()
                if text:
                    bullets.append(text)
        items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets[:14])
        body = f"<ul>{items}</ul>" if items else ""
        cards.append(
            f'<div class="slide"><div class="snum">{index}</div>'
            f'<h2>{html.escape(title or f"Slide {index}")}</h2>{body}</div>'
        )
    return _page("PowerPoint", f'<div class="meta">PowerPoint preview · {len(cards)} slides</div>' + "".join(cards))


def _xlsx_html(data: bytes) -> bytes:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True)
    parts = []
    for sheet in workbook.worksheets:
        rows = []
        for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
            if row_index > 250:
                break
            tag = "th" if row_index == 0 else "td"
            cells = "".join(
                f"<{tag}>{html.escape('' if value is None else str(value))}</{tag}>" for value in row
            )
            rows.append(f"<tr>{cells}</tr>")
        parts.append(f'<div class="sheet"><h3>{html.escape(sheet.title)}</h3><table>{"".join(rows)}</table></div>')
    count = len(workbook.worksheets)
    workbook.close()
    return _page("Excel", f'<div class="meta">Excel preview · {count} sheet(s)</div>' + "".join(parts))


def _docx_html(data: bytes) -> bytes:
    from docx import Document

    document = Document(io.BytesIO(data))
    parts = ['<div class="doc">']
    in_list = False
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style else ""
        is_list = "list" in style or "bullet" in style
        if is_list and not in_list:
            parts.append("<ul>")
            in_list = True
        elif not is_list and in_list:
            parts.append("</ul>")
            in_list = False
        if "title" in style or "heading 1" in style:
            parts.append(f"<h1>{html.escape(text)}</h1>")
        elif "heading" in style:
            parts.append(f"<h2>{html.escape(text)}</h2>")
        elif is_list:
            parts.append(f"<li>{html.escape(text)}</li>")
        else:
            parts.append(f"<p>{html.escape(text)}</p>")
    if in_list:
        parts.append("</ul>")
    for table in document.tables:
        rows = []
        for row_index, row in enumerate(table.rows):
            tag = "th" if row_index == 0 else "td"
            cells = "".join(f"<{tag}>{html.escape(cell.text)}</{tag}>" for cell in row.cells)
            rows.append(f"<tr>{cells}</tr>")
        parts.append(f"<table>{''.join(rows)}</table>")
    parts.append("</div>")
    return _page("Document", "".join(parts))


def _source_html(name: str, data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    body = (
        f'<div class="meta">Source preview · {html.escape(name)}</div>'
        f'<div class="source"><pre>{html.escape(text)}</pre></div>'
    )
    return _page(name, body)


def to_preview(
    name: str,
    mime: str,
    data: bytes,
    *,
    cache_path: Path | None = None,
) -> tuple[bytes, str]:
    """(content, media_type) for inline preview. Office → HTML; everything else served as-is."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in ("pptx", "docx", "xlsx", "xlsm"):
        pdf = _office_pdf(name, data, cache_path=cache_path)
        if pdf:
            return pdf, "application/pdf"
    try:
        if ext == "pptx":
            return _pptx_html(data), "text/html; charset=utf-8"
        if ext in ("xlsx", "xlsm"):
            return _xlsx_html(data), "text/html; charset=utf-8"
        if ext == "docx":
            return _docx_html(data), "text/html; charset=utf-8"
        if ext in ("tex", "bib", "sty", "cls"):
            return _source_html(name, data), "text/html; charset=utf-8"
    except Exception:  # noqa: BLE001 — on any parse failure, fall back to the raw bytes
        pass
    return data, mime
