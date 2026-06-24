import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Download,
  HardDriveDownload,
  MessageSquare,
  Play,
  RefreshCw,
  Trash2,
} from "lucide-react";
import {
  getLocalModels,
  installLocalRuntime,
  pullLocalModel,
  removeLocalModel,
  setLocalModelActive,
  startLocalRuntime,
} from "../lib/api.js";

function formatBytes(bytes) {
  if (!bytes) return "size unavailable";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit >= 3 ? 1 : 0)} ${units[unit]}`;
}

export default function LocalModels({ onNavigate }) {
  const [data, setData] = useState(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState({});
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState("all");
  const [customName, setCustomName] = useState("");

  async function refresh() {
    try {
      setError("");
      setData(await getLocalModels());
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  useEffect(() => { refresh(); }, []);

  async function action(name, fn) {
    setBusy(name);
    setError("");
    try {
      const next = await fn();
      if (next?.curated) setData(next);
      else await refresh();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy("");
    }
  }

  async function pull(model) {
    setBusy(`pull:${model}`);
    setError("");
    setProgress((current) => ({ ...current, [model]: { status: "Starting...", percent: 0 } }));
    const controller = new AbortController();
    try {
      await pullLocalModel(model, (event) => {
        if (event.error) throw new Error(event.error);
        const percent = event.total ? Math.min(100, Math.round((event.completed / event.total) * 100)) : 0;
        setProgress((current) => ({
          ...current,
          [model]: { status: event.done ? "Ready" : event.status, percent: event.done ? 100 : percent },
        }));
      }, controller.signal);
      await refresh();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy("");
    }
  }

  function chatWith(model) {
    sessionStorage.setItem("orrery_preferred_model", `ollama/${model}`);
    onNavigate?.("chat");
  }

  if (!data) {
    return <section className="view local-models"><div className="local-loading">Checking local model runtime...</div></section>;
  }

  return (
    <section className="view local-models">
      <div className="local-scroll">
        <header className="local-header">
          <div>
            <div className="local-eyebrow">ON-DEVICE AI</div>
            <h1>Local Models</h1>
            <p>Install Ollama, download a model, and keep prompts and responses on this computer.</p>
          </div>
          <button className="icon-square" title="Refresh status" onClick={refresh}><RefreshCw /></button>
        </header>

        {error && <div className="local-error">{error}</div>}

        <div className="runtime-strip">
          <div className={`runtime-state ${data.running ? "ready" : ""}`}>
            <HardDriveDownload />
            <div>
              <strong>{data.running ? "Ollama is running" : data.installed ? "Ollama is installed" : "Ollama is not installed"}</strong>
              <span>{data.version ? `Version ${data.version}` : "Official local model runtime"}</span>
            </div>
          </div>
          {!data.installed && (
            <div className="runtime-actions">
              <label className="consent-check">
                <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} />
                Install the official Ollama package with Windows Package Manager
              </label>
              <button
                className="btn primary"
                disabled={!ack || !data.can_install || !!busy}
                onClick={() => action("install", () => installLocalRuntime(true))}
              >
                <Download /> {busy === "install" ? "Installing..." : "Install Ollama"}
              </button>
            </div>
          )}
          {data.installed && !data.running && (
            <button className="btn primary" disabled={!!busy} onClick={() => action("start", startLocalRuntime)}>
              <Play /> {busy === "start" ? "Starting..." : "Start Ollama"}
            </button>
          )}
          {data.running && <span className="runtime-private"><CheckCircle2 /> Local API ready</span>}
        </div>

        <section className="local-section">
          <div className="local-section-head">
            <div>
              <h2>Browse models</h2>
              <p>Start small. Larger models need more RAM and disk space.</p>
            </div>
          </div>
          <div className="local-toolbar">
            <input
              className="key-input local-search"
              placeholder="Search models (name, capability, e.g. vision, code, reasoning)…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select className="effort-pick" value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="all">all sizes</option>
              <option value="tiny">tiny (≤2 GB)</option>
              <option value="small">small (2–6 GB)</option>
              <option value="medium">medium (6–25 GB)</option>
              <option value="large">large (25 GB+)</option>
            </select>
          </div>
          <div className="model-grid">
            {data.curated
              .filter((item) => tier === "all" || item.tier === tier)
              .filter((item) => {
                const q = query.trim().toLowerCase();
                if (!q) return true;
                return (
                  item.name.toLowerCase().includes(q) ||
                  item.label.toLowerCase().includes(q) ||
                  (item.description || "").toLowerCase().includes(q) ||
                  (item.capabilities || []).some((c) => c.toLowerCase().includes(q))
                );
              })
              .map((item) => {
              const itemProgress = progress[item.name];
              const pulling = busy === `pull:${item.name}`;
              return (
                <article className="local-model-card" key={item.name}>
                  <div className="local-model-top">
                    <div>
                      <h3>{item.label}</h3>
                      <code>{item.name}</code>
                    </div>
                    {item.installed && <span className="installed-badge"><CheckCircle2 /> Installed</span>}
                  </div>
                  <p>{item.description}</p>
                  <div className="cap-row">
                    {item.capabilities.map((capability) => <span key={capability}>{capability}</span>)}
                    <span>{item.size}</span>
                  </div>
                  {pulling && (
                    <div className="pull-progress">
                      <div><span>{itemProgress?.status || "Downloading"}</span><b>{itemProgress?.percent || 0}%</b></div>
                      <progress value={itemProgress?.percent || 0} max="100" />
                    </div>
                  )}
                  <div className="local-card-actions">
                    {!item.installed ? (
                      <button className="btn primary" disabled={!data.running || !!busy} onClick={() => pull(item.name)}>
                        <Download /> Download
                      </button>
                    ) : (
                      <>
                        <button className="btn primary" onClick={() => chatWith(item.name)}>
                          <MessageSquare /> Chat
                        </button>
                        <button
                          className="btn ghost"
                          onClick={() => action(`active:${item.name}`, () => setLocalModelActive(item.name, !item.active))}
                        >
                          {item.active ? "Hide from Chat" : "Show in Chat"}
                        </button>
                      </>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
          <div className="local-pull-any">
            <div>
              <strong>Pull any model</strong>
              <span>Enter any name from the Ollama library (e.g. <code>qwen3:7b</code>, <code>llama3.1:8b</code>).</span>
            </div>
            <div className="local-pull-row">
              <input
                className="key-input"
                placeholder="model:tag"
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && customName.trim()) pull(customName.trim()); }}
              />
              <button
                className="btn primary"
                disabled={!data.running || !customName.trim() || !!busy}
                onClick={() => pull(customName.trim())}
              >
                <Download /> Download
              </button>
            </div>
            {progress[customName.trim()] && busy === `pull:${customName.trim()}` && (
              <div className="pull-progress">
                <div><span>{progress[customName.trim()]?.status || "Downloading"}</span><b>{progress[customName.trim()]?.percent || 0}%</b></div>
                <progress value={progress[customName.trim()]?.percent || 0} max="100" />
              </div>
            )}
            {!data.running && <span className="local-hint">Start Ollama above to download models.</span>}
          </div>
        </section>

        {data.models.length > 0 && (
          <section className="local-section">
            <div className="local-section-head"><div><h2>Installed</h2><p>Models currently stored by Ollama.</p></div></div>
            <div className="installed-list">
              {data.models.map((item) => (
                <div className="installed-row" key={item.name}>
                  <div><strong>{item.name}</strong><span>{formatBytes(item.size)}</span></div>
                  <div className="installed-actions">
                    <button className="btn ghost" onClick={() => chatWith(item.name)}><MessageSquare /> Chat</button>
                    <button
                      className="btn ghost"
                      onClick={() => action(`toggle:${item.name}`, () => setLocalModelActive(item.name, !item.active))}
                    >
                      {item.active ? "Visible" : "Hidden"}
                    </button>
                    <button
                      className="icon-square danger"
                      title="Remove model"
                      onClick={() => {
                        if (window.confirm(`Remove ${item.name} from this computer?`)) {
                          action(`remove:${item.name}`, () => removeLocalModel(item.name));
                        }
                      }}
                    >
                      <Trash2 />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </section>
  );
}
