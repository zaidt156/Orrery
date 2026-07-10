import { sparkPoints } from "../lib/spark.js";

// Hand-drawn SVG sparkline — real data only; renders nothing for an empty series.
export default function Sparkline({ values, width = 120, height = 34, stroke = "var(--blue)" }) {
  const points = sparkPoints(values, width, height);
  if (!points) return null;
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline points={points} fill="none" stroke={stroke} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
