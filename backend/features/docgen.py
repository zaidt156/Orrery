"""Structured document generation: the model designs a file as JSON (slides, sheets,
sections); Orrery builds a *real* PPTX/XLSX/DOCX/PDF/… from it deterministically.

This is the "model designs, Orrery builds" path — no model-written code is executed.
A reply carries the design inside a ```orrery-doc fenced JSON block; if present we build
from the structure, otherwise callers fall back to rendering the reply's Markdown.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re

from pptx import Presentation
from pptx.util import Pt

from backend.features import exports
from backend.features.exports import (
    ExportBlock,
    ExportResult,
    ExportTooLarge,
    InlineSpan,
)

_SPEC_FENCE = re.compile(r"```orrery-doc\s*\n([\s\S]*?)```", re.IGNORECASE)
MAX_SPEC_CHARS = 600_000
MAX_ITEMS = 1_000  # slides / sheets / sections / rows guard

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def parse_doc_spec(content: str | None) -> dict | None:
    """Return the structured spec embedded in a reply, or None to fall back to Markdown."""
    if not content or "orrery-doc" not in content:
        return None
    match = _SPEC_FENCE.search(content)
    if not match:
        return None
    raw = match.group(1).strip()
    if not raw or len(raw) > MAX_SPEC_CHARS:
        return None
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return spec if isinstance(spec, dict) and (spec.get("slides") or spec.get("sheets") or spec.get("sections")) else None


def has_doc_spec(content: str | None) -> bool:
    return parse_doc_spec(content) is not None


def _s(value) -> str:
    return exports._clean_text("" if value is None else str(value))


def _list(value) -> list:
    return value[:MAX_ITEMS] if isinstance(value, list) else []


def _spans(text) -> list[InlineSpan]:
    return [InlineSpan(_s(text))]


# --- shared coercions ------------------------------------------------------

def _spec_sheets(spec: dict) -> list[dict]:
    sheets = _list(spec.get("sheets"))
    if sheets:
        return sheets
    derived: list[dict] = []
    for section in _list(spec.get("sections")):
        table = section.get("table") if isinstance(section, dict) else None
        if isinstance(table, dict) and table.get("rows"):
            derived.append({
                "name": section.get("heading", "Sheet"),
                "columns": table.get("columns", []),
                "rows": table.get("rows", []),
            })
    return derived


def _spec_slides(spec: dict, fallback_title: str) -> list[dict]:
    slides = _list(spec.get("slides"))
    if slides:
        return slides
    derived: list[dict] = []
    for section in _list(spec.get("sections")):
        if not isinstance(section, dict):
            continue
        bullets = [_s(p) for p in _list(section.get("paragraphs"))] + [_s(b) for b in _list(section.get("bullets"))]
        derived.append({"title": section.get("heading", fallback_title), "bullets": bullets})
    return derived


def _spec_to_blocks(spec: dict) -> list[ExportBlock]:
    """Document blocks for PDF/DOCX: prefer sections, else slides, else sheets-as-tables."""
    blocks: list[ExportBlock] = []
    sections = _list(spec.get("sections"))
    if sections:
        for section in sections:
            if not isinstance(section, dict):
                continue
            if section.get("heading"):
                level = section.get("level", 1)
                blocks.append(ExportBlock(kind="heading", spans=_spans(section["heading"]),
                                          level=int(level) if str(level).isdigit() else 1))
            for paragraph in _list(section.get("paragraphs")):
                blocks.append(ExportBlock(kind="paragraph", spans=_spans(paragraph)))
            for bullet in _list(section.get("bullets")):
                blocks.append(ExportBlock(kind="bullet", spans=_spans(bullet)))
            table = section.get("table")
            if isinstance(table, dict) and table.get("rows"):
                blocks.append(_table_block(table))
        return blocks

    for slide in _spec_slides(spec, spec.get("title", "")):
        if not isinstance(slide, dict):
            continue
        blocks.append(ExportBlock(kind="heading", spans=_spans(slide.get("title", "")), level=2))
        for bullet in _list(slide.get("bullets")):
            blocks.append(ExportBlock(kind="bullet", spans=_spans(bullet)))
    return blocks


def _table_block(table: dict) -> ExportBlock:
    rows: list[list[str]] = []
    columns = _list(table.get("columns"))
    if columns:
        rows.append([_s(c) for c in columns])
    for row in _list(table.get("rows")):
        rows.append([_s(c) for c in row] if isinstance(row, list) else [_s(row)])
    if sum(len(r) for r in rows) > exports.MAX_TABLE_CELLS:
        raise ExportTooLarge("This table is too large to build safely.")
    return ExportBlock(kind="table", rows=rows)


# --- real-format builders --------------------------------------------------

def build_pptx(spec: dict, title: str) -> bytes:
    prs = Presentation()
    deck_title = _s(spec.get("title")) or title
    cover = prs.slides.add_slide(prs.slide_layouts[0])
    cover.shapes.title.text = deck_title
    if len(cover.placeholders) > 1:
        cover.placeholders[1].text = _s(spec.get("subtitle"))

    for slide_spec in _spec_slides(spec, deck_title):
        if not isinstance(slide_spec, dict):
            continue
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = _s(slide_spec.get("title"))
        body = slide.placeholders[1].text_frame
        body.clear()
        bullets = [_s(b) for b in _list(slide_spec.get("bullets")) if _s(b)]
        for index, bullet in enumerate(bullets):
            paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
            paragraph.text = bullet
            paragraph.font.size = Pt(18)
        notes = _s(slide_spec.get("notes"))
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    output = io.BytesIO()
    prs.save(output)
    return output.getvalue()


def build_xlsx(spec: dict, title: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = _spec_sheets(spec) or [{"name": "Sheet1", "columns": [], "rows": []}]
    cells = 0
    for index, sheet_spec in enumerate(sheets, start=1):
        name = (_s(sheet_spec.get("name")) or f"Sheet{index}")[:31] or f"Sheet{index}"
        sheet = workbook.create_sheet(name)
        row_number = 1
        columns = _list(sheet_spec.get("columns"))
        if columns:
            for column_index, column in enumerate(columns, start=1):
                cell = sheet.cell(row_number, column_index, exports._excel_safe(_s(column))[:32_767])
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="26314F")
            row_number += 1
        for row in _list(sheet_spec.get("rows")):
            values = row if isinstance(row, list) else [row]
            cells += len(values)
            if cells > exports.MAX_TABLE_CELLS:
                raise ExportTooLarge("This spreadsheet is too large to build safely.")
            for column_index, value in enumerate(values, start=1):
                cell = sheet.cell(row_number, column_index, exports._excel_safe(_s(value))[:32_767])
                cell.alignment = Alignment(vertical="top", wrap_text=True)
            row_number += 1
        width = max((len(_list(sheet_spec.get("columns"))), *(len(r) if isinstance(r, list) else 1 for r in _list(sheet_spec.get("rows")))), default=1)
        for column_index in range(1, width + 1):
            sheet.column_dimensions[get_column_letter(column_index)].width = 22
        sheet.freeze_panes = "A2"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_csv(spec: dict) -> bytes:
    sheets = _spec_sheets(spec)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if sheets:
        first = sheets[0]
        if _list(first.get("columns")):
            writer.writerow([exports._excel_safe(_s(c)) for c in _list(first.get("columns"))])
        for row in _list(first.get("rows")):
            values = row if isinstance(row, list) else [row]
            writer.writerow([exports._excel_safe(_s(v)) for v in values])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def spec_to_markdown(spec: dict) -> str:
    """Render the spec to Markdown for md/txt/html exports and non-PDF previews."""
    parts: list[str] = []
    title = _s(spec.get("title"))
    if title:
        parts.append(f"# {title}")
    if spec.get("slides"):
        for index, slide in enumerate(_spec_slides(spec, title), start=1):
            if not isinstance(slide, dict):
                continue
            parts.append(f"## Slide {index}: {_s(slide.get('title'))}".rstrip(": "))
            parts.extend(f"- {_s(b)}" for b in _list(slide.get("bullets")) if _s(b))
    elif spec.get("sheets"):
        for sheet in _spec_sheets(spec):
            parts.append(f"## {_s(sheet.get('name')) or 'Sheet'}")
            columns = [_s(c) for c in _list(sheet.get("columns"))]
            if columns:
                parts.append("| " + " | ".join(columns) + " |")
                parts.append("| " + " | ".join("---" for _ in columns) + " |")
            for row in _list(sheet.get("rows")):
                values = [_s(v) for v in (row if isinstance(row, list) else [row])]
                parts.append("| " + " | ".join(values) + " |")
    else:
        for section in _list(spec.get("sections")):
            if not isinstance(section, dict):
                continue
            if section.get("heading"):
                level = section.get("level", 1)
                hashes = "#" * (int(level) if str(level).isdigit() and 1 <= int(level) <= 6 else 1)
                parts.append(f"{hashes} {_s(section['heading'])}")
            parts.extend(_s(p) for p in _list(section.get("paragraphs")))
            parts.extend(f"- {_s(b)}" for b in _list(section.get("bullets")))
    return "\n\n".join(p for p in parts if p).strip() or title or "Document"


# --- entry points ----------------------------------------------------------

def render_spec(title: str, model: str, spec: dict, export_format: str) -> ExportResult:
    slug = exports._slug(title)
    if export_format == "pptx":
        return ExportResult(build_pptx(spec, title), _PPTX_MIME, f"{slug}.pptx")
    if export_format == "xlsx":
        return ExportResult(build_xlsx(spec, title), _XLSX_MIME, f"{slug}.xlsx")
    if export_format == "csv":
        return ExportResult(build_csv(spec), "text/csv; charset=utf-8", f"{slug}.csv")
    if export_format == "json":
        return ExportResult((json.dumps(spec, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
                            "application/json; charset=utf-8", f"{slug}.json")
    if export_format == "pdf":
        return ExportResult(exports.build_pdf(title, model, _spec_to_blocks(spec)), "application/pdf", f"{slug}.pdf")
    if export_format == "docx":
        return ExportResult(exports.build_docx(title, model, _spec_to_blocks(spec)), _DOCX_MIME, f"{slug}.docx")

    markdown = spec_to_markdown(spec)
    if export_format == "html":
        return ExportResult(exports.build_html(title, model, markdown), "text/html; charset=utf-8", f"{slug}.html")
    if export_format == "md":
        return ExportResult((markdown + "\n").encode("utf-8"), "text/markdown; charset=utf-8", f"{slug}.md")
    if export_format == "txt":
        plain = exports.blocks_to_plain(_spec_to_blocks(spec))
        return ExportResult((plain + "\n").encode("utf-8"), "text/plain; charset=utf-8", f"{slug}.txt")
    raise ValueError("Unsupported export format")


def _slide_card(title: str, bullets: list[str], number: int, cover: bool = False) -> str:
    items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets if b)
    body = f"<ul>{items}</ul>" if items else ""
    return (
        f'<div class="slide{" cover" if cover else ""}">'
        f'<div class="snum">{number}</div><h2>{html.escape(title or "")}</h2>{body}</div>'
    )


def build_pptx_preview_html(title: str, spec: dict) -> bytes:
    """A preview that actually looks like a deck: each slide as a 16:9 card."""
    deck_title = _s(spec.get("title")) or title
    cards = [_slide_card(deck_title, [_s(spec.get("subtitle"))] if _s(spec.get("subtitle")) else [], 1, cover=True)]
    for index, slide in enumerate(_spec_slides(spec, deck_title), start=2):
        if not isinstance(slide, dict):
            continue
        cards.append(_slide_card(_s(slide.get("title")), [_s(b) for b in _list(slide.get("bullets")) if _s(b)], index))
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(deck_title)} preview</title><style>
*{{box-sizing:border-box}} body{{background:#1b2030;margin:0;padding:26px 22px 60px;font-family:Arial,Helvetica,sans-serif}}
.deck-meta{{color:#9aa6bd;font-size:12px;text-align:center;margin-bottom:18px}}
.slide{{position:relative;width:100%;max-width:880px;aspect-ratio:16/9;margin:0 auto 22px;background:#fff;
  border-radius:12px;box-shadow:0 10px 34px rgba(0,0,0,.40);padding:48px 56px;overflow:hidden;color:#172033}}
.slide h2{{font-size:30px;line-height:1.2;margin:0 0 20px;color:#0b1020}}
.slide ul{{margin:0;padding-left:26px}} .slide li{{font-size:21px;line-height:1.55;margin:10px 0}}
.slide .snum{{position:absolute;right:18px;bottom:13px;font-size:13px;color:#9aa6bd}}
.slide.cover{{display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;
  background:linear-gradient(135deg,#0B1020,#1d2b54);color:#fff}}
.slide.cover h2{{font-size:46px;color:#fff;margin:0}}
.slide.cover ul{{list-style:none;padding:0;margin-top:16px}} .slide.cover li{{font-size:23px;color:#cdd8f0}}
</style></head><body>
<div class="deck-meta">PowerPoint preview · {len(cards)} slides</div>
{''.join(cards)}
</body></html>"""
    return document.encode("utf-8")


def render_spec_preview(title: str, model: str, spec: dict, export_format: str) -> ExportResult:
    if export_format == "pdf":
        return render_spec(title, model, spec, "pdf")
    if export_format == "pptx":
        return ExportResult(build_pptx_preview_html(title, spec), "text/html; charset=utf-8",
                            f"{exports._slug(title)}-preview.html")
    markdown = spec_to_markdown(spec)
    return ExportResult(
        exports.build_preview_html(title, model, markdown, export_format),
        "text/html; charset=utf-8",
        f"{exports._slug(title)}-preview.html",
    )
