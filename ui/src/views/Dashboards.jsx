import { useState } from "react";
import { SendIcon } from "../components/icons.jsx";

const LIST = [
  { name: "Sales overview", pip: ["live", "LIVE"], meta: ["built by claude-sonnet-4-6", "5 widgets · refreshes 15 min"] },
  { name: "Support health", pip: ["live", "LIVE"], meta: ["built by gpt-4o", "4 widgets · refreshes hourly"] },
  { name: "Infra costs", pip: ["paused", "DRAFT"], meta: ["built by llama3 · local"] },
];

const BARS = [
  ["Atlas Pro", 100, "$84.2k"],
  ["Nimbus API", 62, "$52.4k"],
  ["Field Kit", 38, "$31.9k"],
  ["Halo Add-on", 15, "$12.6k"],
];

export default function Dashboards() {
  const [active, setActive] = useState(0);
  return (
    <section className="view">
      <aside className="auto-side">
        <button className="btn primary">+ New dashboard</button>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--faint)", lineHeight: 1.7, padding: "0 3px" }}>
          describe it in plain words ·<br />pick the model that builds it
        </div>
        <div className="convo-list">
          {LIST.map((d, i) => (
            <div key={d.name} className={`wf${i === active ? " active" : ""}`} tabIndex={0} onClick={() => setActive(i)}>
              <div className="w-name">{d.name} <span className={`status-pip ${d.pip[0]}`}>{d.pip[1]}</span></div>
              <div className="w-meta">{d.meta[0]}{d.meta[1] && <><br />{d.meta[1]}</>}</div>
            </div>
          ))}
        </div>
      </aside>

      <div className="auto-main">
        <div className="auto-toolbar">
          <span className="view-title">Sales overview</span>
          <span className="pill"><b className="mono" style={{ color: "var(--ice)", fontWeight: 500, fontSize: "10.5px" }}>built by claude-sonnet-4-6</b></span>
          <span className="pill">auto-refresh · 15 min</span>
          <div className="grow" />
          <button className="btn primary">↻ Refresh now</button>
          <button className="btn ghost">Share</button>
          <button className="btn ghost" aria-label="More">⋯</button>
        </div>

        <div className="dash-wrap">
          <div className="dash-grid">
            <div className="widget">
              <div className="w-label">Revenue · this month</div>
              <div className="stat-num">$168.4k</div>
              <div className="stat-delta up2">▲ +12% vs May</div>
              <div className="w-sql">SELECT SUM(total) FROM orders WHERE created_at &gt;= date_trunc('month', now())</div>
            </div>
            <div className="widget">
              <div className="w-label">Orders</div>
              <div className="stat-num">1,284</div>
              <div className="stat-delta up2">▲ +6.1%</div>
              <div className="w-sql">SELECT COUNT(*) FROM orders WHERE …</div>
            </div>

            <div className="widget span2">
              <div className="w-label">Revenue · last 30 days <span className="w-by">claude-sonnet-4-6</span></div>
              <svg className="spark" viewBox="0 0 320 100" aria-hidden="true">
                <defs>
                  <linearGradient id="lg1" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0" stopColor="#9DB9F0" /><stop offset="1" stopColor="#F2B14E" />
                  </linearGradient>
                </defs>
                <path d="M10,76 L54,66 L98,71 L142,54 L186,60 L230,41 L274,46 L312,22" fill="none" stroke="url(#lg1)" strokeWidth="1.6" />
                <g fill="#E8ECF8">
                  <circle cx="10" cy="76" r="2" /><circle cx="54" cy="66" r="2" /><circle cx="98" cy="71" r="2" />
                  <circle cx="142" cy="54" r="2" /><circle cx="186" cy="60" r="2" /><circle cx="230" cy="41" r="2" /><circle cx="274" cy="46" r="2" />
                </g>
                <circle cx="312" cy="22" r="3" fill="#F2B14E" />
              </svg>
              <div className="w-sql">SELECT date(created_at), SUM(total) FROM orders GROUP BY 1 ORDER BY 1</div>
            </div>

            <div className="widget span2">
              <div className="w-label">Top products <span className="w-by">claude-sonnet-4-6</span></div>
              <div className="bars">
                {BARS.map(([name, pct, val]) => (
                  <div className="bar-row" key={name}>
                    <span className="b-name">{name}</span>
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${pct}%` }} /></div>
                    <span className="b-val">{val}</span>
                  </div>
                ))}
              </div>
              <div className="w-sql">SELECT product, SUM(total) FROM orders GROUP BY product ORDER BY 2 DESC LIMIT 4</div>
            </div>

            <div className="widget span2">
              <div className="w-label">Latest orders <span className="w-by">added by gpt-4o</span></div>
              <table className="mini-table">
                <tbody>
                  <tr><th>CUSTOMER</th><th>PRODUCT</th><th>TOTAL</th></tr>
                  <tr><td>Meridian Co</td><td>Atlas Pro</td><td>$1,920</td></tr>
                  <tr><td>Halberd Labs</td><td>Nimbus API</td><td>$640</td></tr>
                  <tr><td>Outland LLC</td><td>Field Kit</td><td>$275</td></tr>
                </tbody>
              </table>
              <div className="w-sql">SELECT customer, product, total FROM orders ORDER BY created_at DESC LIMIT 3</div>
            </div>

            <div className="widget span2 card add" style={{ minHeight: 0 }}>+ Add a widget — or pin one from Chat</div>
          </div>
        </div>

        <div className="revise">
          <div className="composer-box">
            <span className="pill model-pill" style={{ flex: "none" }}><b>claude-sonnet-4-6</b> ⌄</span>
            <input placeholder="Change this dashboard — add a refunds widget, make revenue weekly…" />
            <button className="send" aria-label="Apply"><SendIcon /></button>
          </div>
          <div className="hint2">designed by AI once — refreshing just re-runs the saved queries on your live data, no AI needed</div>
        </div>
      </div>
    </section>
  );
}
