import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { Code2, Database, LayoutDashboard, Layers, Plus, RefreshCw, Search, Trash2, Undo2, WandSparkles } from "lucide-react";
import {
  addDataConnection, createDashboard, createDataModel, createDatasetFromApi, createDatasetFromFile,
  createWorkspace, deleteDashboard, deleteDataModel, getModels, getSchemaMap, listDashboards,
  listDataConnections, listDataModels, listWorkspaces, reviseDashboard, rollbackDashboard,
  runDashboard, setDashboardLayout, setDashboardTransforms,
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
  const [step, setStep] = useState(1); // new-dashboard wizard: 1 data → 2 requirements → 3 model → 4 build
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
  const [workspaces, setWorkspaces] = useState([]);
  const [wsId, setWsId] = useState("");           // import target workspace
  const [newWsName, setNewWsName] = useState("");
  const [modelsOpen, setModelsOpen] = useState(false);
  const [modelConn, setModelConn] = useState(""); // connection the join editor works on
  const [schemaMap, setSchemaMap] = useState({}); // {table: [columns]}
  const [dataModels, setDataModelsList] = useState([]);
  const [modelDraft, setModelDraft] = useState({ name: "", tables: [], links: [] });
  const [tableFilter, setTableFilter] = useState("");
  const [editTransforms, setEditTransforms] = useState(null); // working copy while editing
  const dragIndex = useRef(null);

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
    listWorkspaces().then((w) => { setWorkspaces(w.workspaces || []); setWsId((w.workspaces || [])[0]?.id || ""); }).catch(() => {});
  }, []);

  async function openModelEditor(cid) {
    setModelConn(cid); setModelsOpen(true); setErr("");
    setModelDraft({ name: "", tables: [], links: [] });
    setTableFilter("");
    try {
      const [sm, dm] = await Promise.all([getSchemaMap(cid), listDataModels(cid)]);
      setSchemaMap(sm.tables || {});
      setDataModelsList(dm.models || []);
    } catch (e) { setErr(String(e.message || e)); }
  }

  // Best-guess join keys when a table is added: customers.id = orders.customer_id (singular/plural
  // tolerant), else any shared column name, else same-named id columns.
  function suggestLink(newTable, existingTables) {
    const cols = schemaMap[newTable] || [];
    const stem = (t) => t.replace(/^ds_/, "").replace(/s$/, "");
    for (const prev of existingTables) {
      const prevCols = schemaMap[prev] || [];
      const fkToPrev = cols.find((c) => c === `${stem(prev)}_id`);
      if (fkToPrev && prevCols.includes("id")) return { left: `${prev}.id`, right: `${newTable}.${fkToPrev}`, type: "left" };
      const fkToNew = prevCols.find((c) => c === `${stem(newTable)}_id`);
      if (fkToNew && cols.includes("id")) return { left: `${prev}.${fkToNew}`, right: `${newTable}.id`, type: "left" };
      const shared = cols.find((c) => c !== "id" && prevCols.includes(c));
      if (shared) return { left: `${prev}.${shared}`, right: `${newTable}.${shared}`, type: "left" };
    }
    const first = existingTables[0];
    return { left: first ? `${first}.${(schemaMap[first] || [])[0] || "id"}` : "", right: `${newTable}.${cols[0] || "id"}`, type: "left" };
  }

  function toggleModelTable(t) {
    setModelDraft((d) => {
      if (d.tables.includes(t)) {
        // removing a table rebuilds the chain with fresh suggestions so links stay consistent
        const tables = d.tables.filter((x) => x !== t);
        const links = tables.slice(1).map((tt, i) => suggestLink(tt, tables.slice(0, i + 1)));
        return { ...d, tables, links };
      }
      const links = d.tables.length ? [...d.links, suggestLink(t, d.tables)] : d.links;
      return { ...d, tables: [...d.tables, t], links };
    });
  }

  function updateModelLink(index, patch) {
    setModelDraft((d) => {
      const links = [...(d.links || [])];
      links[index] = { ...(links[index] || {}), ...patch };
      return { ...d, links };
    });
  }

  async function saveModel() {
    const { name, tables, links } = modelDraft;
    if (!name.trim() || tables.length < 2) return;
    setBusy(true); setErr("");
    try {
      const joins = tables.slice(1).map((t, i) => ({
        table: t,
        left: links[i]?.left || "",
        right: links[i]?.right || "",
        type: links[i]?.type || "left",
      }));
      await createDataModel(modelConn, name.trim(), { base: tables[0], joins });
      setDataModelsList((await listDataModels(modelConn)).models || []);
      setModelDraft({ name: "", tables: [], links: [] });
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function removeModel(id) {
    try { await deleteDataModel(id); setDataModelsList((await listDataModels(modelConn)).models || []); }
    catch (e) { setErr(String(e.message || e)); }
  }

  async function addWorkspace() {
    if (!newWsName.trim()) return;
    try {
      const w = await createWorkspace(newWsName.trim());
      const list = (await listWorkspaces()).workspaces || [];
      setWorkspaces(list); setWsId(w.id); setNewWsName("");
      listDataConnections().then((c) => setConnections(c.connections || [])).catch(() => {});
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function saveTransforms() {
    setBusy(true); setErr("");
    try {
      await setDashboardTransforms(activeId, editTransforms);
      setEditTransforms(null);
      await openBoard(activeId);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function onWidgetDrop(target) {
    const from = dragIndex.current;
    dragIndex.current = null;
    if (from === null || from === target || !board) return;
    const order = board.widgets.map((_w, i) => i);
    order.splice(target, 0, order.splice(from, 1)[0]);
    setBoard((b) => ({ ...b, widgets: order.map((i) => b.widgets[i]) }));  // instant, then persist
    try { await setDashboardLayout(activeId, order); } catch (e) { setErr(String(e.message || e)); }
  }

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
      await createDatasetFromApi(connName.trim(), connUrl.trim(), headers, wsId);
      await refreshConnectionsAndSelect(wsId);
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
      await createDatasetFromFile(connName.trim() || file.name.replace(/\.[^.]+$/, ""), file.name, content, wsId);
      await refreshConnectionsAndSelect(wsId);
    } catch (e2) { setErr(String(e2.message || e2)); } finally { setBusy(false); }
  }

  const active = items.find((d) => d.id === activeId);
  const showCreate = creating || (!items.length && !activeId);
  const schemaTables = Object.keys(schemaMap || {});
  const selectedTables = modelDraft.tables || [];
  const selectedColumns = selectedTables.reduce((sum, table) => sum + ((schemaMap[table] || []).length), 0);
  const visibleSchemaTables = schemaTables.filter((table) => {
    const q = tableFilter.trim().toLowerCase();
    if (!q) return true;
    return table.toLowerCase().includes(q) || (schemaMap[table] || []).some((col) => col.toLowerCase().includes(q));
  });
  const currentModelConnection = connections.find((c) => c.id === modelConn);

  return (
    <section className="view projects-view">
      <aside className="project-side">
        <button className="btn primary project-new" onClick={() => { setCreating(true); setStep(1); setActiveId(""); setBoard(null); setErr(""); }}>
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
            <h2><WandSparkles /> New dashboard</h2>
            <div className="wiz-steps">
              {[[1, "Data sets"], [2, "Requirements"], [3, "Data model"], [4, "Build"]].map(([n, label]) => (
                <button
                  key={n}
                  className={`wiz-step${step === n ? " on" : ""}${step > n ? " done" : ""}`}
                  onClick={() => { if (n < step) setStep(n); }}
                >
                  <span className="wiz-num">{step > n ? "\u2713" : n}</span> {label}
                </button>
              ))}
            </div>

            {step === 1 && (
              <>
                <p className="wiz-hint">Add every data set this dashboard needs: databases, files, APIs, Google Sheets.
                  Pick as many as you want; you connect them into a model in step 3.</p>
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
                      {[["postgres", "Database"], ["file", "CSV / Excel / JSON file"], ["api", "REST API / Google Sheet"]].map(([id, label]) => (
                        <button key={id} className={`dash-mode${connMode === id ? " on" : ""}`} onClick={() => setConnMode(id)}>{label}</button>
                      ))}
                    </div>
                    {connMode !== "postgres" && (
                      <div className="dash-connect-row">
                        <small>Import into workspace:</small>
                        <select value={wsId} onChange={(e) => setWsId(e.target.value)}>
                          {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                        </select>
                        <input style={{ flex: 1 }} placeholder="or new workspace name" value={newWsName} onChange={(e) => setNewWsName(e.target.value)} />
                        <button className="btn ghost sm" onClick={addWorkspace} disabled={!newWsName.trim()}>Create</button>
                      </div>
                    )}
                    <input placeholder={connMode === "file" ? "Dataset name (optional)" : "Name (e.g. warehouse)"} value={connName} onChange={(e) => setConnName(e.target.value)} />
                    {connMode === "postgres" && (
                      <>
                        <input placeholder="postgres://...  |  mysql://...  |  sqlite:///C:/path/data.db" value={connUrl} onChange={(e) => setConnUrl(e.target.value)} spellCheck={false} />
                        <div className="dash-connect-row">
                          <button className="btn primary sm" onClick={connectData} disabled={busy || !connUrl.trim()}>{busy ? "Connecting..." : "Connect"}</button>
                          <button className="btn ghost sm" onClick={() => setConnectOpen(false)}>Cancel</button>
                          <small>PostgreSQL, MySQL/MariaDB, or SQLite. Stored only in your OS keychain; queried read-only.</small>
                        </div>
                      </>
                    )}
                    {connMode === "file" && (
                      <>
                        <input ref={fileRef} type="file" accept=".csv,.tsv,.json,.xlsx,.xls,.xlsm,text/csv,application/json" hidden onChange={connectFile} />
                        <div className="dash-connect-row">
                          <button className="btn primary sm" onClick={() => fileRef.current?.click()} disabled={busy}>{busy ? "Importing..." : "Choose file & import"}</button>
                          <button className="btn ghost sm" onClick={() => setConnectOpen(false)}>Cancel</button>
                          <small>CSV, Excel, or JSON becomes a table in the chosen workspace.</small>
                        </div>
                      </>
                    )}
                    {connMode === "api" && (
                      <>
                        <input placeholder="https://api.example.com/v1/orders  or a shared Google Sheets link" value={connUrl} onChange={(e) => setConnUrl(e.target.value)} spellCheck={false} />
                        <textarea
                          className="dash-connect-headers" rows={2} spellCheck={false}
                          placeholder={"Auth headers if needed (one per line):\nAuthorization: Bearer sk-..."}
                          value={connHeaders} onChange={(e) => setConnHeaders(e.target.value)}
                        />
                        <div className="dash-connect-row">
                          <button className="btn primary sm" onClick={connectApi} disabled={busy || !connUrl.trim()}>{busy ? "Fetching..." : "Fetch & import"}</button>
                          <button className="btn ghost sm" onClick={() => setConnectOpen(false)}>Cancel</button>
                          <small>JSON records or a link-shared Google Sheet become a refreshable table; headers stay in your keychain.</small>
                        </div>
                      </>
                    )}
                  </div>
                ) : (
                  <button className="btn ghost sm dash-connect-btn" onClick={() => setConnectOpen(true)}><Plus /> Add a data set</button>
                )}
                <div className="wiz-nav">
                  <span className="wiz-count">{selectedConns.length} data source(s) selected</span>
                  <button className="btn primary" disabled={!selectedConns.length} onClick={() => setStep(2)}>Continue</button>
                </div>
              </>
            )}

            {step === 2 && (
              <>
                <p className="wiz-hint">Define the requirements: what questions must this dashboard answer,
                  which numbers matter, and how you want them broken down.</p>
                <textarea
                  rows={6} value={desc} onChange={(e) => setDesc(e.target.value)}
                  placeholder={"e.g.\n- Total revenue and month-over-month growth\n- Revenue by customer and by product\n- Orders trend over the last 12 months\n- A table of the 20 most recent orders"}
                />
                <div className="wiz-nav">
                  <button className="btn ghost" onClick={() => setStep(1)}>Back</button>
                  <button className="btn primary" disabled={!desc.trim()} onClick={() => { openModelEditor(selectedConns[0] || connections[0]?.id); setStep(3); }}>Continue</button>
                </div>
              </>
            )}

            {step === 3 && (
              <>
                <p className="wiz-hint">Connect related tables into a model: the dashboard treats each model as one
                  pre-joined dataset. Skip this if your data is a single table.</p>
                <div className="dash-model-editor">
                <div className="dash-model-head">
                  <div>
                    <b>Data model builder</b>
                    <small>Build one reusable dataset from related tables on this connection.</small>
                  </div>
                  <select value={modelConn} onChange={(e) => openModelEditor(e.target.value)}>
                    {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div className="dm-summary">
                  <span><b>{schemaTables.length}</b><small>tables in {currentModelConnection?.name || "connection"}</small></span>
                  <span><b>{selectedTables.length}</b><small>selected tables</small></span>
                  <span><b>{selectedColumns}</b><small>available columns</small></span>
                </div>
                <div className="dm-workbench">
                  <aside className="dm-picker">
                    <label className="dm-search">
                      <Search />
                      <input value={tableFilter} onChange={(e) => setTableFilter(e.target.value)} placeholder="Search tables or columns" />
                    </label>
                    <div className="dm-table-list">
                      {visibleSchemaTables.length === 0 && <div className="dm-empty small">No matching tables.</div>}
                      {visibleSchemaTables.map((t) => {
                        const selected = selectedTables.includes(t);
                        return (
                          <button key={t} className={`dm-table-option${selected ? " on" : ""}`} onClick={() => toggleModelTable(t)}>
                            <span>
                              <b>{t.replace(/^ds_/, "")}</b>
                              <small>{(schemaMap[t] || []).length} columns</small>
                            </span>
                            <em>{selected ? "Selected" : "Add"}</em>
                          </button>
                        );
                      })}
                    </div>
                  </aside>
                  <div className="dm-builder">
                    <div className="dm-builder-head">
                      <span>
                        <b>{selectedTables.length ? "Selected model tables" : "No tables selected"}</b>
                        <small>{selectedTables.length > 1 ? "Adjust each join row below before saving." : "Pick at least two related tables."}</small>
                      </span>
                    </div>
                    {selectedTables.length === 0 ? (
                      <div className="dm-empty">Choose tables from the left. Orrery will suggest joins, and you can edit every key before saving.</div>
                    ) : (
                      <>
                        <div className="dm-selected-grid">
                          {selectedTables.map((t, i) => {
                            const link = i > 0 ? modelDraft.links[i - 1] : null;
                            const next = modelDraft.links[i];
                            const keyCols = new Set(
                              [link?.left, link?.right, next?.left, next?.right]
                                .filter(Boolean).filter((r) => r.startsWith(`${t}.`)).map((r) => r.slice(t.length + 1)),
                            );
                            return (
                              <div key={t} className="dm-card">
                                <div className="dm-card-head">
                                  <span>
                                    {t.replace(/^ds_/, "")}
                                    {i === 0 && <em>base</em>}
                                  </span>
                                  <button title="Remove table" onClick={() => toggleModelTable(t)}>x</button>
                                </div>
                                <div className="dm-cols">
                                  {(schemaMap[t] || []).slice(0, 12).map((c) => (
                                    <span key={c} className={`dm-col${keyCols.has(c) ? " key" : ""}`}>{c}</span>
                                  ))}
                                  {(schemaMap[t] || []).length > 12 && <span className="dm-col more">+{(schemaMap[t] || []).length - 12} more</span>}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                        {selectedTables.length > 1 && (
                          <div className="dm-link-editor">
                            {selectedTables.slice(1).map((t, offset) => {
                              const link = modelDraft.links[offset] || {};
                              const leftOptions = selectedTables.slice(0, offset + 1).flatMap((pt) => (schemaMap[pt] || []).map((c) => `${pt}.${c}`));
                              const rightOptions = (schemaMap[t] || []).map((c) => `${t}.${c}`);
                              return (
                                <div key={`${t}-${offset}`} className="dm-link-row">
                                  <div className="dm-link-label">
                                    <Layers />
                                    <span>
                                      <b>Join {t.replace(/^ds_/, "")}</b>
                                      <small>to any table already selected</small>
                                    </span>
                                  </div>
                                  <select value={link.type || "left"} onChange={(e) => updateModelLink(offset, { type: e.target.value })}>
                                    <option value="left">Left join</option>
                                    <option value="inner">Inner join</option>
                                  </select>
                                  <select value={link.left || ""} onChange={(e) => updateModelLink(offset, { left: e.target.value })}>
                                    {leftOptions.map((ref) => <option key={ref} value={ref}>{ref.replace(/^ds_/, "")}</option>)}
                                  </select>
                                  <span className="dm-eq">=</span>
                                  <select value={link.right || ""} onChange={(e) => updateModelLink(offset, { right: e.target.value })}>
                                    {rightOptions.map((ref) => <option key={ref} value={ref}>{ref.replace(/^ds_/, "")}</option>)}
                                  </select>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
                {dataModels.length > 0 && (
                  <div className="dash-model-list">
                    {dataModels.map((m) => (
                      <span key={m.id} className="dash-model-chip">
                        <Layers /> {m.name}
                        <button title="Delete model" onClick={() => removeModel(m.id)}>×</button>
                      </span>
                    ))}
                  </div>
                )}
                <div className="dash-connect-row">
                  <input style={{ flex: 1 }} placeholder="Model name (e.g. Orders with customers)" value={modelDraft.name} onChange={(e) => setModelDraft((d) => ({ ...d, name: e.target.value }))} />
                  <button className="btn primary sm" onClick={saveModel}
                    disabled={busy || !modelDraft.name.trim() || modelDraft.tables.length < 2}>
                    {busy ? "Validating..." : "Save model"}
                  </button>
                  <small className="dm-hint">Validated against the live schema; nothing is written to your data.</small>
                </div>
                </div>
                <div className="wiz-nav">
                  <button className="btn ghost" onClick={() => setStep(2)}>Back</button>
                  <button className="btn primary" onClick={() => setStep(4)}>{dataModels.length ? "Continue" : "Skip (no joins needed)"}</button>
                </div>
              </>
            )}

            {step === 4 && (
              <>
                <div className="wiz-summary">
                  <span><b>{selectedConns.length}</b><small>data source(s)</small></span>
                  <span><b>{dataModels.length}</b><small>data model(s)</small></span>
                  <span><b>{desc.trim().split(/\n+/).filter(Boolean).length}</b><small>requirement line(s)</small></span>
                </div>
                <label className="dash-form-label">Built by</label>
                <select value={model} onChange={(e) => setModel(e.target.value)}>
                  {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
                <p className="wiz-hint">The model designs every widget from your requirements and models. All SQL stays
                  visible per widget, and refreshes re-run the saved queries with no model cost.</p>
                <div className="wiz-nav">
                  <button className="btn ghost" onClick={() => setStep(3)}>Back</button>
                  <button className="btn primary" onClick={build} disabled={busy || !desc.trim() || !model || !selectedConns.length}>
                    {busy ? "Designing..." : "Build dashboard"}
                  </button>
                </div>
              </>
            )}
            {err && <div className="chat-banner">{err}</div>}
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

            {board && (
              <div className="dash-transforms">
                <button className="dash-transforms-head" onClick={() => setShowTransforms((v) => !v)}>
                  <Layers /> Transforms ({(board.transforms || []).length}) — prepared datasets widgets build on
                  <span className="pill-caret">{showTransforms ? "▴" : "▾"}</span>
                </button>
                {showTransforms && editTransforms === null && (
                  <>
                    {(board.transforms || []).map((t) => (
                      <div key={t.name} className="dash-transform">
                        <div className="dash-transform-head">
                          <code>{t.name}</code>
                          <small>{t.description || "prepared dataset"}</small>
                        </div>
                        <pre className="dash-sql">{t.sql}</pre>
                      </div>
                    ))}
                    <div className="dash-transform-actions">
                      <button className="btn ghost sm" onClick={() => setEditTransforms((board.transforms || []).map((t) => ({ ...t })))}>
                        {(board.transforms || []).length ? "Edit transforms" : "Add a transform"}
                      </button>
                    </div>
                  </>
                )}
                {showTransforms && editTransforms !== null && (
                  <div className="dash-transform-edit">
                    {editTransforms.map((t, i) => (
                      <div key={i} className="dash-transform">
                        <div className="dash-transform-head">
                          <input className="dash-tname" placeholder="name (snake_case)" value={t.name}
                            onChange={(e) => setEditTransforms((p) => p.map((x, k) => (k === i ? { ...x, name: e.target.value } : x)))} />
                          <select value={t.connection_id || board.connections[0]}
                            onChange={(e) => setEditTransforms((p) => p.map((x, k) => (k === i ? { ...x, connection_id: e.target.value } : x)))}>
                            {board.connections.map((cid) => <option key={cid} value={cid}>{connections.find((c) => c.id === cid)?.name || "connection"}</option>)}
                          </select>
                          <button className="icon-btn" title="Remove" onClick={() => setEditTransforms((p) => p.filter((_x, k) => k !== i))}>×</button>
                        </div>
                        <textarea className="dash-tsql" rows={3} spellCheck={false} placeholder="ONE read-only SELECT that cleans/joins/reshapes data"
                          value={t.sql} onChange={(e) => setEditTransforms((p) => p.map((x, k) => (k === i ? { ...x, sql: e.target.value } : x)))} />
                      </div>
                    ))}
                    <div className="dash-transform-actions">
                      <button className="btn ghost sm" onClick={() => setEditTransforms((p) => [...p, { name: "", connection_id: board.connections[0], sql: "", description: "" }])}>+ Add</button>
                      <button className="btn primary sm" onClick={saveTransforms} disabled={busy}>{busy ? "Validating…" : "Save transforms"}</button>
                      <button className="btn ghost sm" onClick={() => setEditTransforms(null)}>Cancel</button>
                      <small>Each transform must be a single read-only SELECT — validated on save.</small>
                    </div>
                  </div>
                )}
              </div>
            )}

            {board && (
              <div className="dash-grid2">
                {board.widgets.map((w, i) => (
                  <div
                    key={`${w.title}-${i}`}
                    className="dash-drag"
                    draggable
                    onDragStart={() => { dragIndex.current = i; }}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => onWidgetDrop(i)}
                    title="Drag to rearrange — the layout is saved"
                  >
                    <Widget widget={w} />
                  </div>
                ))}
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
