---
name: Dashboard & visualization design
triggers: dashboard, visualization, visualisation, chart, graph, kpi, widget, bi report, metric
---

## Activation boundary

Activate when designing dashboards, choosing chart types, or writing widget queries. Do not activate
for standalone image/diagram requests (image skill) or document tables (document/spreadsheet skills).

## Chart choice — match the shape of the question

- **stat**: one number the user tracks (total, count, average, latest). Round sensibly; the query
  returns exactly one row and the metric column is numeric.
- **line**: change over time. X must be a time-ordered column (`ORDER BY` it ascending); one row per
  period — aggregate with `date_trunc`/`date()` so points are evenly spaced.
- **bar**: comparison across categories. Order by the value descending; cap at 10–15 bars with LIMIT;
  aggregate the rest server-side rather than rendering 100 slivers.
- **pie**: composition of a whole, only when there are 2–6 slices and they sum to something meaningful.
  More than 6 categories → use a bar instead.
- **table**: detail lookup (latest records, top offenders). Pick 3–7 informative columns, never
  `SELECT *`; always LIMIT ≤ 50 and ORDER BY something meaningful (usually recency).

## Query discipline

- Aggregate in SQL, not in your head: charts want tidy label/value rows (GROUP BY), not raw records.
- Name output columns like labels: `AS revenue`, `AS month` — they appear on the chart axes.
- Handle NULLs (`COALESCE`) and empty tables gracefully; a widget that errors is worse than a simpler
  widget that works.
- Time series: truncate to a sensible grain (day for weeks of data, month for years), and use the
  same grain in the label column.
- Use transforms/data models for shared joins or cleaning instead of repeating them per widget.

## Dashboard composition

- Lead with a stat row (1–3 KPIs), then 2–4 charts that explain those numbers, then at most one
  detail table. 4–7 widgets total reads best.
- Every widget title states what the user sees ("Revenue by month", not "Chart 1").
- Prefer one clear question answered per widget over one widget answering three questions.
