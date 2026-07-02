import { useEffect, useRef, useState } from "react";
import { LayoutGrid, Plus, Save, Search, Server, Sparkles, Trash2, Upload, WandSparkles, X } from "lucide-react";
import {
  approveMcp, approveSkill, createMcp, createSkill, deleteMcp, deleteSkill, generateSkill, getModels,
  getTeam, listMcp, listSkills, testMcp, updateMcp, updateSkill, uploadSkill,
} from "../lib/api.js";

const emptyDraft = { name: "", triggers: "", body: "", always: false, enabled: true };

// Skills tab: the user creates/uploads their own instruction playbooks. Enabled skills are matched
// against each message (by trigger phrases, or "always") and injected into the model's prompt,
// alongside Orrery's built-in skills.
export default function Skills() {
  const [items, setItems] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [draft, setDraft] = useState(emptyDraft);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [query, setQuery] = useState("");
  const [models, setModels] = useState([]);
  const [genText, setGenText] = useState("");
  const [genOpen, setGenOpen] = useState(false);
  const [genBusy, setGenBusy] = useState(false);
  const [builtin, setBuiltin] = useState([]);
  const [mcp, setMcp] = useState([]);
  const emptyMcp = { name: "", transport: "stdio", command: "", url: "", envText: "" };
  const [mcpForm, setMcpForm] = useState(emptyMcp);
  const [mcpOpen, setMcpOpen] = useState(false);
  const [isAdmin, setIsAdmin] = useState(true); // solo or team-admin can approve; default true (solo)
  const fileRef = useRef(null);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? items.filter((s) => (s.name || "").toLowerCase().includes(q) || (s.triggers || "").toLowerCase().includes(q))
    : items;
  const enabledCount = items.filter((s) => s.enabled).length;
  const mcpEnabled = mcp.filter((s) => s.enabled).length;
  const pendingSkills = items.filter((s) => s.status === "pending");
  const pendingMcp = mcp.filter((s) => s.status === "pending");
  const pendingCount = pendingSkills.length + pendingMcp.length;

  async function load(nextActive) {
    const data = await listSkills();
    setItems(data.skills);
    setBuiltin(data.builtin || []);
    const chosen = nextActive || (data.skills.find((s) => s.id === activeId)?.id) || "";
    if (chosen) openItem(chosen, data.skills);
    else { setActiveId(""); setDraft(emptyDraft); }
  }
  async function loadMcp() {
    try { const d = await listMcp(); setMcp(d.servers || []); } catch { /* ignore */ }
  }
  useEffect(() => {
    load("").catch((e) => setErr(String(e.message || e)));
    loadMcp();
    getModels().then((m) => setModels(m.models || [])).catch(() => {});
    getTeam().then((t) => setIsAdmin(!t.team_mode || t.user?.role === "admin")).catch(() => {});
  }, []);

  async function approveSkillItem(s) {
    try { await approveSkill(s.id); await load(activeId); } catch (e) { setErr(String(e.message || e)); }
  }
  async function rejectSkillItem(s) {
    if (!window.confirm(`Reject and delete "${s.name}"?`)) return;
    try { await deleteSkill(s.id); await load(""); } catch (e) { setErr(String(e.message || e)); }
  }
  async function approveMcpItem(s) {
    try { await approveMcp(s.id); await loadMcp(); } catch (e) { setErr(String(e.message || e)); }
  }
  async function rejectMcpItem(s) {
    if (!window.confirm(`Reject and delete "${s.name}"?`)) return;
    try { await deleteMcp(s.id); await loadMcp(); } catch (e) { setErr(String(e.message || e)); }
  }

  // "KEY=value" lines -> {KEY: value}; values are secrets and go straight to the OS keychain.
  function parseEnvText(text) {
    const env = {};
    for (const line of String(text || "").split("\n")) {
      const i = line.indexOf("=");
      if (i > 0) env[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
    return env;
  }

  async function addMcp() {
    if (!mcpForm.name.trim()) { setErr("Name the MCP server"); return; }
    try {
      const { envText, ...rest } = mcpForm;
      await createMcp({ ...rest, env: parseEnvText(envText), enabled: false });
      setMcpForm(emptyMcp); setMcpOpen(false); await loadMcp();
    } catch (e) { setErr(String(e.message || e)); }
  }
  async function toggleMcp(srv, next) {
    setMcp((prev) => prev.map((x) => (x.id === srv.id ? { ...x, enabled: next } : x)));
    try { await updateMcp(srv.id, { enabled: next }); } catch (e) { setErr(String(e.message || e)); await loadMcp(); }
  }
  async function removeMcp(srv) {
    if (!window.confirm("Remove this MCP server?")) return;
    try { await deleteMcp(srv.id); await loadMcp(); } catch (e) { setErr(String(e.message || e)); }
  }
  async function testMcpServer(srv) {
    setErr(""); setMsg("");
    setMcp((prev) => prev.map((x) => (x.id === srv.id ? { ...x, testing: true } : x)));
    try {
      const res = await testMcp(srv.id);
      if (res.ok) { setMsg(`${srv.name}: connected - ${res.tools.length} tool(s).`); await loadMcp(); }
      else setErr(res.error || "Could not connect to the server.");
    } catch (e) { setErr(String(e.message || e)); } finally {
      setMcp((prev) => prev.map((x) => (x.id === srv.id ? { ...x, testing: false } : x)));
    }
  }

  async function generate() {
    const desc = genText.trim();
    if (!desc) return;
    if (!models[0]) { setErr("Connect a model first (Chat tab)."); return; }
    setGenBusy(true); setErr("");
    try {
      const created = await generateSkill(desc, models[0].id);
      setGenText(""); setGenOpen(false);
      await load(created.id);
    } catch (e) { setErr(String(e.message || e)); } finally { setGenBusy(false); }
  }

  function openItem(id, known = items) {
    setErr(""); setActiveId(id);
    const it = known.find((s) => s.id === id);
    if (it) setDraft({ name: it.name || "", triggers: it.triggers || "", body: it.body || "", always: !!it.always, enabled: !!it.enabled });
  }

  async function addItem() {
    setBusy(true); setErr("");
    try {
      const created = await createSkill({ name: "New skill", body: "Describe what the model should do...", triggers: "", always: false, enabled: true });
      await load(created.id);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function save() {
    if (!activeId) return;
    setBusy(true); setErr("");
    try { await updateSkill(activeId, draft); await load(activeId); }
    catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function remove() {
    if (!activeId || !window.confirm("Delete this skill?")) return;
    setBusy(true); setErr("");
    try { await deleteSkill(activeId); await load(""); }
    catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function setEnabled(s, next) {
    setItems((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: next } : x)));
    if (s.id === activeId) setDraft((d) => ({ ...d, enabled: next }));
    try { await updateSkill(s.id, { enabled: next }); }
    catch (e) { setErr(String(e.message || e)); await load(activeId); }
  }

  async function onFilePick(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true); setErr("");
    try {
      const text = await file.text();
      const created = await uploadSkill(text, file.name.replace(/\.[^.]+$/, ""));
      await load(created.id);
    } catch (e2) { setErr(String(e2.message || e2)); } finally { setBusy(false); }
  }

  return (
    <section className="view projects-view">
      <aside className="project-side">
        <button className="btn primary project-new" onClick={addItem} disabled={busy}><Plus /> New skill</button>
        <button className="btn ghost sm skill-wide" onClick={() => fileRef.current?.click()} disabled={busy}>
          <Upload /> Upload .md skill
        </button>
        <input ref={fileRef} type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden onChange={onFilePick} />
        <button className="btn ghost sm skill-wide" onClick={() => setGenOpen((o) => !o)} disabled={busy}>
          <WandSparkles /> Generate with AI
        </button>
        {genOpen && (
          <div className="skill-gen">
            <textarea
              value={genText}
              onChange={(e) => setGenText(e.target.value)}
              rows={3}
              placeholder="Describe the skill you want the model to write, e.g. 'A skill for writing tight, friendly release notes from a changelog.'"
            />
            <button className="btn primary sm skill-wide" onClick={generate} disabled={genBusy || !genText.trim()}>
              {genBusy ? "Generating..." : "Generate skill"}
            </button>
          </div>
        )}
        <div className="ontology-search">
          <Search />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search skills..." />
        </div>
        <div className="project-list project-tree">
          <div className={`project-node${!activeId ? " active" : ""}`}>
            <button className="project-item" onClick={() => { setActiveId(""); setDraft(emptyDraft); }}>
              <LayoutGrid />
              <span><b>Overview</b><small>built-in skills &amp; MCP</small></span>
            </button>
          </div>
          {filtered.length === 0 && <div className="convo-empty">{items.length ? "No matches" : "No skills yet"}</div>}
          {filtered.map((s) => (
            <div key={s.id} className={`project-node${s.id === activeId ? " active" : ""}`}>
              <button className="project-item" onClick={() => openItem(s.id)}>
                <Sparkles />
                <span>
                  <b>{s.name}{s.status === "pending" && <span className="pending-pill">pending</span>}</b>
                  <small>{s.always ? "always on" : (s.triggers ? `triggers: ${s.triggers}` : "no triggers")}</small>
                </span>
              </button>
              <span
                className={`toggle${s.enabled ? " on" : ""}`}
                role="switch" aria-checked={s.enabled} tabIndex={0}
                title={s.enabled ? "Enabled" : "Disabled"}
                onClick={() => setEnabled(s, !s.enabled)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setEnabled(s, !s.enabled); } }}
              />
            </div>
          ))}
        </div>
      </aside>

      <main className="project-main">
        {!activeId ? (
          <div className="skill-overview">
            <div className="workspace-summary skill-summary">
              <span><b>{items.length}</b><small>User skills</small></span>
              <span><b>{enabledCount}</b><small>Enabled</small></span>
              <span><b>{builtin.length}</b><small>Built-in</small></span>
              <span><b>{mcpEnabled}/{mcp.length}</b><small>MCP on</small></span>
            </div>

            {isAdmin && pendingCount > 0 && (
              <section className="ov-section">
                <div className="section-label"><span>Pending approval ({pendingCount})</span></div>
                <p className="ov-sub">Skills and MCP servers submitted by members. Approve to make them available team-wide.</p>
                <div className="ov-list">
                  {pendingSkills.map((s) => (
                    <div key={s.id} className="ov-row">
                      <Sparkles />
                      <span className="ov-meta"><b>{s.name}</b><small>skill - {s.always ? "always on" : (s.triggers || "no triggers")}</small></span>
                      <button className="btn ghost sm" onClick={() => rejectSkillItem(s)}>Reject</button>
                      <button className="btn primary sm" onClick={() => approveSkillItem(s)}>Approve</button>
                    </div>
                  ))}
                  {pendingMcp.map((s) => (
                    <div key={s.id} className="ov-row">
                      <Server />
                      <span className="ov-meta"><b>{s.name}</b><small>MCP - {s.transport === "http" ? (s.url || "http") : (s.command || "stdio")}</small></span>
                      <button className="btn ghost sm" onClick={() => rejectMcpItem(s)}>Reject</button>
                      <button className="btn primary sm" onClick={() => approveMcpItem(s)}>Approve</button>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="ov-section">
              <div className="section-label"><span>Built-in skills</span></div>
              <p className="ov-sub">Prebuilt skills shipped with Orrery - always available, matched automatically.</p>
              <div className="ov-list">
                {builtin.length === 0 && <div className="project-muted">None found.</div>}
                {builtin.map((b) => (
                  <div key={b.name} className="ov-row">
                    <Sparkles />
                    <span className="ov-meta"><b>{b.name}</b><small>{b.always ? "always on" : (b.triggers || "no triggers")}</small></span>
                    <span className="ov-badge">active</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="ov-section">
              <div className="section-label">
                <span>MCP servers</span>
                <button className="btn ghost sm" onClick={() => setMcpOpen((o) => !o)}><Plus /> Add server</button>
              </div>
              <p className="ov-sub">Connect Model Context Protocol servers as tools/context. Saved now; turning one on opts it in. Live tool execution is the next step.</p>
              {mcpOpen && (
                <div className="mcp-form">
                  <input placeholder="Name" value={mcpForm.name} onChange={(e) => setMcpForm((f) => ({ ...f, name: e.target.value }))} />
                  <select value={mcpForm.transport} onChange={(e) => setMcpForm((f) => ({ ...f, transport: e.target.value }))}>
                    <option value="stdio">stdio - local command</option>
                    <option value="http">http / sse - URL</option>
                  </select>
                  {mcpForm.transport === "stdio" ? (
                    <input placeholder="Command, e.g. npx -y @modelcontextprotocol/server-filesystem /path" value={mcpForm.command} onChange={(e) => setMcpForm((f) => ({ ...f, command: e.target.value }))} />
                  ) : (
                    <input placeholder="https://your-mcp-server/sse" value={mcpForm.url} onChange={(e) => setMcpForm((f) => ({ ...f, url: e.target.value }))} />
                  )}
                  <textarea
                    className="mcp-env"
                    rows={2}
                    placeholder={"Environment variables the server needs (one per line):\nGITHUB_TOKEN=ghp_..."}
                    value={mcpForm.envText}
                    onChange={(e) => setMcpForm((f) => ({ ...f, envText: e.target.value }))}
                    spellCheck={false}
                  />
                  <small className="ov-sub" style={{ margin: 0 }}>Values are stored only in your OS keychain and passed to the server at launch — never shown again.</small>
                  <button className="btn primary sm" onClick={addMcp}>Save server</button>
                </div>
              )}
              <div className="ov-list">
                {mcp.length === 0 && <div className="project-muted">No MCP servers yet.</div>}
                {mcp.map((s) => (
                  <div key={s.id} className="ov-row">
                    <Server />
                    <span className="ov-meta">
                      <b>{s.name}{s.status === "pending" && <span className="pending-pill">pending</span>}</b>
                      <small>
                        {(s.tools?.length ? `${s.tools.length} tool(s) - ` : "")}
                        {(s.env_names?.length ? `${s.env_names.length} env - ` : "")}
                        {s.transport === "http" ? (s.url || "http") : (s.command || "stdio")}
                      </small>
                    </span>
                    <button className="btn ghost sm" onClick={() => testMcpServer(s)} disabled={s.testing}>{s.testing ? "Testing..." : "Test"}</button>
                    <span className={`toggle${s.enabled ? " on" : ""}`} role="switch" aria-checked={s.enabled} tabIndex={0} title={s.enabled ? "Enabled" : "Disabled"} onClick={() => toggleMcp(s, !s.enabled)} />
                    <button className="icon-btn" title="Remove" onClick={() => removeMcp(s)}><X /></button>
                  </div>
                ))}
              </div>
            </section>
            {err && <div className="chat-banner">{err}</div>}
            {msg && <div className="admin-ok">{msg}</div>}
          </div>
        ) : (
          <>
            <div className="project-head">
              <input
                className="project-title-input"
                value={draft.name}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                onBlur={save}
                maxLength={120}
                placeholder="Skill name"
              />
              <div className="grow" />
              <span className="rag-toggle" title="Apply this skill on every message">
                Always on
                <span className={`toggle${draft.always ? " on" : ""}`} role="switch" aria-checked={draft.always} tabIndex={0}
                  onClick={() => setDraft((d) => ({ ...d, always: !d.always }))} />
              </span>
              <span className="rag-toggle" title="Enable/disable this skill">
                Enabled
                <span className={`toggle${draft.enabled ? " on" : ""}`} role="switch" aria-checked={draft.enabled} tabIndex={0}
                  onClick={() => setDraft((d) => ({ ...d, enabled: !d.enabled }))} />
              </span>
              <button className="btn" onClick={save} disabled={busy}><Save /> Save</button>
              <button className="btn ghost" onClick={remove} disabled={busy}><Trash2 /></button>
            </div>

            <div className="workspace-summary">
              <span><b>{draft.enabled ? "Enabled" : "Disabled"}</b><small>Status</small></span>
              <span><b>{draft.always ? "Always" : "Triggered"}</b><small>Activation</small></span>
              <span><b>{draft.triggers.split(/[\n,]/).filter((x) => x.trim()).length}</b><small>Triggers</small></span>
            </div>

            <div className="project-details">
              <label>
                Trigger phrases (comma or newline separated; leave empty if "always on")
                <textarea
                  value={draft.triggers}
                  onChange={(e) => setDraft((d) => ({ ...d, triggers: e.target.value }))}
                  rows={2}
                  placeholder="e.g. powerpoint, deck, presentation"
                />
              </label>
            </div>

            {err && <div className="chat-banner">{err}</div>}

            <div className="project-body">
              <div className="project-files-panel full-panel">
                <div className="section-label"><span>Skill instructions</span></div>
                <textarea
                  className="skill-body"
                  value={draft.body}
                  onChange={(e) => setDraft((d) => ({ ...d, body: e.target.value }))}
                  placeholder="Write the playbook the model should follow when this skill applies..."
                />
              </div>
            </div>
          </>
        )}
      </main>
    </section>
  );
}
