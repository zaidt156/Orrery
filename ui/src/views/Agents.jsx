const SIDE = [
  { name: "Ticket triager", pip: ["live", "RUNNING"], meta: ["continuous · checks every 5 min", "claude-sonnet-4-6 · scope: tickets"], active: true },
  { name: "Data quality fixer", pip: ["paused", "SLEEPS 1H"], meta: ["on a timer · wakes hourly", "gpt-4o · scope: orders"] },
  { name: "Report improver", pip: ["iter", "LOOP 4/10"], meta: ["until done · improving each pass", "llama3 · local · scope: digests"] },
];

export default function Agents() {
  return (
    <section className="view">
      <aside className="auto-side">
        <button className="btn primary">+ New agent</button>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--faint)", lineHeight: 1.7, padding: "0 3px" }}>
          a goal · a scope · a model ·<br />a way to run
        </div>
        <div className="convo-list">
          {SIDE.map((a) => (
            <div key={a.name} className={`wf${a.active ? " active" : ""}`} tabIndex={0}>
              <div className="w-name">{a.name} <span className={`status-pip ${a.pip[0]}`}>{a.pip[1]}</span></div>
              <div className="w-meta">{a.meta[0]}<br />{a.meta[1]}</div>
            </div>
          ))}
        </div>
      </aside>

      <div className="auto-main">
        <div className="auto-toolbar">
          <span className="view-title">Ticket triager</span>
          <span className="pill"><span className="pulse-dot" />Running</span>
          <span className="pill"><b className="mono" style={{ color: "var(--ice)", fontWeight: 500, fontSize: "10.5px" }}>claude-sonnet-4-6</b></span>
          <div className="grow" />
          <button className="btn">⏸ Pause</button>
          <button className="btn ghost">■ Stop</button>
          <button className="btn ghost">Edit scope</button>
        </div>

        <div className="agent-wrap">
          <div className="agent-cards">
            <div className="card acard">
              <h5>Goal</h5>
              <p>Keep every new support ticket triaged — category, priority, and a one-line summary. Accuracy matters more than speed; ask me when unsure.</p>
            </div>
            <div className="card acard">
              <h5>Scope — works only here</h5>
              <div className="scope-line">
                tables · <b>tickets</b> read/write · <b>products</b> read<br />
                tools · <b>database</b>, <b>LLM</b><br />
                <span className="no">cannot</span> delete rows · touch other tables<br />
                limits · 60 loops/day · 80% confidence bar
              </div>
            </div>
            <div className="card acard">
              <h5>Run mode &amp; budget</h5>
              <div className="scope-line">continuous · checks every <b>5 min</b><br />stops when · you stop it · budget hit · 3 errors in a row</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--muted)", marginTop: "10px" }}>today $0.42 / $2.00</div>
              <div className="slider" style={{ marginTop: "7px" }}><div className="fill" style={{ width: "21%" }} /></div>
            </div>
          </div>

          <div className="works-with">
            <span className="section-label" style={{ margin: 0 }}>Works with</span>
            <span className="pill">↔ agent · Data quality fixer</span>
            <span className="pill">→ automation · Doc reply drafts</span>
            <span className="pill">↑ you · approvals under 80% confidence</span>
          </div>

          <div className="feed">
            <div className="feed-head"><span className="pulse-dot" />Live activity — every step and learning is logged</div>
            <div className="fitem">
              <span className="f-it">LOOP 12</span>
              <span className="f-body">Found 3 new tickets — classified 2 billing, 1 bug at 94% confidence — wrote category, priority, summary to <span className="mono" style={{ color: "#7FD4C0" }}>tickets</span>.</span>
              <span className="f-time">2m</span>
            </div>
            <div className="fitem learn">
              <span className="f-it">NOTE</span>
              <span className="f-body"><b>Learned:</b> "urgent" in a subject line is a weak signal — refund mentions predict priority better. Saved to my notes; future loops start from this.</span>
              <span className="f-time">1h</span>
            </div>
            <div className="fitem">
              <span className="f-it">LOOP 9</span>
              <span className="f-body">Ticket #4811 classified at 61% — below my 80% bar, so it is waiting for you.
                <span className="approve-btns"><button className="btn">Approve</button><button className="btn ghost">Reclassify</button></span>
              </span>
              <span className="f-time">1h</span>
            </div>
            <div className="fitem">
              <span className="f-it">LOOP 8</span>
              <span className="f-body">Idle pass — no new tickets. Re-checked the last 20 labels against my notes; all consistent.</span>
              <span className="f-time">3h</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
