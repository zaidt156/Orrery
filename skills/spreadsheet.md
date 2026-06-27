---
name: Spreadsheet / Excel / CSV design
triggers: excel, xlsx, xls, spreadsheet, workbook, sheet, csv, table of data, dataset, data file
---
When the request is a spreadsheet, design it via the `orrery-doc` JSON `sheets` array (see the FILES
instruction for the schema). Build a real, tidy dataset:

- **Clear columns.** Give every column a short, specific header. Keep one fact per column and one
  record per row. Don't merge multiple values into a cell.
- **Consistent, typed data.** Format numbers, dates, and currency consistently down each column.
  Use plain numbers (no thousands separators or units inside the value — put units in the header).
- **Realistic, complete rows.** If the user asks for N rows of sample/dummy data, produce N full
  rows with plausible, varied values — not placeholders like "..." or repeated identical rows.
- **Multiple sheets when it helps.** Use a separate sheet per logical table (e.g. "Employees",
  "Departments") rather than cramming unrelated tables together.
- Never start a cell value with `=`, `+`, `-`, or `@` unless it is genuinely a formula the user asked
  for (Orrery escapes these to prevent spreadsheet formula injection).
