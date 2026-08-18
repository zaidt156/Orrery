import { useState, useRef, useLayoutEffect, useCallback, useEffect } from "react";

import {
  createWorkflow, deleteWorkflow, getWorkflow, getWorkflowNodes, getWorkflowRun,
  getWorkflowRuns, getWorkflows, runWorkflow, updateWorkflow,
} from "../lib/api.js";

// This screen used to be a mockup: a fixed list of workflows, a fixed node palette, and invented
// run history. Everything below now comes from the Workflow API, so what you see is what the
// database and the node registry actually contain.

// Node categories are a backend concept (registry.py: ai | data | code | net | logic | tools).
// The colours and the `k-*` classes are this screen's presentation of them.
const CATEGORY_STYLE = {
  ai: { color: "var(--amber)", cls: "k-ai", label: "AI" },
  data: { color: "#7FD4C0", cls: "k-data", label: "Data" },
  code: { color: "#C49DF0", cls: "k-logic", label: "Code" },
  net: { color: "#7FD4C0", cls: "k-data", label: "Net" },
  logic: { color: "#C49DF0", cls: "k-logic", label: "Logic" },
  tools: { color: "var(--ice)", cls: "k-trigger", label: "Tools" },
};

const styleFor = (category) => CATEGORY_STYLE[category] || CATEGORY_STYLE.logic;

// A saved spec does not have to carry positions, so lay out anything without one on a grid.
// Editing positions belongs to the dedicated editing workspace, which does not exist yet.
const COL = 222;
const ROW = 150;
const layout = (nodes) => nodes.map((n, i) => ({
  ...n,
  left: (n.position?.left ?? 170) + (n.position ? 0 : (i % 4) * COL),
  top: (n.position?.top ?? 118) + (n.position ? 0 : Math.floor(i / 4) * ROW),
}));

function relative(iso) {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, (Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return new Date(then).toLocaleDateString();
}

function duration(run) {
  if (!run.started_at || !run.finished_at) return "";
  const ms = Date.parse(run.finished_at) - Date.parse(run.started_at);
  return Number.isNaN(ms) ? "" : `${(ms / 1000).toFixed(1)}s`;
}

export default function Automations() {
  const [catalog, setCatalog] = useState([]);
  const [workflows, setWorkflows] = useState(null);
  const [activeId, setActiveId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [runs, setRuns] = useState([]);
  const [openRun, setOpenRun] = useState({});
  const [runSteps, setRunSteps] = useState({});
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [paths, setPaths] = useState([]);
  const canvasRef = useRef(null);
  const nodeRefs = useRef({});

  const loadWorkflows = useCallback(async (preferId) => {
    const body = await getWorkflows().catch(() => ({ workflows: [] }));
    const list = body.workflows || [];
    setWorkflows(list);
    setActiveId((current) => preferId || current || list[0]?.id || null);
    return list;
  }, []);

  useEffect(() => {
    getWorkflowNodes().then((b) => setCatalog(b.nodes || [])).catch(() => setCatalog([]));
    loadWorkflows();
  }, [loadWorkflows]);

  // Everything below the sidebar depends on which workflow is selected.
  useEffect(() => {
    if (!activeId) { setDetail(null); setRuns([]); return undefined; }
    let live = true;
    setOpenRun({});
    setRunSteps({});
    Promise.all([
      getWorkflow(activeId).catch(() => null),
      getWorkflowRuns(activeId).catch(() => ({ runs: [] })),
    ]).then(([wf, runBody]) => {
      if (!live) return;
      setDetail(wf);
      setRuns(runBody.runs || []);
      setSelected((wf?.spec?.nodes || [])[0]?.id || null);
    });
    return () => { live = false; };
  }, [activeId]);

  const nodes = layout(detail?.spec?.nodes || []);
  const edges = (detail?.spec?.edges || []).map((e) => [e.source, e.target]);

  const drawEdges = useCallback(() => {
    setPaths(edges.map(([a, b]) => {
      const ea = nodeRefs.current[a];
      const eb = nodeRefs.current[b];
      if (!ea || !eb) return "";
      const x1 = ea.offsetLeft + ea.offsetWidth;
      const y1 = ea.offsetTop + ea.offsetHeight / 2;
      const x2 = eb.offsetLeft;
      const y2 = eb.offsetTop + eb.offsetHeight / 2;
      const dx = Math.max(36, (x2 - x1) / 2);
      return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    }));
    // edges are derived from the spec, so this must re-run whenever the spec does
  }, [JSON.stringify(edges)]);

  useLayoutEffect(() => {
    drawEdges();
    const t = setTimeout(drawEdges, 250); // recompute after fonts settle
    window.addEventListener("resize", drawEdges);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", drawEdges);
    };
  }, [drawEdges]);

  const act = async (fn) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e?.message || "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  const onNew = () => act(async () => {
    const created = await createWorkflow("New workflow");
    await loadWorkflows(created.id);
  });

  const onRun = () => act(async () => {
    await runWorkflow(activeId);
    setRuns((await getWorkflowRuns(activeId)).runs || []);
  });

  const onTogglePause = () => act(async () => {
    const updated = await updateWorkflow(activeId, { enabled: !detail.enabled });
    setDetail(updated);
    await loadWorkflows(activeId);
  });

  const onDelete = () => act(async () => {
    await deleteWorkflow(activeId);
    const list = await loadWorkflows(null);
    setActiveId(list.filter((w) => w.id !== activeId)[0]?.id || null);
  });

  const toggleRun = (rid) => {
    setOpenRun((o) => ({ ...o, [rid]: !o[rid] }));
    if (runSteps[rid] || !activeId) return;
    getWorkflowRun(activeId, rid)
      .then((d) => setRunSteps((s) => ({ ...s, [rid]: d.steps || [] })))
      .catch(() => setRunSteps((s) => ({ ...s, [rid]: [] })));
  };

  const selectedNode = nodes.find((n) => n.id === selected) || null;
  const selectedSpec = catalog.find((c) => c.key === selectedNode?.type) || null;
  const selectedStyle = styleFor(selectedSpec?.category);

  return (
    <section className="view">
      <aside className="auto-side">
        <button className="btn primary" onClick={onNew} disabled={busy}>+ New workflow</button>
        <div className="convo-list">
          {workflows === null && <div className="w-meta" style={{ padding: "8px 2px" }}>Loading…</div>}
          {workflows?.length === 0 && (
            <div className="w-meta" style={{ padding: "8px 2px" }}>
              No workflows yet. Create one to get started.
            </div>
          )}
          {(workflows || []).map((w) => (
            <div
              key={w.id}
              className={`wf${w.id === activeId ? " active" : ""}`}
              tabIndex={0}
              onClick={() => setActiveId(w.id)}
              onKeyDown={(e) => e.key === "Enter" && setActiveId(w.id)}
            >
              <div className="w-name">
                {w.name}
                <span className={`status-pip ${w.enabled ? "live" : "paused"}`}>
                  {w.enabled ? "ACTIVE" : "PAUSED"}
                </span>
              </div>
              <div className="w-meta">
                {w.schedule ? `cron · ${w.schedule}` : "manual runs only"}
                <br />
                {`${(w.spec?.nodes || []).length} nodes · updated ${relative(w.updated_at)}`}
              </div>
            </div>
          ))}
        </div>
      </aside>

      <div className="auto-main">
        <div className="auto-toolbar">
          <span className="view-title">{detail?.name || "Automations"}</span>
          {detail && (
            <span className="pill">
              <span
                className="sdot badge-on"
                style={{ background: detail.enabled ? "var(--green)" : "var(--muted)", width: "6px", height: "6px" }}
              />
              {detail.enabled ? "Active" : "Paused"}
            </span>
          )}
          <div className="grow" />
          <button className="btn primary" onClick={onRun} disabled={!detail || busy || !detail.enabled}>
            ▶ Run now
          </button>
          <button className="btn" onClick={onTogglePause} disabled={!detail || busy}>
            {detail?.enabled ? "Pause" : "Resume"}
          </button>
          <button className="btn ghost" onClick={onDelete} disabled={!detail || busy}>Delete</button>
        </div>

        {error && <div className="w-meta" style={{ color: "var(--red)", padding: "0 2px 6px" }}>{error}</div>}

        <div className="canvas-zone">
          <div className="canvas" ref={canvasRef}>
            <svg className="edges">
              {paths.map((d, i) => d && <path key={i} d={d} />)}
            </svg>

            <div className="palette">
              <div className="p-label">Registered nodes</div>
              {catalog.map((n) => (
                <div className="p-item" key={n.key} title={n.key}>
                  <i style={{ background: styleFor(n.category).color }} />{n.label}
                </div>
              ))}
              {catalog.length === 0 && <div className="p-item">Loading…</div>}
            </div>

            {nodes.map((n) => {
              const spec = catalog.find((c) => c.key === n.type);
              const s = styleFor(spec?.category);
              const hasIn = edges.some(([, t]) => t === n.id);
              const hasOut = edges.some(([f]) => f === n.id);
              return (
                <div
                  key={n.id}
                  ref={(el) => (nodeRefs.current[n.id] = el)}
                  className={`node${selected === n.id ? " selected" : ""}`}
                  style={{ left: `${n.left}px`, top: `${n.top}px` }}
                  tabIndex={0}
                  onClick={() => setSelected(n.id)}
                  onKeyDown={(e) => e.key === "Enter" && setSelected(n.id)}
                >
                  <div className={`n-kind ${s.cls}`}><span className="k-star" />{s.label}</div>
                  <div className="n-title">{spec?.label || n.type}</div>
                  <div className="n-sub">{n.id}</div>
                  {hasIn && <span className="port in" />}
                  {hasOut && <span className="port out" />}
                </div>
              );
            })}

            {detail && nodes.length === 0 && (
              <div className="w-meta" style={{ position: "absolute", left: 170, top: 118, maxWidth: 320 }}>
                This workflow has no nodes yet. Editing the canvas is not built — a spec saved
                through the API appears here.
              </div>
            )}
          </div>

          <aside className="config">
            {selectedNode ? (
              <>
                <div className="cfg-head">
                  <div className={`n-kind ${selectedStyle.cls}`}>
                    <span className="k-star" />{selectedStyle.label} node
                  </div>
                  <div className="cfg-title">{selectedSpec?.label || selectedNode.type}</div>
                </div>
                <div className="field">
                  <label>Node id</label>
                  <div className="input mono" style={{ fontSize: "11px" }}>{selectedNode.id}</div>
                </div>
                <div className="field">
                  <label>Type</label>
                  <div className="input mono" style={{ fontSize: "11px" }}>{selectedNode.type}</div>
                </div>
                <div className="field">
                  <label>Saved configuration</label>
                  <textarea rows={8} readOnly value={JSON.stringify(selectedNode.config || {}, null, 2)} />
                </div>
                <div className="field">
                  <label>Accepted settings</label>
                  <div className="var-chips">
                    {Object.keys(selectedSpec?.schema?.properties || {}).map((k) => (
                      <span className="var-chip" key={k}>{k}</span>
                    ))}
                    {!Object.keys(selectedSpec?.schema?.properties || {}).length && (
                      <span className="var-chip">no settings</span>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="w-meta" style={{ padding: "6px 2px" }}>
                {detail ? "Select a node to inspect it." : "Select a workflow."}
              </div>
            )}
          </aside>
        </div>

        <div className="runs">
          <div className="runs-head">
            Run history <span style={{ color: "var(--line)" }}>·</span> stored in your database — runs survive app restarts
          </div>
          {runs.length === 0 && (
            <div className="w-meta" style={{ padding: "8px 2px" }}>
              {detail ? "No runs yet." : "Select a workflow to see its runs."}
            </div>
          )}
          {runs.map((r) => {
            const ok = r.status === "done";
            return (
              <div key={r.id}>
                <div className="run-row" onClick={() => toggleRun(r.id)}>
                  <span className={ok ? "run-ok" : "run-fail"}>{ok ? "✓" : "✕"}</span>
                  <span className="r-when">
                    {relative(r.started_at || r.finished_at)} — {r.status}
                    {r.trigger ? ` · ${r.trigger}` : ""}
                  </span>
                  <span className="r-time">{duration(r)}</span>
                </div>
                <div className={`run-steps${openRun[r.id] ? " open" : ""}`}>
                  {r.error && <div className="step"><b>Run error</b><span className="fail-note">{r.error}</span></div>}
                  {(runSteps[r.id] || []).map((s, i) => (
                    <div className="step" key={i}>
                      <b>{s.node_id}{s.node_type ? ` · ${s.node_type}` : ""}</b>
                      {s.error
                        ? <span className="fail-note">{s.error}</span>
                        : <span>{s.status}{s.output ? ` · ${String(s.output).slice(0, 160)}` : ""}</span>}
                    </div>
                  ))}
                  {openRun[r.id] && !runSteps[r.id] && <div className="step"><b>Loading…</b></div>}
                  {openRun[r.id] && runSteps[r.id]?.length === 0 && !r.error && (
                    <div className="step"><b>No steps recorded</b><span>this run finished without executing a node</span></div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
