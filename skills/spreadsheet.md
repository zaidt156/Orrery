---
name: Spreadsheet / Excel / CSV design
triggers: excel, xlsx, xls, spreadsheet, workbook, worksheet, csv, tsv, table of data, dataset, data file, pivot
---
Use this skill when the user asks for a spreadsheet, workbook, CSV, dataset, tabular template, or data file.
Design it through the `orrery-doc` JSON `sheets` array or the configured spreadsheet artifact mechanism.

## Activation boundary

Activate when the deliverable is a tabular data file. Do not activate for finance concepts that merely contain
the word ("balance sheet", "term sheet"), for HTML tables inside a web page (web artifact skill), or for a
Markdown table inside a document (document skill).

## Spreadsheet contract

- **One fact per cell.** Use clear columns, one record per row, and one value per cell.
- **Typed data.** Keep dates, numbers, currency, percentages, and IDs consistently typed. Use ISO 8601 dates
  (YYYY-MM-DD) unless the user specifies a locale format. Put units in headers, not inside values.
- **State encoding and delimiter for CSV.** Default to UTF-8 with comma separators; offer semicolon separation
  when the user's locale or Excel build expects it, since many European Excel installations misparse
  comma-separated files (and pair commas with decimal points, not decimal commas).
- **No unsafe formulas by default.** Never start a value with `=`, `+`, `-`, or `@` unless the user explicitly
  asks for formulas, and escape user-provided text that could trigger formula injection — spreadsheet apps
  execute such cells on open.
- **Use multiple sheets when useful.** Separate raw data, lookup tables, summary tables, assumptions, and data
  dictionaries instead of cramming unrelated content into one sheet. Add a data-dictionary sheet to multi-sheet
  workbooks.
- **Make sample data realistic.** If dummy/sample data is requested, create complete, varied, plausible rows —
  default to 20–50 rows unless the user sets a size. Do not use repeated rows, ellipses, or placeholder-only
  records.
- **Prefer tidy layout.** Avoid merged cells, decorative spacing, hidden assumptions, or mixed tables on the same
  sheet unless the user asks for a formatted report. Bold and freeze the header row in XLSX output.
- **Include formulas deliberately.** When formulas are requested, keep references readable, document assumptions,
  and avoid volatile or external-link formulas unless necessary.
- **Validate the workbook.** Check sheet names, row counts, column headers, data types, and whether requested
  formulas or summaries are present; fix failures before returning.
