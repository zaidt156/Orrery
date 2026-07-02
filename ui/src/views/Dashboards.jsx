import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { Code2, Database, LayoutDashboard, Layers, Plus, RefreshCw, Trash2, Undo2, WandSparkles } from "lucide-react";
import {
  addDataConnection, createDashboard, createDatasetFromApi, createDatasetFromFile, deleteDashboard,
  getModels, listDashboards, listDataConnections, reviseDashboard, rollbackDashboard, runDashboard,
} from "../lib/api.js";

// Dashboards: the AI is the designer, not the renderer. The user describes the dashboard and picks
// the model + data connection(s); the model writes each widget's SQL (validated read-only) and picks
// chart types. Opening/refreshing re-runs the SAVED SQL — no model call. Every widget's SQL is
// viewable (security.md §3: AI-written SQL is shown, never hidden).
const CHART_COLORS = ["#f2b14e", "#82ade8", "#54c08a", "#e06666", "#b58ee8", "#5fc4c9", "#e8a2c0"];

function chartOption(widget) {
  const cols = widget.columns || [];
  const rows = widget.rows || [];
  const xi = Math.max(0, cols.indexOf(widget.x));
  let yi = cols.indexOf(widget.y);
  if (yi < 0) yi = cols.length > 1 ? (xi === 0 ? 1 : 0) : 0;
  const labels = rows.map((r) => String(r[xi]));
  const values = rows.map((r) => Number(r[yi]) || 0);
  const base = {
    color: CHART_COLORS,
    textStyle: { fontFamily: "inherit" },
    tooltip: { trigger: widget.type === "pie" ? "item" : "axis" },
    grid: { left: 46, right: 14, top: 18, bottom: 32 },
  };
  if (widget.type === "pie") {
    return {
      ...base,
      series: [{
        type: "pie", radius: ["38%", "72%"],
        label: { color: "#9aa3b5", fontSize: 10 },
        data: rows.map((r) => ({ name: String(r[xi]), value: Number(r[yi]) || 0 })),
      }],
    };
  }
  return {
    ...base,
    xAxis: { type: "category", data: labels, axisLabel: { color: "#9aa3b5", fontSize: 10 } },
    yAxis: { type: "value", axisLabel: { color: "#9aa3b5", fontSize: 10 }, splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } } },
    series: [{ type: widget.type === "line" ? "line" : "bar", data: values, smooth: true }],
  };
}

function Chart({ widget }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current) return undefined;
    const chart = echarts.init(ref.current, null, { renderer: "canvas" });
    chart.setOption(chartOption(widget));
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [widget]);
  return <div className="dash-chart" ref={ref} />;
}

function StatWidget({ widget }) {
  const cols = widget.columns || [];
  const row = (widget.rows || [])[0] || [];
  let vi = row.findIndex((c) => typeof c === "number");
  if (vi < 0) vi = 0;
  const value = row[vi];
  const shown = typeof value === "number"
    ? (Math.abs(value) >= 1000 ? value.toLocaleString() : String(Math.round(value * 100) / 100))
    : String(value ?? "—");
  return (
    <div className="dash-stat">
      <b>{shown}</b>
      <small>{cols[vi] || ""}</small>
    </div>
  );
}

function TableWidget({ widget }) {
  const cols = widget.columns || [];
  const rows = (widget.rows || []).slice(0, 50);
  return (
    <div className="dash-table">
      <table>
        <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{String(c ?? "")}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

function Widget({ widget }) {
  const [showSql, setShowSql] = useState(false);
  return (
    <div className={`dash-widget dash-${widget.type}`}>
      <div className="dash-widget-head">
        <span className="dash-widget-title">{widget.title}</span>
        <span className="dash-widget-src" title={`Queries: ${widget.connection || "database"}`}><Database />{widget.connection || ""}</span>
        <button className={`icon-btn${showSql ? " on" : ""}`} title="Show the SQL this widget runs" onClick={() => setShowSql((v) => !v)}>
          <Code2 />
        </button>
      </div>
      {showSql && <pre className="dash-sql">{widget.sql}</pre>}
      {widget.error ? (
        <div className="dash-error">{widget.error}</div>
      ) : widget.type === "stat" ? (
        <StatWidget widget={widget} />
      ) : widget.type === "table" ? (
        <TableWidget widget={widget} />
      ) : (
        <Chart widget={widget} />
      )}
    </div>
  );
}

export default function Dashboards() {
  const [items, setItems] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [board, setBoard] = useState(null); // run result (widgets with live data)
  const [models, setModels] = useState([]);
  const [connections, setConnections] = useState([]);
  const [creating, setCreating] = useState(false);
  const [desc, setDesc] = useState("");
  const [model, setModel] = useState("");
  const [selectedConns, setSelectedConns] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [reviseText, setReviseText] = useState("");
  const [connectOpen, setConnectOpen] = useState(false);
  const [connMode, setConnMode] = useState("postgres"); // postgres | file | api
  const [connName, setConnName] = useState("");
  const [connUrl, setConnUrl] = useState("");
  const [connHeaders, setConnHeaders] = useState("");
  const [showTransforms, setShowTransforms] = useState(false);
  const fileRef = useRef(null);

  async function load(nextActive) {
    const d = await listDashboards();
    setItems(d.dashboards || []);
    const chosen = nextActive ?? (d.dashboards?.[0]?.id || "");
    if (chosen) await openBoard(chosen);
    else { setActiveId(""); setBoard(null); }
  }

  useEffect(() => {
    load().catch((e) => setErr(String(e.message || e)));
    getModels().then((m) => { setModels(m.models || []); setModel((m.models || [])[0]?.id || ""); }).catch(() => {});
    listDataConnections().then((c) => setConnections(c.connections || [])).catch(() => {});
  }, []);

  async function openBoard(id) {
    setErr(""); setActiveId(id); setCreating(false); setLoading(true); setBoard(null);
    try { setBoard(await runDashboard(id)); }
    catch (e) { setErr(String(e.message || e)); }
    finally { setLoading(false); }
  }

  async function build() {
    if (!desc.trim() || !model || selectedConns.length === 0) return;
    setBusy(true); setErr("");
    try {
      const d = await createDashboard(model, selectedConns, desc.trim());
      setDesc(""); setCreating(false);
      await load(d.id);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function revise() {
    if (!reviseText.trim() || !activeId || !model) return;
    setBusy(true); setErr("");
    try {
      await reviseDashboard(activeId, model, reviseText.trim());
      setReviseText("");
      await load(activeId);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function rollback() {
    if (!activeId) return;
    setBusy(true); setErr("");
    try { await rollbackDashboard(activeId); await load(activeId); }
    catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function remove() {
    if (!activeId || !window.confirm("Delete this dashboard?")) return;
    try { await deleteDashboard(activeId); await load(""); } catch (e) { setErr(String(e.message || e)); }
  }

  function toggleConn(id) {
    setSelectedConns((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }

  async function refreshConnectionsAndSelect(preferId) {
    const c = await listDataConnections();
    setConnections(c.connections || []);
    const target = preferId || (c.connections || []).find((x) => x.kind === "datasets")?.id;
    if (target) setSelectedConns((p) => (p.includes(target) ? p : [...p, target]));
    setConnName(""); setConnUrl(""); setConnHeaders(""); setConnectOpen(false);
  }

  async function connectData() {
    if (!connUrl.trim()) return;
    setBusy(true); setErr("");
    try {
      const created = await addDataConnection(connName.trim() || "database", connUrl.trim());
      await refreshConnectionsAndSelect(created.id);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function connectApi() {
    if (!connUrl.trim()) return;
    setBusy(true); setErr("");
    try {
      const headers = {};
      for (const line of connHeaders.split("\n")) {
        const i = line.indexOf(":") >= 0 ? line.indexOf(":") : line.indexOf("=");
        if (i > 0) headers[line.slice(0, i).trim()] = line.slice(i + 1).trim();
      }
      await createDatasetFromApi(connName.trim(), connUrl.trim(), headers);
      await refreshConnectionsAndSelect();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function connectFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true); setErr("");
    try {
      const isExcel = /\.(xlsx|xls|xlsm)$/i.test(file.name);
      let content;
      if (isExcel) {
        const bytes = new Uint8Array(await file.arrayBuffer());
        let bin = "";
        for (let o = 0; o < bytes.length; o += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(o, o + 0x8000));
        content = btoa(bin);
      } else {
        content = await file.text();
      }
      await createDatasetFromFile(connName.trim() || file.name.replace(/\.[^.]+$/, ""), file.name, content);
      await refreshConnectionsAndSelect();
    } catch (e2) { setErr(String(e2.message || e2)); } finally { setBusy(false); }
  }

  const active = items.find((d) => d.id === activeId);
  const showCreate = creating || (!items.length && !activeId);

  return (
    <section className="view projects-view">
      <aside className="project-side">
        <button className="btn primary project-new" onClick={() => { setCreating(true); setActiveId(""); setBoard(null); setErr(""); }}>
          <Plus /> New dashboard
        </button>
        <div className="project-list project-tree">
          {items.length === 0 && !creating && <div className="convo-empty">Describe a dashboard and a model builds it from your data.</div>}
          {items.map((d) => (
            <div key={d.id} className={`project-node${d.id === activeId ? " active" : ""}`}>
              <button className="project-item" onClick={() => openBoard(d.id)}>
                <LayoutDashboard />
                <span>
                  <b>{d.name}</b>
                  <small>{d.widgets.length} widgets · {(d.model || "").split("/").pop()}</small>
                </span>
              </button>
            </div>
          ))}
        </div>
      </aside>

      <main className="project-main">
        {showCreate ? (
          <div className="dash-create">
            <h2><WandSparkles /> Describe your dashboard</h2>
            <p>Pick the data it reads, the model that designs it, and say what you want to see. The model
              writes read-only SQL (always visible per widget); refreshes re-run the saved queries with
              no model cost.</p>
            <label className="dash-form-label">Data connections (pick one or more)</label>
            {connections.length === 0 && !connectOpen && (
              <div className="project-muted">No data connections yet — connect one below.</div>
            )}
            {connections.length > 0 && (
              <div className="dash-conn-list">
                {connections.map((c) => (
                  <label key={c.id} className={`dash-conn${selectedConns.includes(c.id) ? " on" : ""}`}>
                    <input type="checkbox" checked={selectedConns.includes(c.id)} onChange={() => toggleConn(c.id)} />
                    <Database /> {c.name} <small>{c.display}</small>
                  </label>
                ))}
              </div>
            )}
            {connectOpen ? (
              <div className="dash-connect-form">
                <div className="dash-connect-modes">
                  {[["postgres", "PostgreSQL"], ["file", "CSV / Excel file"], ["api", "REST API (JSON)"]].map(([id, label]) => (
                    <button key={id} className={`dash-mode${connMode === id ? " on" : ""}`} onClick={() => setConnMode(id)}>{label}</button>
                  ))}
                </div>
                <input placeholder={connMode === "file" ? "Dataset name (optional — file name is used)" : "Name (e.g. warehouse)"} value={connName} onChange={(e) => setConnName(e.target.value)} />
                {connMode === "postgres" && (
                  <>
                    <input placeholder="postgres://user:password@host:5432/dbname" value={connUrl} onChange={(e) => setConnUrl(e.target.value)} spellCheck={false} />
                    <div className="dash-connect-row">
                      <button className="btn primary sm" onClick={connectData} disabled={busy || !connUrl.trim()}>{busy ? "Connecting…" : "Connect"}</button>
                      <button className="btn ghost sm" onClick={() => setConnectOpen(false)}>Cancel</button>
                      <small>The connection string is stored only in your OS keychain.</small>
                    </div>
                  </>
                )}
                {connMode === "file" && (
                  <>
                    <input ref={fileRef} type="file" accept=".csv,.tsv,.xlsx,.xls,.xlsm,text/csv" hidden onChange={connectFile} />
                    <div className="dash-connect-row">
                      <button className="btn primary sm" onClick={() => fileRef.current?.click()} disabled={busy}>{busy ? "Importing…" : "Choose file & import"}</button>
                      <button className="btn ghost sm" onClick={() => setConnectOpen(false)}>Cancel</button>
                      <small>Becomes a table under “Workspace datasets” — dashboards query it like a database.</small>
                    </div>
                  </>
                )}
                {connMode === "api" && (
                  <>
                    <input placeholder="https://api.example.com/v1/orders" value={connUrl} onChange={(e) => setConnUrl(e.target.value)} spellCheck={false} />
                    <textarea
                      className="dash-connect-headers" rows={2} spellCheck={false}
                      placeholder={"Auth headers if needed (one per line):\nAuthorization: Bearer sk-..."}
                      value={connHeaders} onChange={(e) => setConnHeaders(e.target.value)}
                    />
                    <div className="dash-connect-row">
                      <button className="btn primary sm" onClick={connectApi} disabled={busy || !connUrl.trim()}>{busy ? "Fetching…" : "Fetch & import"}</button>
                      <button className="btn ghost sm" onClick={() => setConnectOpen(false)}>Cancel</button>
                      <small>JSON records become a refreshable table; headers stay in your OS keychain.</small>
                    </div>
                  </>
                )}
              </div>
            ) : (
              <button className="btn ghost sm dash-connect-btn" onClick={() => setConnectOpen(true)}><Plus /> Connect new data source</button>
            )}
            <label className="dash-form-label">Built by</label>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
            <label className="dash-form-label">What should it show?</label>
            <textarea
              rows={3} value={desc} onChange={(e) => setDesc(e.target.value)}
              placeholder="e.g. Revenue overview: monthly totals, top products, active customers, and a table of the latest orders"
            />
            {err && <div className="chat-banner">{err}</div>}
            <button className="btn primary" onClick={build} disabled={busy || !desc.trim() || !model || !selectedConns.length}>
              {busy ? "Designing…" : "Build dashboard"}
            </button>
          </div>
        ) : (
          <>
            <div className="project-head">
              <span className="dash-title">{board?.name || active?.name || ""}</span>
              <small className="dash-by">built by {((board?.model || active?.model) || "").split("/").pop()}</small>
              <div className="grow" />
              <button className="btn" onClick={() => openBoard(activeId)} disabled={loading}><RefreshCw /> Refresh</button>
              {(board?.versions || 0) > 0 && (
                <button className="btn ghost" onClick={rollback} disabled={busy} title="Restore the previous version"><Undo2 /> Roll back</button>
              )}
              <button className="btn ghost" onClick={remove} disabled={busy}><Trash2 /></button>
            </div>

            {err && <div className="chat-banner">{err}</div>}
            {loading && <div className="project-muted" style={{ padding: "18px 4px" }}>Running the saved queries…</div>}

            {board && (board.transforms?.length || 0) > 0 && (
              <div className="dash-transforms">
                <button className="dash-transforms-head" onClick={() => setShowTransforms((v) => !v)}>
                  <Layers /> Transforms ({board.transforms.length}) — prepared datasets widgets build on
                  <span className="pill-caret">{showTransforms ? "▴" : "▾"}</span>
                </button>
                {showTransforms && board.transforms.map((t) => (
                  <div key={t.name} className="dash-transform">
                    <div className="dash-transform-head">
                      <code>{t.name}</code>
                      <small>{t.description || "prepared dataset"}</small>
                    </div>
                    <pre className="dash-sql">{t.sql}</pre>
                  </div>
                ))}
              </div>
            )}

            {board && (
              <div className="dash-grid2">
                {board.widgets.map((w, i) => <Widget key={`${w.title}-${i}`} widget={w} />)}
              </div>
            )}

            <div className="dash-revise">
              <WandSparkles />
              <input
                value={reviseText}
                onChange={(e) => setReviseText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") revise(); }}
                placeholder='Revise with AI — e.g. "add a widget with weekly signups"'
              />
              <select value={model} onChange={(e) => setModel(e.target.value)} title="Model that applies the revision">
                {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
              <button className="btn" onClick={revise} disabled={busy || !reviseText.trim()}>{busy ? "Working…" : "Apply"}</button>
            </div>
          </>
        )}
      </main>
    </section>
  );
}
