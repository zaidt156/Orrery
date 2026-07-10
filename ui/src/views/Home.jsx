import { useEffect, useState } from "react";
import {
  ArrowRight, Bot, Brain, Database, FolderKanban, HardDriveDownload,
  LayoutDashboard, MessageSquare, Workflow,
} from "lucide-react";
import PageHero from "../components/PageHero.jsx";
import StatCard from "../components/StatCard.jsx";
import { dayBuckets } from "../lib/spark.js";
import {
  getDefaults, getLocalModels, getModels, getProviders, getTasks,
  listCollections, listConversations, listDataConnections, listDatasets,
  listOntologies, listProjects,
} from "../lib/api.js";

const QUICK_ACTIONS = [
  { key: "chat", icon: MessageSquare, title: "New chat", sub: "Ask, build, and automate in one thread" },
  { key: "data", icon: Database, title: "Connect data", sub: "PostgreSQL sources and document collections" },
  { key: "dash", icon: LayoutDashboard, title: "Build a dashboard", sub: "Describe it — the SQL and charts are saved" },
  { key: "local", icon: HardDriveDownload, title: "Local models", sub: "Run models fully on this machine" },
];

function relTime(stamp) {
  const t = Date.parse(stamp);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

const TASK_DOT = { done: "", completed: "", running: "amber", error: "red", failed: "red", interrupted: "red" };

export default function Home({ onNavigate }) {
  const [stats, setStats] = useState({});
  const [tasks, setTasks] = useState(null);
  const [system, setSystem] = useState({});

  useEffect(() => {
    let alive = true;
    const grab = (p, pick) => p.then(pick).catch(() => null);
    Promise.all([
      grab(listConversations(), (r) => r.conversations || []),
      grab(listProjects(), (r) => r.projects || []),
      grab(listDataConnections(), (r) => r.connections || []),
      grab(listDatasets(), (r) => r.datasets || []),
      grab(listCollections(), (r) => r.collections || []),
      grab(listOntologies(), (r) => r.ontologies || []),
      grab(getLocalModels(), (r) => r || {}),
      grab(getTasks(), (r) => r.tasks || []),
      grab(getDefaults(), (r) => r || {}),
      grab(getModels(), (r) => r.models || []),
      grab(getProviders(), (r) => r || {}),
    ]).then(([convos, projects, connections, datasets, collections, ontologies, local, taskRows, defaults, models, providers]) => {
      if (!alive) return;
      setStats({
        convos, projects, connections, datasets, collections, ontologies,
        localModels: local?.models || [],
      });
      setTasks(taskRows || []);
      const hit = (models || []).find((m) => m.id === defaults?.model);
      setSystem({
        model: hit?.label || defaults?.model || "",
        providers: providers ? Object.values(providers).filter((p) => p?.configured).length : 0,
      });
    });
    return () => { alive = false; };
  }, []);

  const s = stats;
  const taskStamps = (tasks || []).map((t) => t.created_at);

  return (
    <section className="view">
      <div className="home-wrap">
        <PageHero
          title="Private AI workspace"
          subtitle="Bring your models, files, databases, and workflows together in one secure, local environment."
          badges={["100% local first", "Your data, your control", "Open source"]}
        />

        <div className="section-label">Quick actions</div>
        <div className="qa-row">
          {QUICK_ACTIONS.map(({ key, icon: Icon, title, sub }) => (
            <button key={key} type="button" className="qa-card surface-2" onClick={() => onNavigate?.(key)}>
              <span className="icon-chip surface-3"><Icon /></span>
              <span className="qa-text"><b>{title}</b><span>{sub}</span></span>
              <ArrowRight className="qa-arrow" />
            </button>
          ))}
        </div>

        <div className="section-label">Workspace</div>
        <div className="stat-cards">
          <StatCard icon={MessageSquare} label="Conversations" value={s.convos?.length}
            sub={s.convos?.length ? `latest ${relTime(s.convos[0]?.updated_at)}` : "start your first chat"}
            series={dayBuckets((s.convos || []).map((c) => c.updated_at))} onClick={() => onNavigate?.("chat")} />
          <StatCard icon={FolderKanban} label="Projects" value={s.projects?.length}
            series={dayBuckets((s.projects || []).map((p) => p.created_at))} onClick={() => onNavigate?.("projects")} />
          <StatCard icon={Database} label="Data sources" value={(s.connections?.length ?? 0) + (s.datasets?.length ?? 0)}
            sub={s.connections?.length ? `${s.connections.length} live connections` : "connect PostgreSQL or files"}
            onClick={() => onNavigate?.("data")} />
          <StatCard icon={Brain} label="Collections" value={(s.collections?.length ?? 0) + (s.ontologies?.length ?? 0)}
            sub={s.ontologies?.length ? `${s.ontologies.length} ontologies` : "searchable document sets"}
            onClick={() => onNavigate?.("ontology")} />
          <StatCard icon={HardDriveDownload} label="Local models" value={s.localModels?.length}
            sub="fully on this machine" onClick={() => onNavigate?.("local")} />
        </div>

        <div className="home-cols">
          <div className="activity-card surface-2">
            <div className="home-card-head">
              <b>Recent activity</b>
              <span>{tasks == null ? "loading…" : `${tasks.length} recorded runs`}</span>
            </div>
            {tasks != null && tasks.length === 0 && (
              <div className="home-empty">Task runs, file builds, and agent work will show up here.</div>
            )}
            {(tasks || []).slice(0, 8).map((t) => (
              <div key={t.id} className="activity-row" title={t.detail || ""}>
                <span className="icon-chip surface-3"><Workflow /></span>
                <span className="activity-text">
                  <b>{t.title || t.kind || "Task"}</b>
                  <span>{relTime(t.created_at)}</span>
                </span>
                <i className={`pulse ${TASK_DOT[t.status] ?? "amber"}`} title={t.status} />
              </div>
            ))}
          </div>

          <div className="system-card surface-2">
            <div className="home-card-head"><b>System</b></div>
            <div className="system-row"><span className="icon-chip surface-3"><Bot /></span>
              <span className="activity-text"><b>Default model</b><span>{system.model || "pick one in Chat"}</span></span></div>
            <div className="system-row"><span className="icon-chip surface-3"><Database /></span>
              <span className="activity-text"><b>Database</b><span>PostgreSQL — see the sidebar check</span></span></div>
            <div className="system-row"><span className="icon-chip surface-3"><Brain /></span>
              <span className="activity-text"><b>Providers connected</b><span>{system.providers ?? "…"}</span></span></div>
          </div>
        </div>
      </div>
    </section>
  );
}
