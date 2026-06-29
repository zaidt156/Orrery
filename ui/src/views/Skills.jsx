import { useEffect, useRef, useState } from "react";
import { Plus, Save, Search, Sparkles, Trash2, Upload } from "lucide-react";
import { createSkill, deleteSkill, listSkills, updateSkill, uploadSkill } from "../lib/api.js";

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
  const [query, setQuery] = useState("");
  const fileRef = useRef(null);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? items.filter((s) => (s.name || "").toLowerCase().includes(q) || (s.triggers || "").toLowerCase().includes(q))
    : items;

  async function load(nextActive) {
    const data = await listSkills();
    setItems(data.skills);
    const chosen = nextActive || (data.skills.find((s) => s.id === activeId)?.id) || "";
    if (chosen) openItem(chosen, data.skills);
    else { setActiveId(""); setDraft(emptyDraft); }
  }
  useEffect(() => { load("").catch((e) => setErr(String(e.message || e))); }, []);

  function openItem(id, known = items) {
    setErr(""); setActiveId(id);
    const it = known.find((s) => s.id === id);
    if (it) setDraft({ name: it.name || "", triggers: it.triggers || "", body: it.body || "", always: !!it.always, enabled: !!it.enabled });
  }

  async function addItem() {
    setBusy(true); setErr("");
    try {
      const created = await createSkill({ name: "New skill", body: "Describe what the model should do…", triggers: "", always: false, enabled: true });
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
        <button className="btn ghost sm" onClick={() => fileRef.current?.click()} disabled={busy} style={{ width: "100%", justifyContent: "center" }}>
          <Upload /> Upload .md skill
        </button>
        <input ref={fileRef} type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden onChange={onFilePick} />
        <div className="ontology-search">
          <Search />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search skills…" />
        </div>
        <div className="project-list project-tree">
          {filtered.length === 0 && <div className="convo-empty">{items.length ? "No matches" : "No skills yet"}</div>}
          {filtered.map((s) => (
            <div key={s.id} className={`project-node${s.id === activeId ? " active" : ""}`}>
              <button className="project-item" onClick={() => openItem(s.id)}>
                <Sparkles />
                <span>
                  <b>{s.name}</b>
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
          <div className="project-empty">
            <Sparkles />
            <span>Create or upload a skill: a reusable instruction playbook the model reads before answering. Add trigger phrases (or mark it always‑on) and enable it.</span>
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

            <div className="project-details">
              <label>
                Trigger phrases (comma or newline separated; leave empty if “always on”)
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
              <div className="project-files-panel" style={{ width: "100%" }}>
                <div className="section-label"><span>Skill instructions</span></div>
                <textarea
                  className="skill-body"
                  value={draft.body}
                  onChange={(e) => setDraft((d) => ({ ...d, body: e.target.value }))}
                  placeholder="Write the playbook the model should follow when this skill applies…"
                />
              </div>
            </div>
          </>
        )}
      </main>
    </section>
  );
}
