import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  Bot,
  CalendarClock,
  Check,
  ChevronRight,
  CirclePause,
  CirclePlay,
  Database,
  KeyRound,
  Plus,
  Save,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import {
  archiveAgent,
  cancelAgentRun,
  createAgent,
  decideAgentApproval,
  getAgentCatalog,
  getAgentRun,
  listAgentApprovals,
  listAgentRuns,
  listAgents,
  setAgentStatus,
  startAgentRun,
  updateAgent,
} from "../lib/api.js";

const EMPTY_CATALOG = {
  models: [], skills: [], builtin_skills: [], datasets: [], ontologies: [], projects: [],
  connections: [], dashboards: [], mcp_servers: [], tools: [], connectors: [],
};

function defaultConfig(catalog) {
  return {
    name: "",
    description: "",
    goal: "",
    guidelines: [],
    model: catalog.models?.[0]?.id || "",
    effort: "",
    skills: [],
    datasets: [],
    ontologies: [],
    projects: [],
    tool_grants: [],
    connector_grants: [],
    trigger_modes: ["manual"],
    budgets: {
      max_steps_per_run: 8,
      max_runtime_seconds: 300,
      max_input_chars: 20000,
      max_output_chars: 20000,
      max_runs_per_day: 100,
      max_cost_usd_per_day: 5,
    },
    permissions: {
      life_access: "none",
      allow_life_with_cloud_models: false,
      approval_risks: ["local_write", "external_write", "destructive", "credential_use"],
    },
    schedule: {
      enabled: false,
      cron: "0 9 * * *",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      misfire_policy: "coalesce",
      concurrency_policy: "forbid",
    },
  };
}

function unique(values) {
  return [...new Set(values)];
}

function cloneConfig(config, catalog) {
  return { ...defaultConfig(catalog), ...structuredClone(config || {}) };
}

function Toggle({ checked, onChange, label, disabled = false }) {
  return (
    <label className={`agent-check${disabled ? " disabled" : ""}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span aria-hidden="true">{checked ? <Check /> : null}</span>
      <b>{label}</b>
    </label>
  );
}

function ResourcePicker({ title, description, items, selected, onChange, empty }) {
  return (
    <fieldset className="agent-fieldset">
      <legend>{title}</legend>
      {description && <p>{description}</p>}
      {items.length === 0 ? <div className="agent-resource-empty">{empty}</div> : (
        <div className="agent-resource-grid">
          {items.map((item) => {
            const id = String(item.id);
            return (
              <Toggle
                key={id}
                checked={selected.includes(id)}
                label={item.name || item.label || id}
                onChange={(checked) => onChange(checked ? unique([...selected, id]) : selected.filter((value) => value !== id))}
              />
            );
          })}
        </div>
      )}
    </fieldset>
  );
}

function optionsForResource(field, catalog) {
  if (field === "connection_id") return catalog.connections || [];
  if (field === "collection_id") return catalog.ontologies || [];
  if (field === "dashboard_id") return catalog.dashboards || [];
  if (field === "server_id") return catalog.mcp_servers || [];
  return [];
}

function ToolGrantEditor({ catalog, grants, onChange }) {
  function toggleTool(tool, checked) {
    if (!checked) return onChange(grants.filter((grant) => grant.tool !== tool.key));
    const resources = {};
    for (const field of tool.resource_fields || []) resources[field] = [];
    onChange([...grants, { tool: tool.key, actions: ["execute"], resources, approval: "risk_based" }]);
  }

  function updateGrant(toolKey, patch) {
    onChange(grants.map((grant) => grant.tool === toolKey ? { ...grant, ...patch } : grant));
  }

  return (
    <fieldset className="agent-fieldset agent-tools-fieldset">
      <legend>Tools &amp; exact scope</legend>
      <p>Tools are denied unless selected here. Resource-aware tools also require an explicit resource.</p>
      <div className="agent-tool-list">
        {(catalog.tools || []).map((tool) => {
          const grant = grants.find((item) => item.tool === tool.key);
          return (
            <div className={`agent-tool-row${grant ? " selected" : ""}`} key={tool.key}>
              <div className="agent-tool-heading">
                <Toggle checked={!!grant} label={tool.label} onChange={(checked) => toggleTool(tool, checked)} />
                <span className={`risk-tag risk-${tool.risk}`}>{String(tool.risk || "read").replaceAll("_", " ")}</span>
              </div>
              {grant && (
                <div className="agent-tool-scope">
                  {(tool.resource_fields || []).map((field) => {
                    const items = optionsForResource(field, catalog);
                    const selected = grant.resources?.[field] || [];
                    return (
                      <div key={field} className="agent-tool-resources">
                        <span>{field.replaceAll("_", " ")}</span>
                        {items.length === 0 ? <em>No compatible resources exist yet.</em> : items.map((item) => {
                          const id = String(item.id);
                          return (
                            <Toggle
                              key={id}
                              checked={selected.includes(id)}
                              label={item.name || item.label || id}
                              onChange={(checked) => updateGrant(tool.key, {
                                resources: {
                                  ...grant.resources,
                                  [field]: checked ? unique([...selected, id]) : selected.filter((value) => value !== id),
                                },
                              })}
                            />
                          );
                        })}
                      </div>
                    );
                  })}
                  <label className="agent-inline-field">
                    <span>Approval</span>
                    <select value={grant.approval} onChange={(event) => updateGrant(tool.key, { approval: event.target.value })}>
                      <option value="risk_based">Based on risk</option>
                      <option value="always">Every call</option>
                      {!(["external_write", "destructive", "credential_use"].includes(tool.risk)) && (
                        <option value="preapproved">Preapproved within scope</option>
                      )}
                    </select>
                  </label>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}

function AgentEditor({ initial, catalog, saving, error, onCancel, onSave }) {
  const [config, setConfig] = useState(() => cloneConfig(initial, catalog));
  const [guidelines, setGuidelines] = useState(() => (initial?.guidelines || []).join("\n"));
  const skills = useMemo(() => [
    ...(catalog.builtin_skills || []).map((item) => ({ id: `builtin:${item.name}`, name: `${item.name} · built in` })),
    ...(catalog.skills || []).map((item) => ({ id: item.id, name: item.name })),
  ], [catalog]);

  function patch(field, value) {
    setConfig((current) => ({ ...current, [field]: value }));
  }

  function patchNested(group, field, value) {
    setConfig((current) => ({ ...current, [group]: { ...current[group], [field]: value } }));
  }

  function toggleTrigger(trigger, checked) {
    const next = checked
      ? unique([...config.trigger_modes, trigger])
      : config.trigger_modes.filter((item) => item !== trigger);
    patch("trigger_modes", next);
    if (trigger === "schedule") patchNested("schedule", "enabled", checked);
  }

  function submit(event) {
    event.preventDefault();
    onSave({
      ...config,
      guidelines: guidelines.split("\n").map((line) => line.trim()).filter(Boolean),
    });
  }

  return (
    <form className="agent-editor" onSubmit={submit}>
      <header className="agent-editor-header">
        <div><span className="eyebrow">Agent builder</span><h2>{initial ? `Edit ${initial.name}` : "Create a capable, bounded agent"}</h2></div>
        <button type="button" className="icon-btn" aria-label="Close agent editor" onClick={onCancel}><X /></button>
      </header>

      <div className="agent-form-section">
        <h3><Bot /> Identity &amp; purpose</h3>
        <div className="agent-form-grid two">
          <label><span>Name</span><input required maxLength={160} value={config.name} onChange={(e) => patch("name", e.target.value)} placeholder="Weekly research brief" /></label>
          <label><span>Model</span><select required value={config.model} onChange={(e) => patch("model", e.target.value)}><option value="">Choose a connected model</option>{(catalog.models || []).map((model) => <option key={model.id} value={model.id}>{model.label || model.id}</option>)}</select></label>
        </div>
        <label><span>Description</span><input maxLength={1000} value={config.description} onChange={(e) => patch("description", e.target.value)} placeholder="What this agent is for" /></label>
        <label><span>Goal</span><textarea required rows={5} maxLength={8000} value={config.goal} onChange={(e) => patch("goal", e.target.value)} placeholder="Describe the outcome, success criteria, and when to ask you instead of guessing." /></label>
        <label><span>Guidelines <small>one per line</small></span><textarea rows={5} value={guidelines} onChange={(e) => setGuidelines(e.target.value)} placeholder={"Prefer primary sources.\nNever invent missing data.\nAsk before external writes."} /></label>
      </div>

      <div className="agent-form-section">
        <h3><Database /> Orrery context</h3>
        <div className="agent-picker-columns">
          <ResourcePicker title="Skills" items={skills} selected={config.skills} onChange={(value) => patch("skills", value)} empty="Create a skill to attach reusable guidance." />
          <ResourcePicker title="Projects" items={catalog.projects || []} selected={config.projects} onChange={(value) => patch("projects", value)} empty="No projects yet." />
          <ResourcePicker title="Datasets" items={catalog.datasets || []} selected={config.datasets} onChange={(value) => patch("datasets", value)} empty="No datasets yet." />
          <ResourcePicker title="Ontologies" items={catalog.ontologies || []} selected={config.ontologies} onChange={(value) => patch("ontologies", value)} empty="No ontologies yet." />
        </div>
      </div>

      <div className="agent-form-section"><h3><Wrench /> Capabilities</h3><ToolGrantEditor catalog={catalog} grants={config.tool_grants} onChange={(value) => patch("tool_grants", value)} /></div>

      <div className="agent-form-section">
        <h3><CalendarClock /> Triggers &amp; schedule</h3>
        <div className="agent-trigger-row">
          <Toggle checked disabled label="Manual" onChange={() => {}} />
          <Toggle checked={config.trigger_modes.includes("api")} label="Scoped API" onChange={(value) => toggleTrigger("api", value)} />
          <Toggle checked={config.trigger_modes.includes("schedule")} label="Schedule" onChange={(value) => toggleTrigger("schedule", value)} />
          <Toggle disabled label="Slack · connect account first" checked={false} onChange={() => {}} />
          <Toggle disabled label="Gmail · connect account first" checked={false} onChange={() => {}} />
        </div>
        {config.schedule.enabled && (
          <div className="agent-form-grid schedule">
            <label><span>Cron · five fields</span><input value={config.schedule.cron} onChange={(e) => patchNested("schedule", "cron", e.target.value)} /></label>
            <label><span>IANA timezone</span><input value={config.schedule.timezone} onChange={(e) => patchNested("schedule", "timezone", e.target.value)} /></label>
            <label><span>When Orrery was offline</span><select value={config.schedule.misfire_policy} onChange={(e) => patchNested("schedule", "misfire_policy", e.target.value)}><option value="coalesce">Run once</option><option value="skip">Skip missed run</option></select></label>
            <label><span>Overlapping runs</span><select value={config.schedule.concurrency_policy} onChange={(e) => patchNested("schedule", "concurrency_policy", e.target.value)}><option value="forbid">Forbid overlap</option><option value="queue">Queue next</option><option value="replace">Cancel and replace</option></select></label>
          </div>
        )}
      </div>

      <div className="agent-form-section">
        <h3><ShieldCheck /> Limits &amp; memory</h3>
        <div className="agent-form-grid limits">
          <label><span>Steps per run</span><input type="number" min="1" max="30" value={config.budgets.max_steps_per_run} onChange={(e) => patchNested("budgets", "max_steps_per_run", Number(e.target.value))} /></label>
          <label><span>Runtime seconds</span><input type="number" min="15" max="3600" value={config.budgets.max_runtime_seconds} onChange={(e) => patchNested("budgets", "max_runtime_seconds", Number(e.target.value))} /></label>
          <label><span>Runs per day</span><input type="number" min="1" max="10000" value={config.budgets.max_runs_per_day} onChange={(e) => patchNested("budgets", "max_runs_per_day", Number(e.target.value))} /></label>
          <label><span>Daily API budget $</span><input type="number" min="0" max="10000" step="0.1" value={config.budgets.max_cost_usd_per_day} onChange={(e) => patchNested("budgets", "max_cost_usd_per_day", Number(e.target.value))} /></label>
          <label><span>LIFE.md access</span><select value={config.permissions.life_access} onChange={(e) => patchNested("permissions", "life_access", e.target.value)}><option value="none">None</option><option value="read">Read approved memory</option><option value="propose">Read + propose changes</option></select></label>
          <label><span>Reasoning depth</span><select value={config.effort} onChange={(e) => patch("effort", e.target.value)}><option value="">Standard</option><option value="low">Quick</option><option value="medium">Medium</option><option value="high">Deep</option><option value="xhigh">Maximum</option></select></label>
        </div>
      </div>

      {error && <div className="agent-form-error" role="alert">{error}</div>}
      <footer className="agent-editor-footer">
        <span><ShieldCheck /> Saved versions are immutable. Running work keeps its original grants.</span>
        <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>
        <button className="btn primary" disabled={saving}><Save />{saving ? "Saving…" : initial ? "Save new version" : "Create agent"}</button>
      </footer>
    </form>
  );
}

function AgentInspector({ agent }) {
  if (!agent) return <aside className="agents-inspector"><div className="agent-inspector-empty"><ShieldCheck /><b>Bounded by default</b><p>Choose or create an agent to inspect its exact authority.</p></div></aside>;
  const config = agent.config || {};
  return (
    <aside className="agents-inspector">
      <div className="agents-inspector-head"><span className="eyebrow">Authority snapshot</span><b>Version {agent.version}</b><code>{agent.config_hash?.slice(0, 12)}</code></div>
      <section><h4><Wrench /> Tools</h4>{config.tool_grants?.length ? config.tool_grants.map((grant) => <div className="inspector-line" key={grant.tool}><b>{grant.tool}</b><span>{grant.approval.replaceAll("_", " ")}</span></div>) : <p>No tools granted.</p>}</section>
      <section><h4><Database /> Context</h4><div className="agent-count-grid"><span><b>{config.skills?.length || 0}</b>skills</span><span><b>{config.datasets?.length || 0}</b>datasets</span><span><b>{config.ontologies?.length || 0}</b>ontologies</span><span><b>{config.projects?.length || 0}</b>projects</span></div></section>
      <section><h4><ShieldCheck /> Limits</h4><div className="inspector-line"><b>{config.budgets?.max_steps_per_run || 0} steps</b><span>per run</span></div><div className="inspector-line"><b>{config.budgets?.max_runtime_seconds || 0}s</b><span>runtime</span></div><div className="inspector-line"><b>${Number(config.budgets?.max_cost_usd_per_day || 0).toFixed(2)}</b><span>daily API cap</span></div><div className="inspector-line"><b>{config.permissions?.life_access || "none"}</b><span>LIFE.md</span></div></section>
      <section><h4><KeyRound /> Integration API</h4><p>{config.trigger_modes?.includes("api") ? "Enabled for scoped, revocable keys. No key exists until you create one." : "Disabled for this agent."}</p></section>
    </aside>
  );
}

const RUN_ACTIVE = new Set(["queued", "running", "awaiting_approval"]);
const RUN_DOT = { succeeded: "", failed: "red", cancelled: "red", interrupted: "red" };

function relTime(stamp) {
  const t = Date.parse(stamp || "");
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

const STEP_ICON = { model: Sparkles, tool: Wrench, approval: ShieldCheck, system: Bot, memory: Database };

function AgentActivity({ agent, formOpen, onFormClose }) {
  const [runs, setRuns] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [openRun, setOpenRun] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function reload(detailId = openId) {
    try {
      const [r, a] = await Promise.all([listAgentRuns(agent.id), listAgentApprovals()]);
      const rows = r.runs || [];
      setRuns(rows);
      const runIds = new Set(rows.map((x) => x.id));
      setApprovals((a.approvals || []).filter((p) => runIds.has(p.run_id)));
      if (detailId) setOpenRun(await getAgentRun(detailId).catch(() => null));
    } catch (e) { setErr(String(e.message || e)); }
  }

  useEffect(() => { setRuns(null); setOpenId(null); setOpenRun(null); setErr(""); reload(null); }, [agent.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const active = (runs || []).some((run) => RUN_ACTIVE.has(run.status));
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => reload(), 2500);
    return () => clearInterval(timer);
  }, [active, agent.id, openId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    setBusy(true); setErr("");
    try { await startAgentRun(agent.id, input.trim()); setInput(""); onFormClose(); await reload(); }
    catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  async function decide(approval, approve) {
    setBusy(true); setErr("");
    try { await decideAgentApproval(approval.id, approve); await reload(); }
    catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  async function toggleRun(run) {
    if (openId === run.id) { setOpenId(null); setOpenRun(null); return; }
    setOpenId(run.id);
    setOpenRun(await getAgentRun(run.id).catch(() => null));
  }

  return (
    <section className="agent-detail-section">
      <div className="agent-section-heading"><h2>Activity</h2><span>durable run ledger</span></div>
      {formOpen && (
        <div className="agent-run-form">
          <textarea rows={2} value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="What should this agent work on for this run? Leave empty to just pursue its goal." />
          <div className="agent-run-form-actions">
            <button className="btn ghost sm" onClick={onFormClose} disabled={busy}>Cancel</button>
            <button className="btn primary sm" onClick={start} disabled={busy}><CirclePlay />{busy ? "Starting…" : "Start run"}</button>
          </div>
        </div>
      )}
      {approvals.map((approval) => (
        <div className="agent-approval-card" key={approval.id}>
          <ShieldCheck />
          <div className="agent-approval-body">
            <b>Approval needed · {approval.tool_key} <span className={`risk-tag risk-${approval.risk}`}>{String(approval.risk || "").replaceAll("_", " ")}</span></b>
            <pre>{approval.action}</pre>
          </div>
          <div className="agent-approval-actions">
            <button className="btn ghost sm" disabled={busy} onClick={() => decide(approval, false)}>Reject</button>
            <button className="btn primary sm" disabled={busy} onClick={() => decide(approval, true)}>Approve</button>
          </div>
        </div>
      ))}
      {err && <div className="agent-form-error" role="alert">{err}</div>}
      {runs == null && <p className="agent-empty-copy">Loading runs…</p>}
      {runs != null && runs.length === 0 && (
        <div className="agent-activity-empty"><CirclePlay /><b>No runs yet</b><p>Press Run to give this agent a task now, or enable its schedule under Edit. Every model step, approval, and tool result lands here.</p></div>
      )}
      {(runs || []).map((run) => (
        <div key={run.id} className={`agent-run-row${openId === run.id ? " open" : ""}`}>
          <button type="button" className="agent-run-head" onClick={() => toggleRun(run)}>
            <i className={`pulse ${RUN_ACTIVE.has(run.status) ? "amber" : (RUN_DOT[run.status] ?? "amber")}`} />
            <b>{run.input_text?.trim() ? run.input_text.trim().slice(0, 80) : "Goal run"}</b>
            <span className="agent-run-meta">{run.trigger_type} · {run.status.replaceAll("_", " ")} · {relTime(run.created_at)}</span>
            <ChevronRight />
          </button>
          {openId === run.id && (
            <div className="agent-run-body">
              {RUN_ACTIVE.has(run.status) && (
                <button className="btn ghost sm" onClick={async () => { await cancelAgentRun(run.id).catch(() => {}); reload(); }}>Cancel run</button>
              )}
              {(openRun?.steps || []).map((step) => {
                const Icon = STEP_ICON[step.kind] || Bot;
                return (
                  <div key={step.sequence} className={`agent-step step-${step.status}`}>
                    <Icon />
                    <div><b>{step.summary || step.kind}</b>
                      {step.detail && <pre>{step.detail.length > 1200 ? `${step.detail.slice(0, 1200)}…` : step.detail}</pre>}
                    </div>
                  </div>
                );
              })}
              {run.output_text && <div className="agent-run-output"><b>Result</b><pre>{run.output_text}</pre></div>}
              {run.error && <div className="agent-form-error">{run.error}</div>}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

function AgentDetail({ agent, onEdit, onStatus, onArchive }) {
  const config = agent.config || {};
  const schedule = config.schedule || {};
  const [runFormOpen, setRunFormOpen] = useState(false);
  return (
    <main className="agents-main">
      <header className="agents-toolbar">
        <div><span className="eyebrow">Agent workspace</span><h1>{agent.name}</h1></div>
        <span className={`agent-status status-${agent.status}`}>{agent.status}</span>
        <div className="grow" />
        <button className="btn ghost" onClick={onEdit}>Edit</button>
        <button
          className="btn primary"
          disabled={agent.status !== "active"}
          title={agent.status === "active" ? "Start a run now" : "Activate the agent to run it"}
          onClick={() => setRunFormOpen((open) => !open)}
        >
          <CirclePlay />Run
        </button>
        <button className="btn" onClick={() => onStatus(agent.status === "active" ? "paused" : "active")}>
          {agent.status === "active" ? <CirclePause /> : <CirclePlay />}{agent.status === "active" ? "Pause" : "Activate"}
        </button>
        <button className="icon-btn danger" aria-label="Archive agent" onClick={onArchive}><Archive /></button>
      </header>
      <div className="agents-detail-scroll">
        <section className="agent-hero-card"><div className="agent-orbit-mark"><Bot /></div><div><span className="eyebrow">Goal</span><p>{config.goal}</p></div></section>
        <div className="agent-summary-grid">
          <article><Sparkles /><span>Model</span><b>{config.model}</b><p>{config.effort || "standard"} reasoning</p></article>
          <article><CalendarClock /><span>Run mode</span><b>{schedule.enabled ? schedule.cron : (config.trigger_modes || ["manual"]).join(" · ")}</b><p>{schedule.enabled ? `${schedule.timezone} · ${schedule.misfire_policy}` : "Runs only from enabled triggers"}</p></article>
          <article><ShieldCheck /><span>Guardrails</span><b>{config.budgets?.max_steps_per_run} steps · {config.budgets?.max_runtime_seconds}s</b><p>High-risk actions suspend for approval.</p></article>
        </div>
        <section className="agent-detail-section"><div className="agent-section-heading"><h2>Guidelines</h2><span>{config.guidelines?.length || 0}</span></div>{config.guidelines?.length ? <ol>{config.guidelines.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}</ol> : <p className="agent-empty-copy">No extra guidelines. The goal and platform safety policy still apply.</p>}</section>
        <section className="agent-detail-section"><div className="agent-section-heading"><h2>Granted capabilities</h2><span>{config.tool_grants?.length || 0}</span></div><div className="agent-capability-grid">{config.tool_grants?.length ? config.tool_grants.map((grant) => <div className="agent-capability" key={grant.tool}><Wrench /><div><b>{grant.tool}</b><p>{grant.approval.replaceAll("_", " ")} · {Object.values(grant.resources || {}).flat().length} scoped resources</p></div></div>) : <p className="agent-empty-copy">No tools. This agent can reason and answer, but cannot act.</p>}</div></section>
        <AgentActivity agent={agent} formOpen={runFormOpen} onFormClose={() => setRunFormOpen(false)} />
      </div>
    </main>
  );
}

export default function Agents() {
  const [agents, setAgents] = useState([]);
  const [catalog, setCatalog] = useState(EMPTY_CATALOG);
  const [selectedId, setSelectedId] = useState(null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const selected = agents.find((agent) => agent.id === selectedId) || agents[0] || null;

  async function load(preferredId) {
    const [agentData, catalogData] = await Promise.all([listAgents(), getAgentCatalog()]);
    const nextAgents = agentData.agents || [];
    setAgents(nextAgents);
    setCatalog({ ...EMPTY_CATALOG, ...catalogData });
    setSelectedId(preferredId || selectedId || nextAgents[0]?.id || null);
  }

  useEffect(() => {
    load().catch((e) => setError(String(e.message || e))).finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(config) {
    setSaving(true); setError("");
    try {
      const result = creating ? await createAgent(config) : await updateAgent(selected.id, config);
      await load(result.id);
      setCreating(false); setEditing(false);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(status) {
    setError("");
    try { const result = await setAgentStatus(selected.id, status); await load(result.id); }
    catch (e) { setError(String(e.message || e)); }
  }

  async function archive() {
    if (!window.confirm(`Archive ${selected.name}? Existing history stays available.`)) return;
    setError("");
    try { await archiveAgent(selected.id); setSelectedId(null); await load(); }
    catch (e) { setError(String(e.message || e)); }
  }

  return (
    <section className="view agents-view">
      <aside className="agents-list-pane">
        <div className="agents-list-head"><div><span className="eyebrow">Autonomous work</span><h2>Agents</h2></div><button className="icon-btn primary" aria-label="New agent" onClick={() => { setCreating(true); setEditing(true); setError(""); }}><Plus /></button></div>
        <p className="agents-list-note">A goal, exact authority, a model, and a bounded way to run.</p>
        <div className="agents-list-scroll">
          {loading && <div className="agents-loading">Loading agents…</div>}
          {!loading && agents.length === 0 && <button className="agents-empty-list" onClick={() => { setCreating(true); setEditing(true); }}><Bot /><b>Create your first agent</b><span>Attach skills, data, tools, schedules, and integrations.</span></button>}
          {agents.map((agent) => (
            <button key={agent.id} className={`agent-list-item${selected?.id === agent.id ? " active" : ""}`} onClick={() => { setSelectedId(agent.id); setEditing(false); setCreating(false); setError(""); }}>
              <span className={`agent-list-icon status-${agent.status}`}><Bot /></span><span><b>{agent.name}</b><small>{agent.config?.model || "No model"} · v{agent.version}</small></span><ChevronRight />
            </button>
          ))}
        </div>
        <div className="agents-list-foot"><ShieldCheck /><span>Local by default<br /><small>External access is opt-in and scoped.</small></span></div>
      </aside>

      {editing ? (
        <main className="agents-main agent-editor-main"><AgentEditor initial={creating ? null : selected?.config} catalog={catalog} saving={saving} error={error} onCancel={() => { setEditing(false); setCreating(false); setError(""); }} onSave={save} /></main>
      ) : selected ? (
        <AgentDetail agent={selected} onEdit={() => setEditing(true)} onStatus={changeStatus} onArchive={archive} />
      ) : (
        <main className="agents-main agents-zero"><div className="agent-zero-orbit"><Bot /></div><span className="eyebrow">Build with boundaries</span><h1>Give recurring work a durable home.</h1><p>Create an agent, attach only the Orrery context and tools it needs, then choose manual, schedule, API, Slack, or Gmail triggers.</p><button className="btn primary" onClick={() => { setCreating(true); setEditing(true); }}><Plus />Create agent</button>{error && <div className="agent-form-error">{error}</div>}</main>
      )}

      {!editing && <AgentInspector agent={selected} />}
    </section>
  );
}
