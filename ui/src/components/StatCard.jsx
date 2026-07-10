import Sparkline from "./Sparkline.jsx";

// Concept stat card: L3 icon chip, big number, context line, real-data sparkline. The whole
// card navigates when onClick is given.
export default function StatCard({ icon: Icon, label, value, sub, series, stroke, onClick }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag type={onClick ? "button" : undefined} className="stat-card surface-2" onClick={onClick}>
      <span className="icon-chip surface-3">{Icon ? <Icon /> : null}</span>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value ?? "—"}</span>
      {sub ? <span className="stat-sub">{sub}</span> : null}
      {series?.some((v) => v > 0) ? <Sparkline values={series} stroke={stroke} /> : null}
    </Tag>
  );
}
