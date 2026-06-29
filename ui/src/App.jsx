import { lazy, Suspense, useEffect, useState } from "react";
import {
  Bot,
  Brain,
  Database,
  FolderKanban,
  HardDriveDownload,
  Images,
  LayoutDashboard,
  MessageSquare,
  Settings as SettingsIcon,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import { getAdmin, getBranding, getHealth } from "./lib/api.js";
import { Logo } from "./components/icons.jsx";

function BrandHeader() {
  const [b, setB] = useState(null);
  useEffect(() => {
    let alive = true;
    getBranding().then((x) => alive && setB(x)).catch(() => {});
    const update = (event) => {
      if (alive && event.detail) setB(event.detail);
    };
    window.addEventListener("orrery-branding-changed", update);
    return () => {
      alive = false;
      window.removeEventListener("orrery-branding-changed", update);
    };
  }, []);
  if (!b || !b.enabled || (!b.name && !b.logo)) return null;
  return (
    <header className="brand-header">
      {b.logo && <img className="brand-logo" src={b.logo} alt={b.name || "logo"} />}
      <div className="brand-text">
        {b.name && <div className="brand-name">{b.name}</div>}
        {b.tagline && <div className="brand-tagline">{b.tagline}</div>}
        {b.details && <div className="brand-details">{b.details}</div>}
      </div>
    </header>
  );
}

const Chat = lazy(() => import("./views/Chat.jsx"));
const Data = lazy(() => import("./views/Data.jsx"));
const Dashboards = lazy(() => import("./views/Dashboards.jsx"));
const Projects = lazy(() => import("./views/Projects.jsx"));
const Ontology = lazy(() => import("./views/Ontology.jsx"));
const Skills = lazy(() => import("./views/Skills.jsx"));
const Automations = lazy(() => import("./views/Automations.jsx"));
const Agents = lazy(() => import("./views/Agents.jsx"));
const Media = lazy(() => import("./views/Media.jsx"));
const LocalModels = lazy(() => import("./views/LocalModels.jsx"));
const Settings = lazy(() => import("./views/Settings.jsx"));
const Admin = lazy(() => import("./views/Admin.jsx"));

// `feature` ties a tab to an admin flag — when that feature is turned off, the tab is hidden.
const TABS = [
  { key: "chat", label: "Chat", Icon: MessageSquare, View: Chat },
  { key: "projects", label: "Projects", Icon: FolderKanban, View: Projects },
  { key: "data", label: "Data", Icon: Database, View: Data },
  { key: "ontology", label: "Ontology", Icon: Brain, View: Ontology, feature: "ontology" },
  { key: "skills", label: "Skills", Icon: Sparkles, View: Skills },
  { key: "dash", label: "Dashboards", Icon: LayoutDashboard, View: Dashboards },
  { key: "auto", label: "Automations", Icon: Workflow, View: Automations, feature: "automations" },
  { key: "agents", label: "Agents", Icon: Bot, View: Agents, feature: "agents" },
  { key: "media", label: "Media Hub", Icon: Images, View: Media, feature: "media" },
  { key: "local", label: "Local Models", Icon: HardDriveDownload, View: LocalModels },
  { key: "admin", label: "Admin", Icon: ShieldCheck, View: Admin },
  { key: "settings", label: "Settings", Icon: SettingsIcon, View: Settings },
];

const INITIAL_TAB = new URLSearchParams(window.location.search).get("tab");

export default function App() {
  const [active, setActive] = useState(
    TABS.some((t) => t.key === INITIAL_TAB) ? INITIAL_TAB : "chat"
  );
  const [db, setDb] = useState("checking"); // checking | ok | error | down
  const [features, setFeatures] = useState(null); // null until loaded → show all tabs

  useEffect(() => {
    let alive = true;
    const check = () =>
      getHealth()
        .then((h) => alive && setDb(h.database === "ok" ? "ok" : "error"))
        .catch(() => alive && setDb("down"));
    check();
    const id = setInterval(check, 15000);
    const loadFeatures = () =>
      getAdmin()
        .then((s) => alive && setFeatures(Object.fromEntries((s.features || []).map((f) => [f.name, f.enabled]))))
        .catch(() => {});
    loadFeatures();
    window.addEventListener("orrery-features-changed", loadFeatures);
    return () => {
      alive = false;
      clearInterval(id);
      window.removeEventListener("orrery-features-changed", loadFeatures);
    };
  }, []);

  const visibleTabs = TABS.filter((t) => !t.feature || !features || features[t.feature] !== false);
  const ActiveView = (visibleTabs.find((t) => t.key === active) || visibleTabs[0]).View;
  const pulseClass = db === "ok" ? "" : db === "error" ? "amber" : db === "down" ? "red" : "amber";
  const dbTitle =
    db === "ok" ? "Database connected"
    : db === "error" ? "Backend up — database error"
    : db === "down" ? "Backend unreachable"
    : "Connecting…";

  return (
    <div className="app">
      <BrandHeader />
      <div className="app-body">
        <nav className="rail" aria-label="Main navigation">
          <div className="logo" title="Orrery"><Logo /></div>
          {visibleTabs.map(({ key, label, Icon }) => (
            <button
              key={key}
              className={`tab${key === active ? " active" : ""}`}
              aria-label={label}
              onClick={() => setActive(key)}
            >
              <Icon />
            </button>
          ))}
          <div className="spacer" />
          <div className="db-status" title={dbTitle}>
            <div className={`pulse ${pulseClass}`} />
            <span>DATABASE</span>
          </div>
        </nav>
        <Suspense fallback={<section className="view"><div className="s-sub">Loading...</div></section>}>
          <ActiveView onNavigate={setActive} />
        </Suspense>
      </div>
    </div>
  );
}
