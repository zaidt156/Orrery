import { useState, useRef, useLayoutEffect, useCallback } from "react";

const SIDE = [
  { name: "Morning sales digest", pip: ["live", "ACTIVE"], meta: ["cron · weekdays 9:00", "last run 9:00 ✓ · 98% ok"] },
  { name: "Ticket triage", pip: ["live", "ACTIVE"], meta: ["on new row · tickets", "live trigger · 124 runs"] },
  { name: "Doc reply drafts", pip: ["paused", "PAUSED"], meta: ["webhook · /hooks/drafts"] },
];

const PALETTE = [
  ["var(--ice)", "Schedule"], ["var(--ice)", "On new row"],
  ["var(--amber)", "LLM prompt"], ["var(--amber)", "Search docs"],
  ["#7FD4C0", "DB query"], ["#7FD4C0", "HTTP request"],
  ["#C49DF0", "If / branch"], ["#C49DF0", "Python snippet"],
];

const NODES = [
  { id: "n1", kind: "k-trigger", k: "Trigger", title: "Every weekday", sub: "cron 0 9 * * 1-5", left: 170, top: 118, ports: ["out"] },
  { id: "n2", kind: "k-data", k: "Data", title: "Query orders", sub: "SELECT … WHERE created_at…", left: 392, top: 118, ports: ["in", "out"] },
  { id: "n3", kind: "k-ai", k: "AI", title: "Write the digest", sub: "claude-sonnet-4-6 · {{n2.rows}}", left: 614, top: 110, ports: ["in", "out"] },
  { id: "n4", kind: "k-logic", k: "Logic", title: "Any decline?", sub: "if growth < 0 → flag", left: 836, top: 118, ports: ["in", "out"] },
  { id: "n5", kind: "k-data", k: "Data", title: "Post to Slack", sub: "POST hooks.slack.com/…", left: 836, top: 268, ports: ["in"] },
  { id: "n6", kind: "k-data", k: "Data", title: "Save digest", sub: "INSERT INTO digests", left: 614, top: 268, ports: ["in"] },
];

const EDGES = [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"], ["n3", "n6"]];

const CFG = {
  n1: { kind: "k-trigger", k: "Trigger", title: "Every weekday", fields: [
    { l: "Schedule (cron)", t: "input", v: "0 9 * * 1-5" },
    { l: "Timezone", t: "input", v: "Asia/Kolkata" },
    { l: "Powered by", t: "note", v: "Built-in scheduler — stored in your database" }] },
  n2: { kind: "k-data", k: "Data", title: "Query orders", fields: [
    { l: "Connection", t: "input", v: "main" },
    { l: "SQL", t: "area", v: "SELECT product, SUM(total)\nFROM orders\nWHERE created_at >= now() - interval '1 day'\nGROUP BY product;" },
    { l: "On failure", t: "input", v: "Retry ×3, exponential backoff" }] },
  n3: { kind: "k-ai", k: "AI", title: "Write the digest", fields: [
    { l: "Model", t: "input", v: "claude-sonnet-4-6  (via litellm)" },
    { l: "Prompt", t: "area", v: "Summarize yesterday’s sales for the team.\nHighlight movers and one risk.\n\nData: {{n2.rows}}" },
    { l: "Insert a variable", t: "vars", v: ["{{n2.rows}}", "{{n1.fired_at}}", "{{run.id}}"] },
    { l: "On failure", t: "input", v: "Retry ×3, exponential backoff" }] },
  n4: { kind: "k-logic", k: "Logic", title: "Any decline?", fields: [
    { l: "Condition", t: "input", v: "{{n3.growth_min}} < 0" },
    { l: "If true", t: "note", v: "continue to flag · if false, skip" }] },
  n5: { kind: "k-data", k: "Data", title: "Post to Slack", fields: [
    { l: "Method · URL", t: "input", v: "POST hooks.slack.com/T0…/B8…" },
    { l: "Body", t: "area", v: '{ "text": "{{n3.text}}" }' },
    { l: "On failure", t: "input", v: "Retry ×3, exponential backoff" }] },
  n6: { kind: "k-data", k: "Data", title: "Save digest", fields: [
    { l: "Connection · table", t: "input", v: "main · digests" },
    { l: "Insert", t: "area", v: '{ "body": "{{n3.text}}",\n  "run_id": "{{run.id}}" }' }] },
};

const RUNS = [
  { id: "s1", ok: true, when: "Today 9:00 — completed", time: "4.2s", steps: [
    ["Every weekday", "fired on schedule · 0.0s"],
    ["Query orders", "312 rows · 0.4s"],
    ["Write the digest", "486 tokens · 2.9s"],
    ["Any decline?", "false → skip flag · 0.0s"],
    ["Post to Slack · Save digest", "200 OK · inserted 1 row · 0.9s"],
  ] },
  { id: "s2", ok: false, when: "Jun 11, 9:00 — failed, then recovered", time: "31.8s", steps: [
    ["Post to Slack", "HTTP 500 — retried ×3 with backoff, succeeded on attempt 4", true],
  ] },
  { id: "s3", ok: true, when: "Jun 10, 9:00 — completed", time: "3.9s", steps: [
    ["All 6 nodes", "completed without retries"],
  ] },
];

export default function Automations() {
  const [selected, setSelected] = useState("n3");
  const [open, setOpen] = useState({});
  const [paths, setPaths] = useState([]);
  const canvasRef = useRef(null);
  const nodeRefs = useRef({});

  const drawEdges = useCallback(() => {
    const next = EDGES.map(([a, b]) => {
      const ea = nodeRefs.current[a];
      const eb = nodeRefs.current[b];
      if (!ea || !eb) return "";
      const x1 = ea.offsetLeft + ea.offsetWidth;
      const y1 = ea.offsetTop + ea.offsetHeight / 2;
      const x2 = eb.offsetLeft;
      const y2 = eb.offsetTop + eb.offsetHeight / 2;
      const dx = Math.max(36, (x2 - x1) / 2);
      return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    });
    setPaths(next);
  }, []);

  useLayoutEffect(() => {
    drawEdges();
    const t = setTimeout(drawEdges, 250); // recompute after fonts settle
    window.addEventListener("resize", drawEdges);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", drawEdges);
    };
  }, [drawEdges]);

  const c = CFG[selected];

  return (
    <section className="view">
      <aside className="auto-side">
        <button className="btn primary">+ New workflow</button>
        <div className="convo-list">
          {SIDE.map((w, i) => (
            <div key={w.name} className={`wf${i === 0 ? " active" : ""}`} tabIndex={0}>
              <div className="w-name">{w.name} <span className={`status-pip ${w.pip[0]}`}>{w.pip[1]}</span></div>
              <div className="w-meta">{w.meta[0]}{w.meta[1] && <><br />{w.meta[1]}</>}</div>
            </div>
          ))}
        </div>
      </aside>

      <div className="auto-main">
        <div className="auto-toolbar">
          <span className="view-title">Morning sales digest</span>
          <span className="pill"><span className="sdot badge-on" style={{ background: "var(--green)", width: "6px", height: "6px" }} />Active</span>
          <div className="grow" />
          <button className="btn primary">▶ Run now</button>
          <button className="btn">Pause</button>
          <button className="btn ghost">Export JSON</button>
          <button className="btn ghost" aria-label="More">⋯</button>
        </div>

        <div className="canvas-zone">
          <div className="canvas" ref={canvasRef}>
            <svg className="edges">
              {paths.map((d, i) => d && <path key={i} d={d} />)}
            </svg>

            <div className="palette">
              <div className="p-label">Add a node</div>
              {PALETTE.map(([color, label]) => (
                <div className="p-item" key={label}><i style={{ background: color }} />{label}</div>
              ))}
            </div>

            {NODES.map((n) => (
              <div
                key={n.id}
                ref={(el) => (nodeRefs.current[n.id] = el)}
                className={`node${selected === n.id ? " selected" : ""}`}
                style={{ left: `${n.left}px`, top: `${n.top}px` }}
                tabIndex={0}
                onClick={() => setSelected(n.id)}
              >
                <div className={`n-kind ${n.kind}`}><span className="k-star" />{n.k}</div>
                <div className="n-title">{n.title}</div>
                <div className="n-sub">{n.sub}</div>
                {n.ports.includes("in") && <span className="port in" />}
                {n.ports.includes("out") && <span className="port out" />}
              </div>
            ))}
          </div>

          <aside className="config">
            <div className="cfg-head">
              <div className={`n-kind ${c.kind}`}><span className="k-star" />{c.k} node</div>
              <div className="cfg-title">{c.title}</div>
            </div>
            {c.fields.map((f, i) => (
              <div className="field" key={i}>
                <label>{f.l}</label>
                {f.t === "input" && <div className="input mono" style={{ fontSize: "11px" }}>{f.v}</div>}
                {f.t === "area" && <textarea rows={5} readOnly value={f.v} />}
                {f.t === "note" && <div style={{ fontSize: "11.5px", color: "var(--muted)", lineHeight: 1.55 }}>{f.v}</div>}
                {f.t === "vars" && <div className="var-chips">{f.v.map((x) => <span className="var-chip" key={x}>{x}</span>)}</div>}
              </div>
            ))}
            <button className="btn" style={{ marginTop: "2px" }}>Test this node</button>
          </aside>
        </div>

        <div className="runs">
          <div className="runs-head">Run history <span style={{ color: "var(--line)" }}>·</span> stored in your database — runs survive app restarts</div>
          {RUNS.map((r) => (
            <div key={r.id}>
              <div className="run-row" onClick={() => setOpen((o) => ({ ...o, [r.id]: !o[r.id] }))}>
                <span className={r.ok ? "run-ok" : "run-fail"}>{r.ok ? "✓" : "✕"}</span>
                <span className="r-when">{r.when}</span>
                <span className="r-time">{r.time}</span>
              </div>
              <div className={`run-steps${open[r.id] ? " open" : ""}`}>
                {r.steps.map((s, i) => (
                  <div className="step" key={i}>
                    <b>{s[0]}</b>
                    {s[2] ? <span className="fail-note">{s[1]}</span> : <span>{s[1]}</span>}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
