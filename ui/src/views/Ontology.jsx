import { useEffect, useRef, useState } from "react";
import { Brain, FileText, Plus, Save, Trash2, Upload, X } from "lucide-react";
import {
  addOntologyFiles, createOntology, deleteOntology, deleteOntologyFile, listOntologies,
  listOntologyFiles, readFileAsAttachment, updateOntology,
} from "../lib/api.js";

const emptyDraft = { name: "", description: "" };

// Ontology tab: the user builds reusable knowledge bases from their own files. A "connected" ontology
// is automatically searched as standing context in every chat (alongside data + project files).
export default function Ontology() {
  const [items, setItems] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [draft, setDraft] = useState(emptyDraft);
  const [connected, setConnected] = useState(false);
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef(null);

  async function load(nextActive) {
    const data = await listOntologies();
    setItems(data.ontologies);
    const chosen = nextActive || data.ontologies[0]?.id || "";
    if (chosen) await openItem(chosen, data.ontologies);
    else { setActiveId(""); setDraft(emptyDraft); setConnected(false); setFiles([]); }
  }

  useEffect(() => { load("").catch((e) => setErr(String(e.message || e))); }, []);

  async function refreshList() {
    const data = await listOntologies();
    setItems(data.ontologies);
  }

  async function openItem(id, known = items) {
    setErr("");
    setActiveId(id);
    const it = known.find((o) => o.id === id);
    if (it) { setDraft({ name: it.name || "", description: it.description || "" }); setConnected(!!it.connected); }
    const f = await listOntologyFiles(id);
    setFiles(f.files || []);
  }

  async function addItem() {
    setBusy(true); setErr("");
    try {
      const created = await createOntology("New ontology", "");
      await load(created.id);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function save() {
    if (!activeId) return;
    setBusy(true); setErr("");
    try { await updateOntology(activeId, { name: draft.name, description: draft.description }); await refreshList(); }
    catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function toggleConnected() {
    if (!activeId) return;
    const next = !connected;
    setConnected(next);
    try { await updateOntology(activeId, { connected: next }); await refreshList(); }
    catch (e) { setConnected(!next); setErr(String(e.message || e)); }
  }

  async function remove() {
    if (!activeId || !window.confirm("Delete this ontology and its files? Chats will stop using it as context.")) return;
    setBusy(true); setErr("");
    try { await deleteOntology(activeId); await load(""); }
    catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function onFilePick(e) {
    const picked = Array.from(e.target.files || []);
    e.target.value = "";
    if (!picked.length || !activeId) return;
    setUploading(true); setErr("");
    try {
      const atts = await Promise.all(picked.map(readFileAsAttachment));
      const res = await addOntologyFiles(activeId, atts);
      setFiles(res.files || []);
      await refreshList();
      if (!res.added) setErr("No readable text found in those files (images and binaries can't be searched yet).");
    } catch (e2) { setErr(String(e2.message || e2)); } finally { setUploading(false); }
  }

  async function removeFile(source) {
    try { await deleteOntologyFile(activeId, source); setFiles((f) => f.filter((x) => x.source !== source)); await refreshList(); }
    catch (e) { setErr(String(e.message || e)); }
  }

  return (
    <section className="view projects-view">
      <aside className="project-side">
        <button className="btn primary project-new" onClick={addItem} disabled={busy}><Plus /> New ontology</button>
        <div className="project-list project-tree">
          {items.length === 0 && <div className="convo-empty">No ontologies yet</div>}
          {items.map((o) => (
            <div key={o.id} className={`project-node${o.id === activeId ? " active" : ""}`}>
              <button className="project-item" onClick={() => openItem(o.id).catch((e) => setErr(String(e.message || e)))}>
                <Brain />
                <span>
                  <b>{o.name}</b>
                  <small>{o.chunks} chunks{o.connected ? " · connected" : ""}</small>
                </span>
              </button>
            </div>
          ))}
        </div>
      </aside>

      <main className="project-main">
        {!activeId ? (
          <div className="project-empty">
            <Brain />
            <span>Create an ontology: add your own files as reusable knowledge, then connect it so every chat uses it as context.</span>
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
                placeholder="Ontology name"
              />
              <div className="grow" />
              <span className="rag-toggle" title="Connect so this ontology is used as context in every chat">
                Connected
                <span className={`toggle${connected ? " on" : ""}`} role="switch" aria-checked={connected} tabIndex={0} onClick={toggleConnected} />
              </span>
              <button className="btn" onClick={save} disabled={busy}><Save /> Save</button>
              <button className="btn ghost" onClick={remove} disabled={busy}><Trash2 /></button>
            </div>

            <div className="project-details">
              <label>
                Description
                <textarea
                  value={draft.description}
                  onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                  rows={2}
                  maxLength={2000}
                  placeholder="What knowledge this ontology holds"
                />
              </label>
            </div>

            {err && <div className="chat-banner">{err}</div>}

            <div className="project-body">
              <div className="project-files-panel" style={{ width: "100%" }}>
                <div className="section-label">
                  <span>Knowledge files</span>
                  <button className="btn ghost sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
                    <Upload /> {uploading ? "Adding…" : "Add files"}
                  </button>
                </div>
                <input ref={fileRef} type="file" multiple hidden onChange={onFilePick} />
                {files.length === 0 ? (
                  <div className="project-muted">
                    Add files (PDF, Word, Excel, PowerPoint, text/code). When connected, their content is used as context in every chat.
                  </div>
                ) : (
                  <div className="project-file-list">
                    {files.map((f) => (
                      <div key={f.source} className="project-file">
                        <FileText />
                        <span className="project-file-name">{f.source}</span>
                        <small>{f.chunks}</small>
                        <button className="icon-btn" title="Remove" onClick={() => removeFile(f.source)}><X /></button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </section>
  );
}
