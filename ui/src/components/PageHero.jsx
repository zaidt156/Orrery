// Concept hero banner: title + subtitle (+ badge pills) on the left, the reference art's orbital
// system on the right — thin rings, a small sun, planet dots. `compact` for views with a toolbar.
export default function PageHero({ title, subtitle, badges = [], actions = null, compact = false }) {
  return (
    <div className={`page-hero surface-1${compact ? " compact" : ""}`}>
      <div className="page-hero-copy">
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
        {badges.length > 0 && (
          <div className="page-hero-badges">
            {badges.map((b) => <span key={b} className="pill">{b}</span>)}
          </div>
        )}
        {actions}
      </div>
      <div className="hero-art" aria-hidden="true">
        <i className="hero-ring r1" /><i className="hero-ring r2" /><i className="hero-ring r3" />
        <i className="hero-sun" />
        <i className="hero-dot d1" /><i className="hero-dot d2" /><i className="hero-dot d3" />
      </div>
    </div>
  );
}
