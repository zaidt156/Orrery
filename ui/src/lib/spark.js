// Tiny pure helpers for the hand-drawn SVG sparklines (no charting library).

// SVG polyline `points` string for a numeric series inside a w×h box. Flat or single-value
// series draw a visible midline instead of collapsing; empty series draw nothing.
export function sparkPoints(values, w = 120, h = 34, pad = 2) {
  const series = (values || []).filter((v) => Number.isFinite(v));
  if (!series.length) return "";
  if (series.length === 1) series.push(series[0]);
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  const step = (w - pad * 2) / (series.length - 1);
  return series
    .map((v, i) => {
      const x = pad + i * step;
      const y = max === min ? h / 2 : pad + (1 - (v - min) / span) * (h - pad * 2);
      return `${Math.round(x * 100) / 100},${Math.round(y * 100) / 100}`;
    })
    .join(" ");
}

// Count ISO timestamps into `days` trailing daily buckets ending today (oldest → newest).
// Invalid dates and anything outside the window are ignored — real data only, never invented.
export function dayBuckets(timestamps, days = 14, now = new Date()) {
  const buckets = new Array(days).fill(0);
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() + 86_400_000;
  for (const stamp of timestamps || []) {
    const t = Date.parse(stamp);
    if (Number.isNaN(t)) continue;
    const age = Math.floor((end - 1 - t) / 86_400_000);
    if (age >= 0 && age < days) buckets[days - 1 - age] += 1;
  }
  return buckets;
}
