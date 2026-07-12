import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { Code2, Database, LayoutDashboard, Layers, Plus, RefreshCw, Search, Trash2, Undo2, WandSparkles } from "lucide-react";
import {
  addDataConnection, createDashboard, createDataModel, createDatasetFromApi, createDatasetFromFile, createDatasetFromMongo,
  createWorkspace, deleteDashboard, deleteDataModel, getModels, getSchemaMap, listDashboards,
  listDataConnections, listDataModels, listWorkspaces, reviseDashboard, rollbackDashboard,
  runDashboard, setDashboardLayout, setDashboardTransforms,
} from "../lib/api.js";
import {
  DASHBOARD_REFRESH_OPTIONS,
  createDashboardLayoutPersistence,
  createSerialDashboardQueue,
  dashboardSourceEntries,
  dashboardSummary,
  filterDashboards,
  normalizeDashboardRefreshMs,
  reconcileDashboardWidgets,
  reorderDashboardWidgets,
  resolveDashboardWidgetDrop,
  shouldRunScheduledDashboardRefresh,
} from "../lib/dashboardPresentation.js";

// Dashboards: the AI is the designer, not the renderer. The user describes the dashboard and picks
// the model + data connection(s); the model writes each widget's SQL (validated read-only) and picks
// chart types. Opening/refreshing re-runs the SAVED SQL — no model call. Every widget's SQL is
// viewable (security.md §3: AI-written SQL is shown, never hidden).
const CHART_COLORS = ["#f2b14e", "#82ade8", "#54c08a", "#e06666", "#b58ee8", "#5fc4c9", "#e8a2c0"];
const DASHBOARD_REFRESH_STORAGE_PREFIX = "orrery:dashboard-refresh:";

function storedDashboardRefreshMs(dashboardId) {
  if (!dashboardId || typeof window === "undefined") return 0;
  try {
    return normalizeDashboardRefreshMs(window.localStorage.getItem(`${DASHBOARD_REFRESH_STORAGE_PREFIX}${encodeURIComponent(dashboardId)}`));
  } catch {
    return 0;
  }
}

function persistDashboardRefreshMs(dashboardId, milliseconds) {
  if (!dashboardId || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      `${DASHBOARD_REFRESH_STORAGE_PREFIX}${encodeURIComponent(dashboardId)}`,
      String(normalizeDashboardRefreshMs(milliseconds)),
    );
  } catch {
    // Storage can be unavailable in hardened webviews. The current session still keeps the choice.
  }
}

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
        <button
          className={`icon-btn${showSql ? " on" : ""}`}
          aria-label={`${showSql ? "Hide" : "Show"} SQL for ${widget.title}`}
          aria-pressed={showSql}
          title={`${showSql ? "Hide" : "Show"} the SQL this widget runs`}
          onClick={() => setShowSql((v) => !v)}
        >
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
  const [dashFilter, setDashFilter] = useState("");
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
  const [autoRefreshing, setAutoRefreshing] = useState(false);
  const [refreshMs, setRefreshMs] = useState(0);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);
  const [refreshState, setRefreshState] = useState({ status: "idle", attemptedAt: null, succeededAt: null, error: "" });
  const [layoutStatus, setLayoutStatus] = useState("saved");
  const [layoutError, setLayoutError] = useState("");
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
  const activeIdRef = useRef("");
  const boardRequestRef = useRef(0);
  const boardRef = useRef(null);
  const runQueueRef = useRef(null);
  const layoutPersistenceRef = useRef(null);
  const layoutIntentVersionRef = useRef(0);
  const layoutStatusRef = useRef("saved");
  const specMutationPendingRef = useRef(0);
  const pendingFocusRef = useRef(null);
  const widgetNodesRef = useRef(new Map());
  if (!runQueueRef.current) runQueueRef.current = createSerialDashboardQueue();
  if (!layoutPersistenceRef.current) {
    layoutPersistenceRef.current = createDashboardLayoutPersistence({
      saveLayout: setDashboardLayout,
      loadAuthoritative: async (dashboardId) => {
        const next = await runDashboard(dashboardId);
        const currentWidgets = boardRef.current?.id === dashboardId ? boardRef.current.widgets : [];
        const widgets = reconcileDashboardWidgets(next?.widgets, currentWidgets, false);
        return { ...next, widgets, keys: widgets.map((widget) => widget._clientKey) };
      },
    });
  }

  function commitBoard(next) {
    boardRef.current = next;
    setBoard(next);
  }

  function updateLayoutStatus(status) {
    layoutStatusRef.current = status;
    setLayoutStatus(status);
  }

  async function enqueueDashboardMutation(task) {
    specMutationPendingRef.current += 1;
    try {
      return await runQueueRef.current.enqueue(task);
    } finally {
      specMutationPendingRef.current -= 1;
    }
  }

  function clearActiveBoard() {
    boardRequestRef.current += 1;
    layoutIntentVersionRef.current += 1;
    dragIndex.current = null;
    activeIdRef.current = "";
    boardRef.current = null;
    setActiveId("");
    setBoard(null);
    setLoading(false);
    setAutoRefreshing(false);
    setLastRefreshedAt(null);
    setRefreshState({ status: "idle", attemptedAt: null, succeededAt: null, error: "" });
    updateLayoutStatus("saved");
    setLayoutError("");
  }

  async function load(nextActive) {
    const d = await listDashboards();
    setItems(d.dashboards || []);
    const chosen = nextActive ?? (d.dashboards?.[0]?.id || "");
    if (chosen) await openBoard(chosen);
    else clearActiveBoard();
  }

  useEffect(() => {
    load().catch((e) => setErr(String(e.message || e)));
    getModels().then((m) => { setModels(m.models || []); setModel((m.models || [])[0]?.id || ""); }).catch(() => {});
    listDataConnections().then((c) => setConnections(c.connections || [])).catch(() => {});
    listWorkspaces().then((w) => { setWorkspaces(w.workspaces || []); setWsId((w.workspaces || [])[0]?.id || ""); }).catch(() => {});
  }, []);

  useEffect(() => {
    activeIdRef.current = activeId;
    setAutoRefreshing(false);
    if (!activeId) {
      boardRequestRef.current += 1;
      setLoading(false);
    }
  }, [activeId]);

  useEffect(() => {
    if (!activeId || !refreshMs) return undefined;
    const refreshDashboard = () => {
      if (!shouldRunScheduledDashboardRefresh(document.visibilityState, runQueueRef.current.isBusy())) return;
      requestDashboardRun(activeId, { automatic: true, preserveLayout: true });
    };
    const interval = window.setInterval(refreshDashboard, refreshMs);
    return () => window.clearInterval(interval);
  }, [activeId, refreshMs]);

  useEffect(() => {
    const pending = pendingFocusRef.current;
    if (!pending) return;
    const node = widgetNodesRef.current.get(pending.widgetKey);
    const preferred = node?.querySelector(`[data-reorder-action="${pending.action}"]:not(:disabled)`);
    const fallback = node?.querySelector("[data-reorder-action]:not(:disabled)");
    (preferred || fallback)?.focus();
    pendingFocusRef.current = null;
  }, [board?.widgets]);

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
    const dashboardId = activeId;
    const transforms = editTransforms;
    setBusy(true); setErr("");
    try {
      await enqueueDashboardMutation(() => setDashboardTransforms(dashboardId, transforms));
      setEditTransforms(null);
      await openBoard(dashboardId);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function moveWidget(from, target, focusAction = null) {
    if (specMutationPendingRef.current > 0) return;
    const current = boardRef.current;
    const next = reorderDashboardWidgets(current?.widgets, from, target);
    if (!next) return;
    const dashboardId = activeIdRef.current;
    if (layoutPersistenceRef.current.isBlocked(dashboardId)) {
      updateLayoutStatus("unsaved");
      setLayoutError("Layout is not saved. Refresh the dashboard before rearranging again.");
      return;
    }
    const intentVersion = ++layoutIntentVersionRef.current;
    const desiredKeys = next.widgets.map((widget) => widget._clientKey);
    if (focusAction) {
      pendingFocusRef.current = { widgetKey: current.widgets[from]._clientKey, action: focusAction };
    }
    updateLayoutStatus("saving");
    setLayoutError("");
    commitBoard({ ...current, widgets: next.widgets });
    const outcome = await runQueueRef.current.enqueue(
      () => layoutPersistenceRef.current.save(dashboardId, desiredKeys),
    );
    if (activeIdRef.current !== dashboardId || layoutIntentVersionRef.current !== intentVersion) return;

    if (outcome.status === "saved") {
      if (outcome.authoritative) {
        const { keys: _keys, ...authoritativeBoard } = outcome.authoritative;
        commitBoard(authoritativeBoard);
      }
      updateLayoutStatus("saved");
      setLayoutError("");
      return;
    }
    if (outcome.status === "recovered") {
      const { keys: _keys, ...authoritativeBoard } = outcome.authoritative;
      commitBoard(authoritativeBoard);
      const recoveredAt = Date.now();
      setLastRefreshedAt(recoveredAt);
      setRefreshState({ status: "fresh", attemptedAt: recoveredAt, succeededAt: recoveredAt, error: "" });
      updateLayoutStatus("saved");
      setLayoutError("");
      return;
    }
    if (outcome.status === "conflict") {
      const snapshot = outcome.authoritative;
      if (snapshot) {
        const { keys: _keys, ...authoritativeBoard } = snapshot;
        commitBoard(authoritativeBoard);
      }
      updateLayoutStatus(snapshot ? "error" : "unsaved");
      setLayoutError("Layout was not saved because the dashboard changed. Refresh before rearranging again.");
      return;
    }

    const refreshMessage = String(outcome.refreshError?.message || outcome.refreshError || "authoritative refresh required");
    updateLayoutStatus("unsaved");
    setLayoutError(`Layout could not be confirmed: ${refreshMessage}`);
    const attemptedAt = Date.now();
    setRefreshState((previous) => ({
      status: "failed",
      attemptedAt,
      succeededAt: previous.succeededAt,
      error: `Authoritative layout refresh failed: ${refreshMessage}`,
    }));
  }

  async function onWidgetDrop(targetKey) {
    const dragState = dragIndex.current;
    dragIndex.current = null;
    const current = boardRef.current;
    const move = resolveDashboardWidgetDrop(current?.widgets, dragState, targetKey, activeIdRef.current);
    if (move) await moveWidget(move.from, move.target);
  }

  async function requestDashboardRun(id, { automatic = false, preserveLayout = true } = {}) {
    if (!id) return;
    const request = ++boardRequestRef.current;
    const attemptedAt = Date.now();
    setRefreshState((previous) => ({
      status: "refreshing",
      attemptedAt,
      succeededAt: previous.succeededAt,
      error: "",
    }));
    if (automatic) setAutoRefreshing(true);
    else {
      setAutoRefreshing(false);
      setLoading(true);
    }
    try {
      const result = await runQueueRef.current.enqueue(async () => {
        const next = await runDashboard(id);
        const currentWidgets = boardRef.current?.id === id ? boardRef.current.widgets : [];
        const serverWidgets = reconcileDashboardWidgets(next?.widgets, currentWidgets, false);
        layoutPersistenceRef.current.seed(id, {
          ...next,
          widgets: serverWidgets,
          keys: serverWidgets.map((widget) => widget._clientKey),
        });
        return { next, serverWidgets };
      });
      if (request === boardRequestRef.current && activeIdRef.current === id) {
        const shouldPreserveLayout = preserveLayout && layoutStatusRef.current !== "unsaved";
        const currentWidgets = shouldPreserveLayout && boardRef.current?.id === id
          ? boardRef.current.widgets
          : [];
        const widgets = shouldPreserveLayout
          ? reconcileDashboardWidgets(result.serverWidgets, currentWidgets)
          : result.serverWidgets;
        commitBoard({ ...result.next, widgets });
        const succeededAt = Date.now();
        setLastRefreshedAt(succeededAt);
        setRefreshState({ status: "fresh", attemptedAt, succeededAt, error: "" });
        if (layoutStatusRef.current !== "saving") {
          updateLayoutStatus("saved");
          setLayoutError("");
        }
      }
    } catch (e) {
      if (request === boardRequestRef.current && activeIdRef.current === id) {
        const message = `${automatic ? "Scheduled refresh failed: " : "Refresh failed: "}${String(e.message || e)}`;
        setRefreshState((previous) => ({
          status: "failed",
          attemptedAt,
          succeededAt: previous.succeededAt,
          error: message,
        }));
      }
    } finally {
      if (request === boardRequestRef.current && activeIdRef.current === id) {
        if (automatic) setAutoRefreshing(false);
        else setLoading(false);
      }
    }
  }

  async function openBoard(id) {
    layoutIntentVersionRef.current += 1;
    dragIndex.current = null;
    activeIdRef.current = id;
    boardRef.current = null;
    setErr(""); setActiveId(id); setCreating(false); setBoard(null);
    setRefreshMs(storedDashboardRefreshMs(id));
    setLastRefreshedAt(null);
    setRefreshState({ status: "idle", attemptedAt: null, succeededAt: null, error: "" });
    updateLayoutStatus("saved");
    setLayoutError("");
    await requestDashboardRun(id, { preserveLayout: false });
  }

  async function refreshBoard() {
    await requestDashboardRun(activeIdRef.current, { preserveLayout: true });
  }

  function updateRefreshSchedule(event) {
    const next = normalizeDashboardRefreshMs(event.target.value);
    setRefreshMs(next);
    persistDashboardRefreshMs(activeId, next);
  }

  function beginCreate() {
    clearActiveBoard();
    setCreating(true);
    setStep(1);
    setErr("");
  }

  async function build() {
    if (!desc.trim() || !model || selectedConns.length === 0) return;
    setBusy(true); setErr("");
    try {
      const d = await enqueueDashboardMutation(() => createDashboard(model, selectedConns, desc.trim()));
      setDesc(""); setCreating(false);
      await load(d.id);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function revise() {
    if (!reviseText.trim() || !activeId || !model) return;
    const dashboardId = activeId;
    const instruction = reviseText.trim();
    setBusy(true); setErr("");
    try {
      await enqueueDashboardMutation(() => reviseDashboard(dashboardId, model, instruction));
      setReviseText("");
      await load(dashboardId);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function rollback() {
    if (!activeId) return;
    const dashboardId = activeId;
    setBusy(true); setErr("");
    try {
      await enqueueDashboardMutation(() => rollbackDashboard(dashboardId));
      await load(dashboardId);
    }
    catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function remove() {
    if (!activeId || !window.confirm("Delete this dashboard?")) return;
    const dashboardId = activeId;
    setBusy(true); setErr("");
    try {
      await enqueueDashboardMutation(() => deleteDashboard(dashboardId));
      await load("");
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
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

  async function connectMongo() {
    if (!connUrl.trim() || !connHeaders.trim()) return;  // headers field doubles as the collection name in mongo mode
    setBusy(true); setErr("");
    try {
      await createDatasetFromMongo(connName.trim(), connUrl.trim(), connHeaders.trim(), wsId);
      await refreshConnectionsAndSelect(wsId);
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
  const visibleDashboards = filterDashboards(items, dashFilter);
  const summary = dashboardSummary(board, refreshState);
  const boardSources = dashboardSourceEntries(board, connections);
  const layoutLabel = {
    saved: "Saved",
    saving: "Saving…",
    error: "Save failed",
    unsaved: "Unsaved",
  }[layoutStatus] || "Saved";

  return (
    <section className="view projects-view dashboard-view">
      <aside className="project-side dashboard-side" aria-label="Saved dashboards">
        <div className="dash-library-head">
          <span className="dash-eyebrow"><LayoutDashboard /> AI dashboards</span>
          <h1>Dashboards</h1>
          <p>{items.length} saved {items.length === 1 ? "view" : "views"}</p>
        </div>
        <button className="btn primary project-new" onClick={beginCreate} disabled={busy}>
          <Plus /> New dashboard
        </button>
        <label className="dash-library-search">
          <Search aria-hidden="true" />
          <input
            type="search"
            aria-label="Search saved dashboards"
            placeholder="Search dashboards"
            value={dashFilter}
            onChange={(event) => setDashFilter(event.target.value)}
          />
        </label>
        <div className="project-list project-tree">
          {items.length === 0 && !creating && <div className="convo-empty">Describe a dashboard and a model builds it from your data.</div>}
          {items.length > 0 && visibleDashboards.length === 0 && (
            <div className="convo-empty" role="status">No dashboards match “{dashFilter.trim()}”.</div>
          )}
          {visibleDashboards.map((d) => (
            <div key={d.id} className={`project-node${d.id === activeId ? " active" : ""}`}>
              <button className="project-item" aria-current={d.id === activeId ? "page" : undefined} onClick={() => openBoard(d.id)} disabled={busy}>
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

      <main className="project-main dashboard-main">
        {showCreate ? (
          <div className="dash-create">
            <header className="dash-builder-intro">
              <span className="dash-eyebrow"><WandSparkles /> Dashboard builder</span>
              <h2>Build from your live data</h2>
              <p>Select data sources, describe the questions, and choose a model for the dashboard.</p>
            </header>
            <div className="wiz-steps">
              {[[1, "Data sets"], [2, "Requirements"], [3, "Data model"], [4, "Build"]].map(([n, label]) => (
                <button
                  key={n}
                  className={`wiz-step${step === n ? " on" : ""}${step > n ? " done" : ""}`}
                  aria-current={step === n ? "step" : undefined}
                  disabled={n > step}
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
                      {[["postgres", "Database"], ["file", "CSV / Excel / JSON / JSONL / XML"], ["api", "REST API / Google Sheet"], ["mongo", "MongoDB"]].map(([id, label]) => (
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
                        <input ref={fileRef} type="file" accept=".csv,.tsv,.json,.jsonl,.ndjson,.xml,.xlsx,.xls,.xlsm,text/csv,application/json,text/xml" hidden onChange={connectFile} />
                        <div className="dash-connect-row">
                          <button className="btn primary sm" onClick={() => fileRef.current?.click()} disabled={busy}>{busy ? "Importing..." : "Choose file & import"}</button>
                          <button className="btn ghost sm" onClick={() => setConnectOpen(false)}>Cancel</button>
                          <small>CSV, Excel, or JSON becomes a table in the chosen workspace.</small>
                        </div>
                      </>
                    )}
                    {connMode === "mongo" && (
                      <>
                        <input placeholder="mongodb://user:password@host:27017/mydb  (or mongodb+srv://...)" value={connUrl} onChange={(e) => setConnUrl(e.target.value)} spellCheck={false} />
                        <input placeholder="Collection to import (e.g. orders)" value={connHeaders} onChange={(e) => setConnHeaders(e.target.value)} spellCheck={false} />
                        <div className="dash-connect-row">
                          <button className="btn primary sm" onClick={connectMongo} disabled={busy || !connUrl.trim() || !connHeaders.trim()}>{busy ? "Importing..." : "Import collection"}</button>
                          <button className="btn ghost sm" onClick={() => setConnectOpen(false)}>Cancel</button>
                          <small>Documents become a refreshable table; the URI stays in your OS keychain.</small>
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
                <p className="wiz-hint">Review the selected sources, requirements, and model before building.</p>
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
            <header className="project-head dashboard-commandbar">
              <div className="dash-heading">
                <span className="dash-eyebrow">AI dashboard <em className={`dash-live ${summary.tone}`}>{summary.status}</em></span>
                <div>
                  <h2 className="dash-title">{board?.name || active?.name || ""}</h2>
                  <small className="dash-by">built by {((board?.model || active?.model) || "").split("/").pop()}</small>
                </div>
              </div>
              <div className="grow" />
              <div className="dash-refresh-tools">
                <label className="dash-refresh-control">
                  <span>Auto refresh</span>
                  <select value={refreshMs} onChange={updateRefreshSchedule} aria-label="Automatic dashboard refresh schedule">
                    {DASHBOARD_REFRESH_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <small role="status" aria-live="polite">
                  {refreshState.status === "refreshing"
                    ? "Refreshing now…"
                    : refreshState.status === "failed" && refreshState.attemptedAt
                      ? `Failed ${new Date(refreshState.attemptedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
                    : lastRefreshedAt
                      ? `Last run ${new Date(lastRefreshedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
                      : "Not run yet"}
                </small>
              </div>
              <button className="btn" onClick={refreshBoard} disabled={busy || loading || autoRefreshing}>
                <RefreshCw className={loading || autoRefreshing ? "spin" : ""} /> {loading ? "Refreshing…" : "Refresh"}
              </button>
              {(board?.versions || 0) > 0 && (
                <button className="btn ghost" onClick={rollback} disabled={busy} title="Restore the previous version"><Undo2 /> Roll back</button>
              )}
              <button className="btn ghost" aria-label="Delete dashboard" title="Delete dashboard" onClick={remove} disabled={busy}><Trash2 /></button>
            </header>

            {err && <div className="chat-banner">{err}</div>}
            {layoutError && <div className="chat-banner">{layoutError}</div>}
            {refreshState.status === "failed" && refreshState.error && <div className="chat-banner">{refreshState.error}</div>}
            {loading && <div className="project-muted" style={{ padding: "18px 4px" }}>Running the saved queries…</div>}

            {board && (
              <div className="dash-workspace">
                <div className="dash-canvas">
                  <div className="dash-summary-strip" aria-label="Dashboard summary">
                    <span><b>{summary.widgetCount}</b><small>live widgets</small></span>
                    <span><b>{summary.sourceCount}</b><small>data sources</small></span>
                    <span><b>{summary.transformCount}</b><small>transforms</small></span>
                    <span className={`dash-layout-summary ${layoutStatus}`}><b>{layoutLabel}</b><small>layout</small></span>
                  </div>
                  <div className="dash-transforms">
                <button className="dash-transforms-head" aria-expanded={showTransforms} onClick={() => setShowTransforms((v) => !v)}>
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
                  <div className="dash-grid2">
                {board.widgets.map((w, i) => (
                  <div
                    key={w._clientKey}
                    className={`dash-drag dash-${w.type}`}
                    ref={(node) => {
                      if (node) widgetNodesRef.current.set(w._clientKey, node);
                      else widgetNodesRef.current.delete(w._clientKey);
                    }}
                    draggable={!busy}
                    onDragStart={(event) => {
                      if (busy) return;
                      dragIndex.current = { dashboardId: activeIdRef.current, widgetKey: w._clientKey };
                      event.dataTransfer.effectAllowed = "move";
                    }}
                    onDragEnd={() => { dragIndex.current = null; }}
                    onDragOver={(event) => {
                      if (dragIndex.current?.dashboardId === activeIdRef.current) event.preventDefault();
                    }}
                    onDrop={(event) => { event.preventDefault(); onWidgetDrop(w._clientKey); }}
                    title="Drag to rearrange widgets"
                  >
                    <div className="dash-drag-controls" role="group" aria-label={`Reorder ${w.title}`}>
                      <button type="button" data-reorder-action="earlier" aria-label={`Move ${w.title} earlier`} title="Move earlier" disabled={busy || i === 0} onClick={() => moveWidget(i, i - 1, "earlier")}>↑</button>
                      <button type="button" data-reorder-action="later" aria-label={`Move ${w.title} later`} title="Move later" disabled={busy || i === board.widgets.length - 1} onClick={() => moveWidget(i, i + 1, "later")}>↓</button>
                    </div>
                    <Widget widget={w} />
                  </div>
                ))}
                  </div>
                </div>
                <aside className="dash-insights" aria-label="Dashboard details">
                  <header>
                    <span className="dash-eyebrow"><WandSparkles /> Run overview</span>
                    <h2>Dashboard pulse</h2>
                  </header>
                  <div className={`dash-insight-status ${summary.tone}`} role="status">
                    <span aria-hidden="true" />
                    <div>
                      <b>{summary.status}</b>
                      <small>{summary.detail}</small>
                    </div>
                  </div>
                  <section>
                    <h3><Database /> Data sources</h3>
                    <div className="dash-source-list">
                      {boardSources.length
                        ? boardSources.map((source) => <span key={source.id}>{source.name}</span>)
                        : <small>No named sources reported.</small>}
                    </div>
                  </section>
                </aside>
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
