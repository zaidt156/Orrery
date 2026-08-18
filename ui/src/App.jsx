import { lazy, Suspense, useEffect, useState } from "react";
import {
  Bot,
  Brain,
  Database,
  FolderKanban,
  HardDriveDownload,
  House,
  Images,
  LayoutDashboard,
  MessageSquare,
  Settings as SettingsIcon,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import { getAdmin, getAppUpdate, getBranding, getDefaults, getHealth, getModels, getTeam } from "./lib/api.js";
import { Logo } from "./components/icons.jsx";
import FirstRunSetup from "./components/FirstRunSetup.jsx";
import TopSearch from "./components/TopSearch.jsx";
import ConnectionCheck from "./components/ConnectionCheck.jsx";
import { useAppearance } from "./components/AppearanceProvider.jsx";

// Concept top bar: workspace identity on the left (custom branding when set), the workspace's
// real default model as a chip on the right. Purely informational — model/effort are changed in
// Chat and Settings, so nothing here pretends to be a control.
function TopBar({ interfaceMode, tabs = [], onNavigate }) {
  const [b, setB] = useState(null);
  const [modelLabel, setModelLabel] = useState("");
  useEffect(() => {
    let alive = true;
    getBranding().then((x) => alive && setB(x)).catch(() => {});
    const loadModel = () =>
      Promise.all([getDefaults().catch(() => ({})), getModels().catch(() => ({ models: [] }))])
        .then(([d, m]) => {
          if (!alive) return;
          const hit = (m.models || []).find((x) => x.id === d.model);
          setModelLabel(hit?.label || d.model || "");
        });
    loadModel();
    const update = (event) => { if (alive && event.detail) setB(event.detail); };
    window.addEventListener("orrery-branding-changed", update);
    window.addEventListener("orrery-models-changed", loadModel);
    return () => {
      alive = false;
      window.removeEventListener("orrery-branding-changed", update);
      window.removeEventListener("orrery-models-changed", loadModel);
    };
  }, []);
  const branded = b?.enabled && (b.name || b.logo);
  if (interfaceMode === "classic" && !branded) return null;
  return (
    <header className={`topbar${interfaceMode === "classic" ? " classic-brand" : ""}`}>
      <div className="topbar-left">
        {branded && b.logo && <img className="brand-logo" src={b.logo} alt={b.name || "logo"} />}
        <div className="brand-text">
          <div className="brand-name">{branded && b.name ? b.name : "Personal workspace"}</div>
          {branded && b.tagline ? <div className="brand-tagline">{b.tagline}</div> : null}
        </div>
      </div>
      {interfaceMode === "concept" && <TopSearch tabs={tabs} onNavigate={onNavigate} />}
      {interfaceMode === "concept" && modelLabel && (
        <div className="provider-pill" title="Workspace default model — change it in Settings or per chat">
          <i className="pulse-dot" />
          <span>{modelLabel}</span>
        </div>
      )}
    </header>
  );
}

// Each view is its own chunk, so the first paint does not carry the whole workspace. Keeping the
// import functions by name lets us ALSO warm them while the browser is idle (see prefetchViews
// below) - without that, every first visit to a tab waits on a network round trip and a parse,
// which is what made switching tabs feel slow even once the backend was answering in milliseconds.
const VIEW_LOADERS = {
  home: () => import("./views/Home.jsx"),
  chat: () => import("./views/Chat.jsx"),
  data: () => import("./views/Data.jsx"),
  dash: () => import("./views/Dashboards.jsx"),
  projects: () => import("./views/Projects.jsx"),
  ontology: () => import("./views/Ontology.jsx"),
  skills: () => import("./views/Skills.jsx"),
  auto: () => import("./views/Automations.jsx"),
  agents: () => import("./views/Agents.jsx"),
  media: () => import("./views/Media.jsx"),
  local: () => import("./views/LocalModels.jsx"),
  settings: () => import("./views/Settings.jsx"),
  admin: () => import("./views/Admin.jsx"),
  lock: () => import("./views/Lock.jsx"),
};

// Warmed one at a time, cheapest-to-reach first, each waiting for the next idle slot so this never
// competes with the tab the user is actually looking at. Dashboards is last: it is by far the
// largest chunk, and paying for it early would be the one prefetch a user could feel.
const PREFETCH_ORDER = ["chat", "projects", "data", "settings", "skills", "agents",
                        "ontology", "local", "auto", "admin", "media", "dash"];

function prefetchViews() {
  const whenIdle = window.requestIdleCallback || ((fn) => window.setTimeout(fn, 250));
  let stopped = false;
  const warm = (i) => {
    if (stopped || i >= PREFETCH_ORDER.length) return;
    const load = VIEW_LOADERS[PREFETCH_ORDER[i]];
    Promise.resolve(load ? load() : null)
      .catch(() => {})           // a failed warm must never surface; the real visit will retry
      .then(() => whenIdle(() => warm(i + 1)));
  };
  whenIdle(() => warm(0));
  return () => { stopped = true; };
}

const Home = lazy(VIEW_LOADERS.home);
const Chat = lazy(VIEW_LOADERS.chat);
const Data = lazy(VIEW_LOADERS.data);
const Dashboards = lazy(VIEW_LOADERS.dash);
const Projects = lazy(VIEW_LOADERS.projects);
const Ontology = lazy(VIEW_LOADERS.ontology);
const Skills = lazy(VIEW_LOADERS.skills);
const Automations = lazy(VIEW_LOADERS.auto);
const Agents = lazy(VIEW_LOADERS.agents);
const Media = lazy(VIEW_LOADERS.media);
const LocalModels = lazy(VIEW_LOADERS.local);
const Settings = lazy(VIEW_LOADERS.settings);
const Admin = lazy(VIEW_LOADERS.admin);
const Lock = lazy(VIEW_LOADERS.lock);

// `feature` ties a tab to an admin flag — when that feature is turned off, the tab is hidden.
const TABS = [
  { key: "home", label: "Home", Icon: House, View: Home },
  { key: "chat", label: "Chat", Icon: MessageSquare, View: Chat },
  { key: "projects", label: "Projects", Icon: FolderKanban, View: Projects },
  { key: "data", label: "Data", Icon: Database, View: Data },
  { key: "ontology", label: "Ontology", Icon: Brain, View: Ontology, feature: "ontology" },
  { key: "skills", label: "Skills", Icon: Sparkles, View: Skills },
  { key: "dash", label: "Dashboards", Icon: LayoutDashboard, View: Dashboards, feature: "dashboards" },
  { key: "auto", label: "Automations", Icon: Workflow, View: Automations, feature: "automations" },
  { key: "agents", label: "Agents", Icon: Bot, View: Agents, feature: "agents" },
  { key: "media", label: "Media Hub", Icon: Images, View: Media, feature: "media" },
  { key: "local", label: "Local Models", Icon: HardDriveDownload, View: LocalModels },
  { key: "admin", label: "Admin", Icon: ShieldCheck, View: Admin },
  { key: "settings", label: "Settings", Icon: SettingsIcon, View: Settings },
];

const INITIAL_TAB = new URLSearchParams(window.location.search).get("tab");

export default function App() {
  const { interfaceMode } = useAppearance();

  useEffect(prefetchViews, []);
  const [active, setActive] = useState(() => {
    const requested = TABS.some((t) => t.key === INITIAL_TAB) ? INITIAL_TAB : null;
    if (interfaceMode === "classic") return requested && requested !== "home" ? requested : "chat";
    return requested || "home";
  });
  const [db, setDb] = useState("checking"); // checking | ok | error | down
  const [appVersion, setAppVersion] = useState("");
  const [features, setFeatures] = useState(null); // null until loaded → show all tabs
  const [teamState, setTeamState] = useState(null); // null until loaded; {team_mode, locked, user}
  const [update, setUpdate] = useState(null); // {latest_version, url} when a newer release exists

  useEffect(() => {
    let alive = true;
    const check = () =>
      getHealth()
        .then((h) => {
          if (!alive) return;
          setDb(h.database === "ok" ? "ok" : "error");
          if (h.version) setAppVersion(h.version);
        })
        .catch(() => alive && setDb("down"));
    check();
    const id = setInterval(check, 15000);
    const loadFeatures = () =>
      getAdmin()
        .then((s) => alive && setFeatures(Object.fromEntries((s.features || []).map((f) => [f.name, f.effective ?? f.enabled]))))
        .catch(() => {});
    const loadTeam = () => getTeam().then((s) => alive && setTeamState(s)).catch(() => alive && setTeamState({ team_mode: false, locked: false }));
    loadFeatures();
    loadTeam();
    // prompt once per session when a newer release exists (dismissable; details in Settings → Updates)
    getAppUpdate()
      .then((u) => {
        if (alive && u?.update_available && !sessionStorage.getItem("orrery_update_dismissed")) {
          setUpdate({ version: u.latest_version, url: u.release_url });
        }
      })
      .catch(() => {});
    window.addEventListener("orrery-features-changed", loadFeatures);
    window.addEventListener("orrery-team-changed", loadTeam);
    return () => {
      alive = false;
      clearInterval(id);
      window.removeEventListener("orrery-features-changed", loadFeatures);
      window.removeEventListener("orrery-team-changed", loadTeam);
    };
  }, []);

  useEffect(() => {
    if (interfaceMode === "classic" && active === "home") setActive("chat");
  }, [active, interfaceMode]);

  // Joined to a team database without a valid key → hold everything behind the lock screen.
  if (teamState?.team_mode && teamState?.locked) {
    return <Suspense fallback={null}><Lock onUnlocked={() => window.dispatchEvent(new CustomEvent("orrery-team-changed"))} /></Suspense>;
  }

  const visibleTabs = TABS.filter((t) =>
    (interfaceMode === "concept" || t.key !== "home")
    && (!t.feature || !features || features[t.feature] !== false)
  );
  const ActiveView = (visibleTabs.find((t) => t.key === active) || visibleTabs[0]).View;
  const pulseClass = db === "ok" ? "" : db === "error" ? "amber" : db === "down" ? "red" : "amber";
  const dbTitle =
    db === "ok" ? "Database connected"
    : db === "error" ? "Backend up — database error"
    : db === "down" ? "Backend unreachable"
    : "Connecting…";

  return (
    <div className="app">
      {update && (
        <div className="update-banner">
          <span>Orrery {update.version} is available.</span>
          <a href={update.url} target="_blank" rel="noreferrer">Download the update</a>
          <button
            aria-label="Dismiss"
            onClick={() => { sessionStorage.setItem("orrery_update_dismissed", "1"); setUpdate(null); }}
          >×</button>
        </div>
      )}
      <TopBar interfaceMode={interfaceMode} tabs={visibleTabs} onNavigate={setActive} />
      <FirstRunSetup />
      <div className="app-body">
        <nav className="rail" aria-label="Main navigation">
          <div className="rail-brand">
            <div className="logo" title="Orrery"><Logo /></div>
            <span className="rail-wordmark">Orrery</span>
          </div>
          {visibleTabs.map(({ key, label, Icon }) => (
            <button
              key={key}
              className={`tab${key === active ? " active" : ""}`}
              aria-label={label}
              onClick={() => setActive(key)}
            >
              <Icon />
              <span>{label}</span>
            </button>
          ))}
          <div className="spacer" />
          <ConnectionCheck db={db} />
          <div className="rail-meta">{appVersion ? `Orrery v${appVersion} · ` : ""}Open source · Apache 2.0</div>
        </nav>
        <Suspense fallback={<section className="view"><div className="s-sub">Loading...</div></section>}>
          <ActiveView onNavigate={setActive} features={features} />
        </Suspense>
      </div>
    </div>
  );
}
