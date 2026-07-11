import { useEffect, useMemo, useRef, useState } from "react";
import { Brain, Database, FolderKanban, LayoutDashboard, LayoutGrid, MessageSquare, Search, Sparkles } from "lucide-react";
import {
  listCollections, listConversations, listDashboards, listOntologies, listProjects, listSkills,
} from "../lib/api.js";

// Concept top-bar global search (the reference's "Search anything… ⌘K"). Client-side over the
// workspace lists; Ctrl/Cmd+K focuses it from anywhere. Selecting navigates to the owning tab
// (conversations also ask Chat to open that thread via a session handoff).
const GROUPS = [
  { key: "chats", label: "Chats", tab: "chat", Icon: MessageSquare },
  { key: "projects", label: "Projects", tab: "projects", Icon: FolderKanban },
  { key: "dashboards", label: "Dashboards", tab: "dash", Icon: LayoutDashboard },
  { key: "ontologies", label: "Ontologies", tab: "ontology", Icon: Brain },
  { key: "collections", label: "Collections", tab: "data", Icon: Database },
  { key: "skills", label: "Skills", tab: "skills", Icon: Sparkles },
  { key: "tabs", label: "Go to", tab: null, Icon: LayoutGrid },
];

export default function TopSearch({ tabs = [], onNavigate }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(null); // {chats:[{id,name}],...} — loaded on first focus
  const boxRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e) {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("mousedown", onClick); };
  }, []);

  async function ensureIndex() {
    if (index) return;
    const grab = (p, pick) => p.then(pick).catch(() => []);
    const [chats, projects, dashboards, ontologies, collections, skills] = await Promise.all([
      grab(listConversations(200), (r) => (r.conversations || []).map((c) => ({ id: c.id, name: c.title || "Untitled chat" }))),
      grab(listProjects(), (r) => (r.projects || []).map((p) => ({ id: p.id, name: p.name || "Project" }))),
      grab(listDashboards(), (r) => (r.dashboards || []).map((d) => ({ id: d.id, name: d.name || d.title || "Dashboard" }))),
      grab(listOntologies(), (r) => (r.ontologies || []).map((o) => ({ id: o.id, name: o.name }))),
      grab(listCollections(), (r) => (r.collections || []).map((c) => ({ id: c.id, name: c.name }))),
      grab(listSkills(), (r) => (r.skills || []).map((s) => ({ id: s.id, name: s.name }))),
    ]);
    setIndex({ chats, projects, dashboards, ontologies, collections, skills });
  }

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return [];
    const out = [];
    for (const g of GROUPS) {
      const pool = g.key === "tabs"
        ? tabs.map((t) => ({ id: t.key, name: t.label, tab: t.key }))
        : (index?.[g.key] || []);
      const hits = pool.filter((item) => item.name?.toLowerCase().includes(needle)).slice(0, 4);
      if (hits.length) out.push({ group: g, hits });
    }
    return out;
  }, [q, index, tabs]);

  function pick(group, item) {
    setOpen(false);
    setQ("");
    if (group.key === "chats") sessionStorage.setItem("orrery_open_conversation", item.id);
    onNavigate?.(group.key === "tabs" ? item.tab : group.tab);
  }

  return (
    <div className="topsearch" ref={boxRef}>
      <Search className="topsearch-icon" />
      <input
        ref={inputRef}
        value={q}
        placeholder="Search anything…"
        onFocus={() => { setOpen(true); ensureIndex(); }}
        onChange={(e) => { setQ(e.target.value); ensureIndex(); }}
        aria-label="Search the workspace"
      />
      <span className="topsearch-kbd">Ctrl K</span>
      {open && q.trim() && (
        <div className="topsearch-pop surface-3" role="listbox">
          {results.length === 0 && <div className="topsearch-empty">{index ? "No matches" : "Searching…"}</div>}
          {results.map(({ group, hits }) => (
            <div key={group.key} className="topsearch-group">
              <div className="topsearch-glabel">{group.label}</div>
              {hits.map((item) => (
                <button key={item.id} type="button" className="topsearch-hit" onClick={() => pick(group, item)}>
                  <group.Icon />
                  <span>{item.name}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
