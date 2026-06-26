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
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

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

def _rgb(hex_color: str) -> RGBColor:
    value = hex_color.strip().lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _fill(shape, color: str) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    shape.line.fill.background()


def _rect(slide, left, top, width, height, color: str):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    _fill(shape, color)
    return shape


def _text(slide, left, top, width, height, text: str, size: int, color: str,
          bold: bool = False, align=None):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.text = _s(text)
    if align is not None:
        paragraph.alignment = align
    run_font = paragraph.runs[0].font if paragraph.runs else paragraph.font
    run_font.size = Pt(size)
    run_font.bold = bold
    run_font.color.rgb = _rgb(color)
    return box


def _bullets(slide, bullets: list[str], left, top, width, height) -> None:
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(0.05)
    frame.margin_right = Inches(0.08)
    clean = [_s(b) for b in bullets if _s(b)][:8]
    if not clean:
        clean = ["Key points to discuss"]
    for index, bullet in enumerate(clean):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = bullet
        paragraph.level = 0
        paragraph.space_after = Pt(8)
        paragraph.font.size = Pt(19 if len(clean) <= 5 else 17)
        paragraph.font.color.rgb = _rgb("172033")


def build_pptx(spec: dict, title: str) -> bytes:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    deck_title = _s(spec.get("title")) or title
    subtitle = _s(spec.get("subtitle"))

    cover = prs.slides.add_slide(blank)
    _rect(cover, 0, 0, prs.slide_width, prs.slide_height, "0B1020")
    _rect(cover, Inches(0.55), Inches(0.55), Inches(0.12), Inches(6.4), "F2B14E")
    _text(cover, Inches(1.05), Inches(2.2), Inches(11.2), Inches(1.05), deck_title, 42, "FFFFFF", True)
    if subtitle:
        _text(cover, Inches(1.08), Inches(3.35), Inches(10.5), Inches(0.55), subtitle, 20, "C9D4EA")
    _text(cover, Inches(1.08), Inches(6.65), Inches(4.2), Inches(0.25), "Generated by Orrery", 10, "8D99AE")

    slides = [s for s in _spec_slides(spec, deck_title) if isinstance(s, dict)]
    for index, slide_spec in enumerate(slides, start=1):
        slide = prs.slides.add_slide(blank)
        _rect(slide, 0, 0, prs.slide_width, prs.slide_height, "F7F8FB")
        _rect(slide, 0, 0, Inches(0.28), prs.slide_height, "F2B14E")
        _rect(slide, Inches(0.28), 0, Inches(0.06), prs.slide_height, "26314F")
        _text(slide, Inches(0.72), Inches(0.48), Inches(10.7), Inches(0.78), slide_spec.get("title", ""), 28, "0B1020", True)
        _text(slide, Inches(11.75), Inches(0.58), Inches(0.9), Inches(0.3), f"{index:02d}", 11, "69758A", False, PP_ALIGN.RIGHT)
        _bullets(slide, [_s(b) for b in _list(slide_spec.get("bullets"))], Inches(1.02), Inches(1.55), Inches(11.1), Inches(4.95))
        _rect(slide, Inches(1.02), Inches(6.72), Inches(11.2), Inches(0.015), "D9DEE8")
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


def _md_table(columns, rows) -> str:
    """A Markdown table — rows on CONSECUTIVE lines (blank lines between rows break the table)."""
    cols = [_s(c) for c in _list(columns)]
    lines: list[str] = []
    if cols:
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for row in _list(rows):
        values = [_s(v) for v in (row if isinstance(row, list) else [row])]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def spec_to_markdown(spec: dict) -> str:
    """Render the spec to Markdown for md/txt/html exports and non-PDF previews."""
    blocks: list[str] = []
    title = _s(spec.get("title"))
    if title:
        blocks.append(f"# {title}")
    if spec.get("slides"):
        for index, slide in enumerate(_spec_slides(spec, title), start=1):
            if not isinstance(slide, dict):
                continue
            lines = [f"## Slide {index}: {_s(slide.get('title'))}".rstrip(": ")]
            lines += [f"- {_s(b)}" for b in _list(slide.get("bullets")) if _s(b)]
            blocks.append("\n".join(lines))
    elif spec.get("sheets"):
        for sheet in _spec_sheets(spec):
            heading = f"## {_s(sheet.get('name')) or 'Sheet'}"
            table = _md_table(sheet.get("columns"), sheet.get("rows"))
            blocks.append(f"{heading}\n\n{table}" if table else heading)
    else:
        for section in _list(spec.get("sections")):
            if not isinstance(section, dict):
                continue
            chunk: list[str] = []
            if section.get("heading"):
                level = section.get("level", 1)
                hashes = "#" * (int(level) if str(level).isdigit() and 1 <= int(level) <= 6 else 1)
                chunk.append(f"{hashes} {_s(section['heading'])}")
            chunk += [_s(p) for p in _list(section.get("paragraphs")) if _s(p)]
            bullets = [f"- {_s(b)}" for b in _list(section.get("bullets")) if _s(b)]
            if bullets:
                chunk.append("\n".join(bullets))
            table_spec = section.get("table")
            if isinstance(table_spec, dict):
                table = _md_table(table_spec.get("columns"), table_spec.get("rows"))
                if table:
                    chunk.append(table)
            if chunk:
                blocks.append("\n\n".join(chunk))
    return "\n\n".join(b for b in blocks if b).strip() or title or "Document"


# --- entry points ----------------------------------------------------------

def render_spec(title: str, model: str, spec: dict, export_format: str) -> ExportResult:
    # Name the document after its OWN title (the model sets it in the spec), not the chat name;
    # the conversation title is only a last resort if the spec didn't provide one.
    doc_title = _s(spec.get("title")) or title or "Document"
    slug = exports._slug(doc_title)
    if export_format == "pptx":
        return ExportResult(build_pptx(spec, doc_title), _PPTX_MIME, f"{slug}.pptx")
    if export_format == "xlsx":
        return ExportResult(build_xlsx(spec, doc_title), _XLSX_MIME, f"{slug}.xlsx")
    if export_format == "csv":
        return ExportResult(build_csv(spec), "text/csv; charset=utf-8", f"{slug}.csv")
    if export_format == "json":
        return ExportResult((json.dumps(spec, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
                            "application/json; charset=utf-8", f"{slug}.json")
    if export_format == "pdf":
        return ExportResult(exports.build_pdf(doc_title, model, _spec_to_blocks(spec)), "application/pdf", f"{slug}.pdf")
    if export_format == "docx":
        return ExportResult(exports.build_docx(doc_title, model, _spec_to_blocks(spec)), _DOCX_MIME, f"{slug}.docx")

    markdown = spec_to_markdown(spec)
    if export_format == "html":
        return ExportResult(exports.build_html(doc_title, model, markdown), "text/html; charset=utf-8", f"{slug}.html")
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
