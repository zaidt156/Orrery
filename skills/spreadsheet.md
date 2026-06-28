---
name: Spreadsheet / Excel / CSV design
triggers: excel, xlsx, xls, spreadsheet, workbook, sheet, csv, table of data, dataset, data file
---
Use this skill when the user asks for a spreadsheet, workbook, CSV, dataset, tabular template, or data file.
Design it through the `orrery-doc` JSON `sheets` array or the configured spreadsheet artifact mechanism.

## Spreadsheet contract

- **One fact per cell.** Use clear columns, one record per row, and one value per cell.
- **Typed data.** Keep dates, numbers, currency, percentages, and IDs consistently typed. Put units in headers,
  not inside values.
- **No unsafe formulas by default.** Never start a value with `=`, `+`, `-`, or `@` unless the user explicitly
  asks for formulas. Escape user-provided text that could trigger formula injection.
- **Use multiple sheets when useful.** Separate raw data, lookup tables, summary tables, assumptions, and data
  dictionaries instead of cramming unrelated content into one sheet.
- **Make sample data realistic.** If dummy/sample data is requested, create complete, varied, plausible rows.
  Do not use repeated rows, ellipses, or placeholder-only records.
- **Prefer tidy layout.** Avoid merged cells, decorative spacing, hidden assumptions, or mixed tables on the same
  sheet unless the user asks for a formatted report.
- **Include formulas deliberately.** When formulas are requested, keep references readable, document assumptions,
  and avoid volatile or external-link formulas unless necessary.
- **Validate the workbook.** Check sheet names, row counts, column headers, data types, and whether requested
  formulas or summaries are present.
