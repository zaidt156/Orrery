import { useEffect, useRef, useState } from "react";
import {
  ChevronDown, ChevronRight, FileText, FolderKanban, MessageSquare, Plus, Save, Trash2, Upload, X,
} from "lucide-react";
import { SendIcon } from "../components/icons.jsx";
import {
  addProjectFiles, createProject, deleteProject, deleteProjectFile, getProject,
  listProjects, readFileAsAttachment, updateProject,
} from "../lib/api.js";

const emptyDraft = { name: "", description: "", instructions: "" };

export default function Projects({ onNavigate }) {
  const [projects, setProjects] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [draft, setDraft] = useState(emptyDraft);
  const [conversations, setConversations] = useState([]);
  const [files, setFiles] = useState([]);
  const [message, setMessage] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef(null);

  async function load(nextActive = activeId) {
    const data = await listProjects();
    setProjects(data.projects);
    const chosen = nextActive || data.projects[0]?.id || "";
    if (chosen) await openProject(chosen, data.projects);
    else {
      setActiveId("");
      setDraft(emptyDraft);
      setConversations([]);
      setFiles([]);
    }
  }

  useEffect(() => {
    load("").catch((e) => setErr(String(e.message || e)));
  }, []);

  async function openProject(id, known = projects) {
    setErr("");
    setActiveId(id);
    setDetailsOpen(false);
    setMessage("");
    const fallback = known.find((p) => p.id === id);
    if (fallback) setDraft({
      name: fallback.name || "",
      description: fallback.description || "",
      instructions: fallback.instructions || "",
    });
    const full = await getProject(id);
    setDraft({
      name: full.name || "",
      description: full.description || "",
      instructions: full.instructions || "",
    });
    setConversations(full.conversations || []);
    setFiles(full.files || []);
  }

  async function addProject() {
    setBusy(true);
    setErr("");
    try {
      const created = await createProject({ name: "New project", description: "", instructions: "" });
      window.dispatchEvent(new CustomEvent("orrery-projects-changed"));
      await load(created.id);
      setDetailsOpen(true);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function saveProject() {
    if (!activeId) return;
    setBusy(true);
    setErr("");
    try {
      const saved = await updateProject(activeId, draft);
      window.dispatchEvent(new CustomEvent("orrery-projects-changed"));
      // refresh sidebar names without losing the open file/chat state
      const data = await listProjects();
      setProjects(data.projects);
      setDraft({
        name: saved.name || "",
        description: saved.description || "",
        instructions: saved.instructions || "",
      });
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function removeProject() {
    if (!activeId) return;
    if (!window.confirm("Delete this project? Chats stay in Orrery, but they will no longer be grouped here.")) return;
    setBusy(true);
    setErr("");
    try {
      await deleteProject(activeId);
      window.dispatchEvent(new CustomEvent("orrery-projects-changed"));
      await load("");
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function onFilePick(e) {
    const picked = Array.from(e.target.files || []);
    e.target.value = "";
    if (!picked.length || !activeId) return;
    setUploading(true);
    setErr("");
    try {
      const attachments = await Promise.all(picked.map(readFileAsAttachment));
      const result = await addProjectFiles(activeId, attachments);
      setFiles(result.files || []);
      if (!result.added) {
        setErr("No readable text found in those files (images and binaries can't be searched yet).");
      }
    } catch (e2) {
      setErr(String(e2.message || e2));
    } finally {
      setUploading(false);
    }
  }

  async function removeFile(source) {
    if (!activeId) return;
    try {
      await deleteProjectFile(activeId, source);
      setFiles((f) => f.filter((item) => item.source !== source));
    } catch (e) {
      setErr(String(e.message || e));
    }
  }

  function openChat(id) {
    sessionStorage.setItem("orrery_open_conversation", id);
    onNavigate?.("chat");
  }

  function startProjectChat(id, firstMessage = "") {
    sessionStorage.setItem("orrery_new_project_chat", id);
    if (firstMessage.trim()) sessionStorage.setItem("orrery_project_first_message", firstMessage.trim());
    onNavigate?.("chat");
  }

  function sendMessage() {
    if (!activeId || !message.trim()) return;
    startProjectChat(activeId, message);
  }

  function onComposerKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <section className="view projects-view">
      <aside className="project-side">
        <button className="btn primary project-new" onClick={addProject} disabled={busy}>
          <Plus /> New project
        </button>
        <div className="project-list project-tree">
          {projects.length === 0 && <div className="convo-empty">No projects yet</div>}
          {projects.map((p) => (
            <div key={p.id} className={`project-node${p.id === activeId ? " active" : ""}`}>
              <button
                className="project-item"
                onClick={() => openProject(p.id).catch((e) => setErr(String(e.message || e)))}
              >
                <FolderKanban />
                <span>
                  <b>{p.name}</b>
                  <small>{p.conversation_count || 0} chats</small>
                </span>
              </button>
              {p.id === activeId && (
                <div className="project-children">
                  <button className="project-child new" onClick={() => startProjectChat(p.id)}>
                    <Plus /> New chat
                  </button>
                  {conversations.map((c) => (
                    <button key={c.id} className="project-child" onClick={() => openChat(c.id)}>
                      <MessageSquare />
                      <span>{c.title}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </aside>

      <main className="project-main">
        {!activeId ? (
          <div className="project-empty">
            <FolderKanban />
            <span>Create a project to group chats, add files, and carry project instructions into the model.</span>
          </div>
        ) : (
          <>
            <div className="project-head">
              <input
                className="project-title-input"
                value={draft.name}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                onBlur={saveProject}
                maxLength={160}
                placeholder="Project name"
              />
              <div className="grow" />
              <button className="btn ghost" onClick={() => setDetailsOpen((o) => !o)}>
                {detailsOpen ? <ChevronDown /> : <ChevronRight />} Details &amp; instructions
              </button>
              <button className="btn" onClick={saveProject} disabled={busy}><Save /> Save</button>
              <button className="btn ghost" onClick={removeProject} disabled={busy}><Trash2 /></button>
            </div>

            {detailsOpen && (
              <div className="project-details">
                <label>
                  Description
                  <textarea
                    value={draft.description}
                    onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                    maxLength={2000}
                    rows={2}
                    placeholder="What this project is about"
                  />
                </label>
                <label>
                  Standing instructions
                  <textarea
                    value={draft.instructions}
                    onChange={(e) => setDraft((d) => ({ ...d, instructions: e.target.value }))}
                    maxLength={8000}
                    rows={5}
                    placeholder="Instructions every chat in this project should follow"
                  />
                </label>
              </div>
            )}

            {err && <div className="chat-banner">{err}</div>}

            <div className="project-body">
              <div className="project-files-panel">
                <div className="section-label">
                  <span>Project files</span>
                  <button className="btn ghost sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
                    <Upload /> {uploading ? "Adding…" : "Add files"}
                  </button>
                </div>
                <input ref={fileRef} type="file" multiple hidden onChange={onFilePick} />
                {files.length === 0 ? (
                  <div className="project-muted">
                    Add files (PDF, Word, Excel, PowerPoint, text/code) and the chats here will answer from them.
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

              <div className="project-chat-panel">
                <div className="section-label"><span>Chats</span></div>
                <div className="project-chats-scroll">
                  {conversations.length === 0 ? (
                    <div className="project-muted">No chats yet. Start one below — it uses this project's files and instructions.</div>
                  ) : (
                    conversations.map((c) => (
                      <button key={c.id} className="project-chat" onClick={() => openChat(c.id)}>
                        <MessageSquare />
                        <span>
                          <b>{c.title}</b>
                          <small>{c.model}</small>
                        </span>
                      </button>
                    ))
                  )}
                </div>
                <div className="project-composer">
                  <textarea
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={onComposerKey}
                    rows={2}
                    placeholder="Start a new chat in this project…"
                  />
                  <button className="btn primary send" onClick={sendMessage} disabled={!message.trim()}>
                    <SendIcon /> Start
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </main>
    </section>
  );
}
