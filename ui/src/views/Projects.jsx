import { useEffect, useState } from "react";
import { FolderKanban, MessageSquare, Plus, Save, Trash2 } from "lucide-react";
import { createProject, deleteProject, getProject, listProjects, updateProject } from "../lib/api.js";

const emptyDraft = { name: "", description: "", instructions: "" };

export default function Projects({ onNavigate }) {
  const [projects, setProjects] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [draft, setDraft] = useState(emptyDraft);
  const [conversations, setConversations] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function load(nextActive = activeId) {
    const data = await listProjects();
    setProjects(data.projects);
    const chosen = nextActive || data.projects[0]?.id || "";
    if (chosen) await openProject(chosen, data.projects);
    else {
      setActiveId("");
      setDraft(emptyDraft);
      setConversations([]);
    }
  }

  useEffect(() => {
    load("").catch((e) => setErr(String(e.message || e)));
  }, []);

  async function openProject(id, known = projects) {
    setErr("");
    setActiveId(id);
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
  }

  async function addProject() {
    setBusy(true);
    setErr("");
    try {
      const created = await createProject({ name: "New project", description: "", instructions: "" });
      window.dispatchEvent(new CustomEvent("orrery-projects-changed"));
      await load(created.id);
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
      await load(saved.id);
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

  function openChat(id) {
    sessionStorage.setItem("orrery_open_conversation", id);
    onNavigate?.("chat");
  }

  function startProjectChat(id) {
    sessionStorage.setItem("orrery_new_project_chat", id);
    onNavigate?.("chat");
  }

  const active = projects.find((p) => p.id === activeId);

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
              <div className="project-children">
                <button className="project-child new" onClick={() => startProjectChat(p.id)}>
                  <Plus /> New chat
                </button>
                {(p.conversations || []).map((c) => (
                  <button key={c.id} className="project-child" onClick={() => openChat(c.id)}>
                    <MessageSquare />
                    <span>{c.title}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </aside>

      <main className="project-main">
        <div className="project-toolbar">
          <span className="view-title">{active?.name || "Projects"}</span>
          <div className="grow" />
          {activeId && (
            <>
              <button className="btn primary" onClick={() => startProjectChat(activeId)} disabled={busy}>
                <MessageSquare /> New chat
              </button>
              <button className="btn" onClick={saveProject} disabled={busy}><Save /> Save</button>
              <button className="btn ghost" onClick={removeProject} disabled={busy}><Trash2 /> Delete</button>
            </>
          )}
        </div>

        {err && <div className="chat-banner">{err}</div>}

        {!activeId ? (
          <div className="project-empty">
            <FolderKanban />
            <span>Create a project to group chats and carry project instructions into the model.</span>
          </div>
        ) : (
          <div className="project-editor">
            <label>
              Name
              <input
                className="search"
                value={draft.name}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                maxLength={160}
              />
            </label>
            <label>
              Description
              <textarea
                value={draft.description}
                onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                maxLength={2000}
                rows={3}
              />
            </label>
            <label>
              Standing instructions
              <textarea
                value={draft.instructions}
                onChange={(e) => setDraft((d) => ({ ...d, instructions: e.target.value }))}
                maxLength={8000}
                rows={8}
              />
            </label>

            <div className="project-chats">
              <div className="section-label">Project chats</div>
              {conversations.length === 0 && (
                <div className="project-muted">
                  No chats attached yet. Start a new chat inside this project to keep its instructions and context.
                </div>
              )}
              {conversations.map((c) => (
                <button key={c.id} className="project-chat" onClick={() => openChat(c.id)}>
                  <MessageSquare />
                  <span>
                    <b>{c.title}</b>
                    <small>{c.model}</small>
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </main>
    </section>
  );
}
