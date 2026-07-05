import { useEffect, useState } from "react";
import {
  Building2,
  Cpu,
  Database,
  Download,
  ImagePlus,
  KeyRound,
  LogIn,
  MessageSquareText,
  Plug,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Trash2,
  WalletCards,
} from "lucide-react";
import Toggle from "../components/Toggle.jsx";
import {
  addCustomModel,
  clearProviderKey,
  connectPlan,
  deleteCustomModel,
  disconnectPlan,
  getBranding,
  getAppUpdate,
  getPrivacy,
  setPrivacy,
  getDatabase,
  getTeam,
  testDatabase,
  saveDatabase,
  clearDatabase,
  getDefaults,
  setDefaults,
  getModels,
  listMcp,
  updateMcp,
  getModelCatalog,
  getProviders,
  getUsage,
  installPlanCli,
  loginPlanCli,
  refreshPlan,
  setBranding,
  setModelActive,
  setProviderKey,
  setSpendCap,
  submitFeedback,
} from "../lib/api.js";

const PLAN_MODE_IDS = ["claude_plan", "chatgpt_plan", "gemini_plan"];

// Tell the rest of the app (e.g. the chat model picker) that the set of usable models
// may have changed — connecting/disconnecting a key or plan, or toggling a model.
const notifyModelsChanged = () => window.dispatchEvent(new Event("orrery-models-changed"));

const ICON = {
  claude_plan: "C", chatgpt_plan: "O", gemini_plan: "G",
  anthropic: "A", openai: "O", google: "G",
  mistral: "M", deepseek: "D", openrouter: "R", ollama: "L", custom: "+",
};

const PROVIDER_LABEL = {
  claude_plan: "Claude plan (Claude Code)", chatgpt_plan: "ChatGPT plan (Codex CLI)",
  gemini_plan: "Google account (Gemini CLI)", anthropic: "Anthropic", openai: "OpenAI",
  google: "Google", mistral: "Mistral (EU)", deepseek: "DeepSeek",
  openrouter: "OpenRouter", ollama: "Ollama (local)", custom: "Custom models",
};

const SETTINGS_SECTIONS = [
  { id: "general", label: "General", Icon: SlidersHorizontal },
  { id: "accounts", label: "Accounts", Icon: KeyRound },
  { id: "database", label: "Database", Icon: Database },
  { id: "models", label: "Models", Icon: Cpu },
  { id: "usage", label: "Usage", Icon: WalletCards },
  { id: "updates", label: "Updates", Icon: Download },
  { id: "integrations", label: "Integrations", Icon: Plug },
  { id: "feedback", label: "Feedback", Icon: MessageSquareText },
];

// OpenAI-compatible presets — picking one fills the base URL (and a sample model)
const CUSTOM_PRESETS = [
  { name: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "" },
  { name: "Qwen (Alibaba)", base_url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", model: "qwen3.7-max" },
  { name: "Kimi (Moonshot)", base_url: "https://api.moonshot.ai/v1", model: "kimi-k2.7-code" },
  { name: "GLM (Z.AI)", base_url: "https://api.z.ai/api/paas/v4", model: "glm-5.2" },
  { name: "Together", base_url: "https://api.together.xyz/v1", model: "" },
  { name: "Groq", base_url: "https://api.groq.com/openai/v1", model: "" },
];

function CtrlToggle({ on, busy, disabled, onClick }) {
  const blocked = !!disabled;
  return (
    <span
      className={`toggle${on ? " on" : ""}${blocked ? " disabled" : ""}`}
      role="switch"
      aria-checked={on}
      aria-busy={busy || undefined}
      aria-disabled={blocked || undefined}
      tabIndex={blocked ? -1 : 0}
      onClick={blocked ? undefined : onClick}
      onKeyDown={(e) => {
        if (!blocked && (e.key === " " || e.key === "Enter")) {
          e.preventDefault();
          onClick();
        }
      }}
    />
  );
}

function StatusText({ mode }) {
  if (mode.configured) return <span className="keychain">✓ {mode.preview || "connected"}</span>;
  if (mode.status === "unsupported") return <span className="mode-off">unsupported</span>;
  if (mode.kind === "local") return <span className="keychain">local</span>;
  return <span className="mode-off">not connected</span>;
}

function ApiKeyMode({ provider, info, mode, onSaved, canManage }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    if (!val.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await setProviderKey(provider, val.trim());
      setVal("");
      setEditing(false);
      onSaved();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setErr(null);
    try {
      await clearProviderKey(provider);
      onSaved();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mode-row">
      <div className="mode-main">
        <div className="mode-name">{mode.label}</div>
        {!editing && <div className="mode-sub"><StatusText mode={mode} /> · {mode.message}</div>}
        {editing && (
          <div className="key-edit">
            <div className="key-edit-row">
              <input
                type="password"
                className="key-input"
                value={val}
                onChange={(e) => setVal(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") save(); }}
                placeholder={`Paste ${info.label} API key`}
                autoFocus
              />
              <button className="btn primary" disabled={busy} onClick={save}>Save</button>
              <button className="btn ghost" onClick={() => { setEditing(false); setVal(""); setErr(null); }}>Cancel</button>
            </div>
            {err && <span className="key-err">{err}</span>}
          </div>
        )}
      </div>
      {!editing && (
        <div className="mode-actions">
          {canManage ? (
            <>
              <button className="btn ghost" disabled={busy} onClick={() => setEditing(true)}>
                {mode.configured ? "Edit key" : "Add key"}
              </button>
              {mode.configured && <button className="btn ghost" disabled={busy} onClick={remove}>Remove</button>}
            </>
          ) : (
            <button className="btn ghost" disabled>Managed by admin</button>
          )}
        </div>
      )}
    </div>
  );
}

function PlanMode({ mode, onSaved, canManage }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [notice, setNotice] = useState(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [installAcknowledged, setInstallAcknowledged] = useState(false);

  async function run(action, fn, acknowledgement = false) {
    setBusy(action);
    setErr(null);
    setNotice(null);
    try {
      await fn(mode.id, acknowledgement);
      setAcknowledged(false);
      setInstallAcknowledged(false);
      await onSaved();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(null);
    }
  }

  async function signIn() {
    setBusy("login");
    setErr(null);
    setNotice(null);
    try {
      const result = await loginPlanCli(mode.id);
      setNotice(result.message);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(null);
    }
  }

  async function checkStatus() {
    setBusy("refresh");
    setErr(null);
    setNotice(null);
    try {
      await refreshPlan(mode.id);
      await onSaved();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(null);
    }
  }

  const showInstaller = mode.can_install && (
    !mode.installed || mode.update_recommended || (mode.installed && !mode.available)
  );
  const needsConsent = !mode.configured && mode.available && mode.requires_acknowledgement;

  return (
    <div className="mode-row">
      <div className="mode-main">
        <div className="mode-name">
          {mode.label}
          {mode.version && <span className="mode-version">v{mode.version}</span>}
        </div>
        <div className="mode-sub"><StatusText mode={mode} /> · {mode.message}</div>
        {mode.update_recommended && <div className="mode-warning">An official CLI update is recommended.</div>}
        {mode.model_strategy && <div className="mode-hint">{mode.model_strategy}</div>}
        {mode.warning && <div className="mode-warning">⚠ {mode.warning}</div>}
        {showInstaller && (
          <label className="mode-ack">
            <input
              type="checkbox"
              checked={installAcknowledged}
              onChange={(e) => setInstallAcknowledged(e.target.checked)}
            />
            I agree to {mode.installed ? "update" : "install"} the official vendor CLI using Windows Package Manager.
          </label>
        )}
        {needsConsent && (
          <label className="mode-ack">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            I understand this launches the official CLI and uses its account limits.
          </label>
        )}
        {notice && <span className="mode-notice">{notice}</span>}
        {err && <span className="key-err">{err}</span>}
      </div>
      <div className="mode-actions">
        {!canManage && <button className="btn ghost" disabled>Managed by admin</button>}
        {canManage && (
          <>
        {showInstaller && (
          <button
            className="btn ghost icon-text-btn"
            disabled={!!busy || !installAcknowledged}
            onClick={() => run("install", installPlanCli, installAcknowledged)}
          >
            <Download />
            {mode.installed ? "Update CLI" : "Install CLI"}
          </button>
        )}
        {mode.can_login && (
          <button className="btn ghost icon-text-btn" disabled={!!busy} onClick={signIn}>
            <LogIn />
            Sign in
          </button>
        )}
        {mode.configured ? (
          <button
            className="btn ghost"
            disabled={!!busy}
            onClick={() => run("disconnect", disconnectPlan)}
          >
            Disconnect
          </button>
        ) : mode.available ? (
          <button
            className="btn primary"
            disabled={!!busy || (mode.requires_acknowledgement && !acknowledged)}
            onClick={() => run("connect", connectPlan, acknowledged)}
          >
            {busy === "connect" ? "Verifying…" : "Connect"}
          </button>
        ) : null}
        <button
          className="icon-button"
          title="Check CLI status"
          aria-label={`Check ${mode.label} status`}
          disabled={!!busy}
          onClick={checkStatus}
        >
          <RefreshCw className={busy === "refresh" ? "spin" : ""} />
        </button>
          </>
        )}
      </div>
    </div>
  );
}

function PassiveMode({ mode }) {
  return (
    <div className={`mode-row${mode.status === "unsupported" ? " unsupported" : ""}`}>
      <div className="mode-main">
        <div className="mode-name">{mode.label}</div>
        <div className="mode-sub"><StatusText mode={mode} /> · {mode.message}</div>
      </div>
      <div className="mode-actions">
        <button className="btn ghost" disabled>{mode.status === "unsupported" ? "Unavailable" : "No action"}</button>
      </div>
    </div>
  );
}

function ProviderBlock({ name, info, onSaved, canManage }) {
  const modes = info.modes || [];
  const apiMode = modes.find((m) => m.id === "api_key");
  const rest = modes.filter((m) => m.id !== "api_key");

  return (
    <div className="provider-block">
      <div className="provider-head">
        <div className="s-icon">{ICON[name] || name[0].toUpperCase()}</div>
        <div>
          <div className="s-name">{info.label}</div>
          <div className="s-sub">accounts and keys stay local to this machine</div>
        </div>
      </div>
      {apiMode && <ApiKeyMode provider={name} info={info} mode={apiMode} onSaved={onSaved} canManage={canManage} />}
      {rest.map((mode) =>
        PLAN_MODE_IDS.includes(mode.id) ? (
          <PlanMode key={mode.id} mode={mode} onSaved={onSaved} canManage={canManage} />
        ) : (
          <PassiveMode key={mode.id} mode={mode} />
        )
      )}
    </div>
  );
}

function AddCustomModel({ onAdded, canManage }) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  function preset(p) {
    setBaseUrl(p.base_url);
    setModel(p.model);
    if (!label) setLabel(p.model ? `${p.name} · ${p.model}` : p.name);
  }

  async function save() {
    if (!baseUrl.trim() || !model.trim()) { setErr("Base URL and model id are required."); return; }
    setBusy(true);
    setErr(null);
    try {
      await addCustomModel(label.trim() || model.trim(), baseUrl.trim(), model.trim(), key.trim());
      setLabel(""); setBaseUrl(""); setModel(""); setKey(""); setOpen(false);
      onAdded();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="mode-row">
        <div className="mode-main">
          <div className="mode-name">+ Add a custom model</div>
          <div className="mode-sub">Any OpenAI-compatible endpoint — Qwen, Kimi, GLM, OpenRouter, Together, local…</div>
        </div>
        <div className="mode-actions">
          <button className="btn primary" disabled={!canManage} onClick={() => setOpen(true)}>
            {canManage ? "Add model" : "Managed by admin"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="provider-block">
      <div className="provider-head">
        <div className="s-icon">+</div>
        <div><div className="s-name">Add a custom model</div>
          <div className="s-sub">OpenAI-compatible API · key stored in your keychain, never in files</div></div>
      </div>
      <div className="preset-row">
        {CUSTOM_PRESETS.map((p) => (
          <button key={p.name} className="cmd-chip" onClick={() => preset(p)}>{p.name}</button>
        ))}
      </div>
      <div className="custom-form">
        <input className="key-input" placeholder="Display name (e.g. Qwen Max)" value={label} onChange={(e) => setLabel(e.target.value)} />
        <input className="key-input" placeholder="Base URL (https://…/v1)" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        <input className="key-input" placeholder="Model id (e.g. qwen-max)" value={model} onChange={(e) => setModel(e.target.value)} />
        <input className="key-input" type="password" placeholder="API key" value={key} onChange={(e) => setKey(e.target.value)} />
        <div className="sys-actions">
          <button className="btn primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save model"}</button>
          <button className="btn ghost" onClick={() => { setOpen(false); setErr(null); }}>Cancel</button>
        </div>
        {err && <span className="key-err">{err}</span>}
      </div>
    </div>
  );
}

function ModelsSection({ canManage }) {
  const [catalog, setCatalog] = useState(null);
  const [busy, setBusy] = useState(null);
  const load = () => getModelCatalog().then((d) => setCatalog(d.models)).catch(() => setCatalog([])).finally(notifyModelsChanged);
  useEffect(() => { load(); }, []);

  async function toggle(m) {
    if (!canManage) return;
    setBusy(m.id);
    try { await setModelActive(m.id, m.label, m.provider, !m.active); await load(); }
    catch { /* leave as-is on failure */ } finally { setBusy(null); }
  }

  async function removeCustom(m) {
    if (!canManage) return;
    if (!window.confirm(`Remove ${m.label}? This can't be undone.`)) return;
    try { await deleteCustomModel(m.custom_id); await load(); } catch { /* already gone */ }
  }

  const groups = {};
  (catalog || []).forEach((m) => { (groups[m.provider] ||= []).push(m); });
  const order = ["claude_plan", "chatgpt_plan", "gemini_plan", "anthropic", "openai", "google", "mistral", "deepseek", "ollama", "custom"];
  const activeCount = (catalog || []).filter((m) => m.active).length;

  return (
    <>
      <div className="section-label">Models — turn on the ones you want in the chat picker · {activeCount} active</div>
      {catalog === null && <div className="s-sub" style={{ padding: "4px 2px" }}>Loading…</div>}
      {catalog && catalog.length === 0 && (
        <div className="s-sub" style={{ padding: "4px 2px" }}>
          No models yet — add an API key above, connect Claude plan, or add a custom model below.
        </div>
      )}
      {order.filter((p) => groups[p]).map((p) => (
        <div className="provider-block" key={p}>
          <div className="provider-head">
            <div className="s-icon">{(ICON[p] || p[0]).toUpperCase()}</div>
            <div><div className="s-name">{PROVIDER_LABEL[p] || p}</div></div>
          </div>
          {groups[p].map((m) => (
            <div className="mode-row" key={m.id}>
              <div className="mode-main">
                <div className="mode-name">
                  {m.label}
                  {m.provider === "custom" && m.configured === false && <span className="mode-off"> · no key</span>}
                </div>
                <div className="mode-sub">{m.id}</div>
              </div>
              <div className="mode-actions">
                {m.provider === "custom" && <button className="btn ghost" disabled={!canManage} onClick={() => removeCustom(m)}>Remove</button>}
                <CtrlToggle on={m.active} busy={busy === m.id} disabled={!canManage} onClick={() => toggle(m)} />
              </div>
            </div>
          ))}
        </div>
      ))}
      <AddCustomModel onAdded={load} canManage={canManage} />
    </>
  );
}

// Keeps an in-progress branding edit alive across Settings sub-tab switches (the section
// unmounts when you leave General), so the form no longer "resets to zero".
let _brandingDraft = null;

function BrandingSection({ canManage }) {
  const [b, setB] = useState(_brandingDraft);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (_brandingDraft) return; // a draft from this session takes precedence over a re-fetch
    getBranding()
      .then((x) => { _brandingDraft = x; setB(x); })
      .catch(() => { const f = { enabled: false, name: "", tagline: "", details: "", logo: "" }; _brandingDraft = f; setB(f); });
  }, []);

  if (!b) {
    return (<><div className="section-label">Branding</div><div className="s-sub" style={{ padding: "4px 2px" }}>Loading…</div></>);
  }

  const update = (patch) => setB((p) => { const next = { ...p, ...patch }; _brandingDraft = next; return next; });

  function pickLogo(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const allowed = ["image/png", "image/jpeg", "image/webp", "image/gif"];
    if (!allowed.includes(f.type)) {
      setErr("Use a PNG, JPEG, WebP, or GIF logo.");
      return;
    }
    if (f.size > 15 * 1024 * 1024) { setErr("Logo file is too large (max 15 MB)."); return; }
    setErr(null);
    const r = new FileReader();
    r.onload = () => {
      const raw = String(r.result);
      // Small GIFs keep their animation; everything else is downscaled so ANY image works as a logo.
      if (f.type === "image/gif" && raw.length < 1_400_000) { update({ logo: raw }); return; }
      const img = new Image();
      img.onload = () => {
        const maxH = 128;  // header renders at 28px; 128 keeps it crisp on high-DPI screens
        const scale = Math.min(1, maxH / (img.height || maxH));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(img.width * scale));
        canvas.height = Math.max(1, Math.round(img.height * scale));
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        update({ logo: canvas.toDataURL("image/png"), enabled: true });  // uploading a logo means "show it"
      };
      img.onerror = () => setErr("Couldn't read that image — try a different file.");
      img.src = raw;
    };
    r.readAsDataURL(f);
  }

  async function save() {
    if (!canManage) {
      setErr("Branding is managed by the workspace admin.");
      return;
    }
    setBusy(true);
    setSaved(false);
    setErr(null);
    try {
      const next = await setBranding(b);
      _brandingDraft = next;
      setB(next);
      window.dispatchEvent(new CustomEvent("orrery-branding-changed", { detail: next }));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="section-label">Branding — show your company logo and name in the app header</div>
      <div className="provider-block">
        <div className="mode-row">
          <div className="mode-main">
            <div className="mode-name">Show branding header</div>
            <div className="mode-sub">When on, a header bar with your logo and name appears at the top of every tab.</div>
          </div>
          <div className="mode-actions"><CtrlToggle on={!!b.enabled} disabled={!canManage} onClick={() => update({ enabled: !b.enabled })} /></div>
        </div>
        <div className="branding-preview" aria-label="Branding preview">
          <div className="branding-preview-logo">
            {b.logo ? <img src={b.logo} alt="" /> : <Building2 />}
          </div>
          <div className="brand-text">
            <div className="brand-name">{b.name || "Company name"}</div>
            <div className="brand-tagline">{b.tagline || "Optional company tagline"}</div>
            {b.details && <div className="brand-details">{b.details}</div>}
          </div>
        </div>
        <div className="custom-form branding-form">
          <input className="key-input" maxLength={80} placeholder="Company name" value={b.name || ""} disabled={!canManage} onChange={(e) => update({ name: e.target.value })} />
          <input className="key-input" maxLength={160} placeholder="Tagline (optional)" value={b.tagline || ""} disabled={!canManage} onChange={(e) => update({ tagline: e.target.value })} />
          <textarea className="key-input" maxLength={280} rows={3} placeholder="Company details (optional)" value={b.details || ""} disabled={!canManage} onChange={(e) => update({ details: e.target.value })} />
          <div className="branding-actions">
            <label className={`btn ghost icon-text-btn${!canManage ? " disabled" : ""}`}>
              <ImagePlus />
              Upload logo
              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden disabled={!canManage} onChange={pickLogo} />
            </label>
            {b.logo && (
              <button className="btn ghost icon-text-btn" disabled={!canManage} onClick={() => update({ logo: "" })}>
                <Trash2 />
                Remove
              </button>
            )}
          </div>
          <div className="sys-actions">
            <button className="btn primary icon-text-btn" disabled={busy || !canManage} onClick={save}>
              <Save />
              {busy ? "Saving…" : saved ? "Saved" : "Save branding"}
            </button>
          </div>
          {err && <span className="key-err">{err}</span>}
        </div>
      </div>
    </>
  );
}

const PRIVACY_OPTIONS = [
  { id: "off", name: "Off", sub: "Send your text to cloud models exactly as written — no redaction." },
  { id: "basic", name: "Basic (recommended)", sub: "Mask common personal data (emails, phone numbers, card/SSN numbers, IPs) before it reaches a cloud model." },
  { id: "strict", name: "Strict", sub: "Basic redaction plus a stronger boundary; broader detection coming. Best when sharing sensitive documents." },
];

function PrivacySection({ canManage }) {
  const [mode, setMode] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => { getPrivacy().then((r) => setMode(r.mode)).catch(() => setMode("basic")); }, []);

  if (!mode) {
    return (<><div className="section-label">Privacy</div><div className="s-sub" style={{ padding: "4px 2px" }}>Loading…</div></>);
  }

  async function choose(id) {
    if (!canManage) return;
    const prev = mode;
    setMode(id);
    setBusy(true);
    setSaved(false);
    try {
      const r = await setPrivacy(id);
      setMode(r.mode);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch {
      setMode(prev);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="section-label">Privacy — what leaves your machine when you use a cloud model</div>
      <div className="provider-block">
        {PRIVACY_OPTIONS.map((o) => (
          <div className="mode-row" key={o.id}>
            <div className="mode-main">
              <div className="mode-name">{o.name}</div>
              <div className="mode-sub">{o.sub}</div>
            </div>
            <div className="mode-actions"><CtrlToggle on={mode === o.id} disabled={!canManage} onClick={() => choose(o.id)} /></div>
          </div>
        ))}
        <div className="mode-sub" style={{ marginTop: 8 }}>
          Local models (Ollama) are never redacted — nothing leaves your machine for them.{saved ? " Saved." : busy ? " Saving…" : ""}
        </div>
      </div>
    </>
  );
}

const CAP_PERIODS = ["hour", "day", "month", "all"];

function DatabaseSection({ canManage }) {
  const [info, setInfo] = useState(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const reload = () => getDatabase().then(setInfo).catch(() => setInfo({ configured: false }));
  useEffect(() => { if (canManage) reload(); }, [canManage]);

  if (!canManage) {
    return (
      <div className="s-card">
        <div className="section-label">Database management is controlled by the workspace admin.</div>
        <div className="mode-sub">
          You can use Orrery with the configured server, but connection strings stay hidden from member accounts.
        </div>
      </div>
    );
  }

  async function run(kind) {
    setBusy(kind); setResult(null);
    try {
      const r = kind === "save" ? await saveDatabase(url) : await testDatabase(url);
      setResult({ ...r, kind });
      if (kind === "save" && r.ok) { setUrl(""); reload(); }
    } catch (e) {
      setResult({ ok: false, error: String(e.message || e) });
    } finally {
      setBusy("");
    }
  }

  async function reconnect() {
    setBusy("reconnect"); setResult(null);
    await reload();
    setBusy("");
    setResult({ kind: "reconnect", ok: true });
  }

  async function disconnect() {
    if (!window.confirm("Remove this database connection? Orrery will use the .env default (or prompt for a new one) after a restart.")) return;
    setBusy("disconnect"); setResult(null);
    try {
      await clearDatabase();
      setResult({ kind: "disconnect", ok: true });
      reload();
    } catch (e) {
      setResult({ ok: false, error: String(e.message || e) });
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="s-card">
      <div className="section-label">The primary PostgreSQL database where Orrery stores everything — connection is kept in your OS keychain, never in project files.</div>
      {info && (
        <div className="db-current">
          <span className="db-dot" data-ok={info.status === "ok"} />
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="db-url mono">{info.configured ? info.masked : "No database configured yet"}</div>
            <div className="s-sub">{info.configured ? `${info.status === "ok" ? "Connected" : "Not reachable"} · loaded from ${info.source}` : "Enter a connection string below to get started"}</div>
          </div>
          {info.configured && (
            <div className="db-manage">
              <button className="btn ghost" disabled={!!busy} onClick={reconnect}>{busy === "reconnect" ? "Checking…" : "Reconnect"}</button>
              <button className="btn ghost" disabled={!!busy} onClick={disconnect}>{busy === "disconnect" ? "Removing…" : "Disconnect"}</button>
            </div>
          )}
        </div>
      )}
      <label className="db-label">Switch to / add another Postgres server (local, Docker, Supabase, Neon, RDS…)</label>
      <input
        className="search db-input"
        placeholder="postgresql://user:password@host:5432/dbname"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
      <div className="db-actions">
        <button className="btn" disabled={!url.trim() || !!busy} onClick={() => run("test")}>
          {busy === "test" ? "Testing…" : "Test connection"}
        </button>
        <button className="btn primary" disabled={!url.trim() || !!busy} onClick={() => run("save")}>
          {busy === "save" ? "Saving…" : "Save & connect"}
        </button>
      </div>
      {result && result.kind === "save" && result.ok && (
        <div className="db-msg ok">Saved. <strong>Restart Orrery</strong> to connect to the new database.</div>
      )}
      {result && result.kind === "test" && result.ok && (
        <div className="db-msg ok">Connection successful.</div>
      )}
      {result && result.kind === "reconnect" && result.ok && (
        <div className="db-msg ok">Re-checked the current connection.</div>
      )}
      {result && result.kind === "disconnect" && result.ok && (
        <div className="db-msg ok">Connection removed. <strong>Restart Orrery</strong> to apply.</div>
      )}
      {result && result.ok === false && (
        <div className="db-msg err">{result.error || "Could not connect."}</div>
      )}
    </div>
  );
}

function SpendingSection({ canManage }) {
  const [u, setU] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => getUsage().then(setU).catch(() => {});
  useEffect(() => { load(); const id = setInterval(load, 10000); return () => clearInterval(id); }, []);

  if (!u) return (<><div className="section-label">Spending (API keys only)</div><div className="s-sub" style={{ padding: "4px 2px" }}>Loading…</div></>);

  const cap = u.cap || { enabled: false, limit_usd: 10, period: "month" };
  const updateCap = (patch) => {
    if (!canManage) return;
    setU((p) => ({ ...p, cap: { ...p.cap, ...patch } }));
  };
  async function save() {
    if (!canManage) return;
    setBusy(true);
    try { setU(await setSpendCap({ enabled: !!cap.enabled, limit_usd: Number(cap.limit_usd) || 0, period: cap.period })); }
    finally { setBusy(false); }
  }
  const pct = cap.enabled && cap.limit_usd > 0 ? Math.min(100, (u.cost / cap.limit_usd) * 100) : 0;

  return (
    <>
      <div className="section-label">Spending — live API-key cost · subscription &amp; local models don't count</div>
      <div className="provider-block" style={{ gridColumn: "1 / -1" }}>
        <div className="mode-row">
          <div className="mode-main">
            <div className="mode-name">${(u.cost || 0).toFixed(4)} this {u.period} · {((u.tokens_in || 0) + (u.tokens_out || 0)).toLocaleString()} tokens</div>
            <div className="mode-sub">{u.over ? "Over cap — API-key models are blocked until the window resets or you raise the cap." : "Counts only API-key models (per-token billing); subscription/local are free of this."}</div>
            {cap.enabled && <div className="slider" style={{ marginTop: "8px" }}><div className="fill" style={{ width: `${pct}%`, background: u.over ? "var(--red)" : "var(--amber)" }} /></div>}
          </div>
          <div className="mode-actions"><CtrlToggle on={!!cap.enabled} disabled={!canManage} onClick={() => updateCap({ enabled: !cap.enabled })} /></div>
        </div>
        <div className="custom-form">
          <div className="preset-row" style={{ alignItems: "center" }}>
            <span className="s-sub">Cap&nbsp;$</span>
            <input className="key-input" style={{ maxWidth: "120px" }} type="number" min="0" step="0.5" value={cap.limit_usd} disabled={!canManage} onChange={(e) => updateCap({ limit_usd: e.target.value })} />
            <span className="s-sub">per</span>
            <select className="effort-pick" value={cap.period} disabled={!canManage} onChange={(e) => updateCap({ period: e.target.value })}>
              {CAP_PERIODS.map((p) => <option key={p} value={p}>{p === "all" ? "all time" : p}</option>)}
            </select>
          </div>
          <div className="sys-actions"><button className="btn primary" disabled={busy || !canManage} onClick={save}>{busy ? "Saving…" : "Save cap"}</button></div>
        </div>
      </div>
    </>
  );
}

function formatBytes(size) {
  if (!size) return "";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${Math.round(size / (1024 * 1024))} MB`;
}

function UpdatesSection() {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);

  async function check() {
    setBusy(true);
    try {
      setInfo(await getAppUpdate());
    } catch (e) {
      setInfo({ ok: false, error: String(e.message || e) });
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { check(); }, []);

  const assets = info?.assets || [];
  const isElectron = !!window.orreryDesktop;

  return (
    <>
      <div className="section-label">Updates</div>
      <div className="provider-block" style={{ gridColumn: "1 / -1" }}>
        <div className="mode-row">
          <div className="mode-main">
            <div className="mode-name">
              Orrery {info?.current_version || "checking"}
              {info?.ok && info.update_available && <span className="mode-version">new version available</span>}
            </div>
            <div className="mode-sub">
              {busy ? "Checking GitHub releases..."
                : info?.ok && info.update_available ? `Latest release: ${info.latest_tag || info.latest_version}`
                : info?.ok ? "You are on the latest published release."
                : info?.error ? `Could not check updates: ${info.error}`
                : "No update status yet."}
            </div>
            {isElectron && <div className="mode-hint">Electron shell detected. Automatic installer updates will be enabled after signed release builds are published.</div>}
          </div>
          <div className="mode-actions">
            <button className="btn ghost icon-text-btn" disabled={busy} onClick={check}>
              <RefreshCw className={busy ? "spin" : ""} />
              Check now
            </button>
            {info?.html_url && (
              <a className="btn primary icon-text-btn" href={info.html_url} target="_blank" rel="noreferrer">
                <Download />
                Open release
              </a>
            )}
          </div>
        </div>
        {assets.length > 0 && (
          <div className="custom-form">
            {assets.map((asset) => (
              <div className="mode-row" key={`${asset.name}-${asset.url}`}>
                <div className="mode-main">
                  <div className="mode-name">{asset.name || "Release asset"}</div>
                  <div className="mode-sub">{formatBytes(asset.size)}</div>
                </div>
                <div className="mode-actions">
                  {asset.url && <a className="btn ghost" href={asset.url} target="_blank" rel="noreferrer">Download</a>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

const FEEDBACK_CATS = [["general", "General"], ["bug", "Bug"], ["idea", "Idea"], ["praise", "Praise"]];

function FeedbackSection() {
  const [cat, setCat] = useState("general");
  const [msg, setMsg] = useState("");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState(null);

  async function send() {
    if (!msg.trim()) { setErr("Write a message first."); return; }
    setBusy(true);
    setErr(null);
    try {
      await submitFeedback({ category: cat, message: msg.trim(), contact: contact.trim(), context: "" });
      setMsg(""); setContact(""); setDone(true); setTimeout(() => setDone(false), 2500);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="section-label">Feedback — tell us what's working or what's missing</div>
      <div className="provider-block" style={{ gridColumn: "1 / -1" }}>
        <div className="custom-form">
          <div className="preset-row">
            {FEEDBACK_CATS.map(([v, l]) => (
              <button key={v} className={`cmd-chip${cat === v ? " warm" : ""}`} onClick={() => setCat(v)}>{l}</button>
            ))}
          </div>
          <textarea className="key-input" style={{ resize: "vertical", minHeight: "60px" }} rows={3} placeholder="Your feedback…" value={msg} onChange={(e) => setMsg(e.target.value)} />
          <input className="key-input" placeholder="Email (optional, if you want a reply)" value={contact} onChange={(e) => setContact(e.target.value)} />
          <div className="sys-actions"><button className="btn primary" disabled={busy} onClick={send}>{busy ? "Sending…" : done ? "✓ Thanks!" : "Send feedback"}</button></div>
          {err && <span className="key-err">{err}</span>}
        </div>
      </div>
    </>
  );
}

function SettingsPanelHeader({ title, description }) {
  return (
    <div className="settings-panel-header">
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}

const EFFORT_DEFAULTS = [["", "Standard"], ["low", "Quick"], ["high", "Deep"], ["xhigh", "Max"]];

function DefaultsSection({ canManage }) {
  const [models, setModels] = useState([]);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getModels().then((m) => setModels(m.models || [])).catch(() => {});
    getDefaults().then((d) => { setModel(d.model || ""); setEffort(d.effort || ""); }).catch(() => {});
  }, []);

  async function save(nextModel, nextEffort) {
    if (!canManage) return;
    setBusy(true); setSaved(false);
    try {
      await setDefaults(nextModel, nextEffort);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch { /* keep local state; next change retries */ } finally { setBusy(false); }
  }

  return (
    <>
      <div className="section-label">Defaults — applied to every new chat</div>
      <div className="provider-block">
        <div className="mode-row">
          <div className="mode-main">
            <div className="mode-name">Default model</div>
            <div className="mode-sub">New chats start on this model (you can still switch per chat)</div>
          </div>
          <div className="mode-actions">
            <select className="defaults-select" value={model}
              disabled={!canManage}
              onChange={(e) => { setModel(e.target.value); save(e.target.value, effort); }}>
              <option value="">Last used / first available</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
        </div>
        <div className="mode-row">
          <div className="mode-main">
            <div className="mode-name">Default reasoning depth</div>
            <div className="mode-sub">Quick / Standard / Deep / Max — the per-chat selector still overrides it</div>
          </div>
          <div className="mode-actions">
            <select className="defaults-select" value={effort}
              disabled={!canManage}
              onChange={(e) => { setEffort(e.target.value); save(model, e.target.value); }}>
              {EFFORT_DEFAULTS.map(([v, label]) => <option key={v || "std"} value={v}>{label}</option>)}
            </select>
          </div>
        </div>
        <div className="mode-sub" style={{ marginTop: 8 }}>{busy ? "Saving…" : saved ? "Saved." : ""}</div>
      </div>
    </>
  );
}

function IntegrationsSection() {
  const [servers, setServers] = useState(null);
  const load = () => listMcp().then((d) => setServers(d.servers || [])).catch(() => setServers([]));
  useEffect(() => { load(); }, []);

  async function toggle(s, next) {
    setServers((prev) => (prev || []).map((x) => (x.id === s.id ? { ...x, enabled: next } : x)));
    try { await updateMcp(s.id, { enabled: next }); } catch { await load(); }
  }

  return (
    <>
      <div className="section-label">MCP servers — your own tools, available to the chat model</div>
      {servers === null && <div className="s-sub settings-loading">Loading…</div>}
      {servers?.length === 0 && (
        <div className="s-sub" style={{ padding: "4px 2px" }}>
          No MCP servers yet. Add and configure them in the Skills tab (Overview → MCP servers).
        </div>
      )}
      {(servers || []).map((s) => (
        <div className="srow" key={s.id}>
          <div className="s-icon">M</div>
          <div className="s-body">
            <div className="s-name">{s.name}</div>
            <div className="s-sub">
              {(s.tools?.length ? `${s.tools.length} tool(s) · ` : "")}
              {(s.env_names?.length ? `${s.env_names.length} env · ` : "")}
              {s.transport === "http" ? (s.url || "http") : (s.command || "stdio")}
            </div>
          </div>
          <Toggle on={s.enabled} onClick={() => toggle(s, !s.enabled)} />
        </div>
      ))}
      {(servers || []).length > 0 && (
        <div className="s-sub" style={{ padding: "6px 2px 0" }}>Add, test, or remove servers in the Skills tab.</div>
      )}
    </>
  );
}

export default function Settings() {
  const [activeSection, setActiveSection] = useState("accounts");
  const [providers, setProviders] = useState(null);
  const [team, setTeam] = useState(null);
  const load = () => getProviders().then(setProviders).catch(() => setProviders({})).finally(notifyModelsChanged);
  useEffect(() => {
    load();
    getTeam().then(setTeam).catch(() => setTeam({ team_mode: false, locked: false }));
  }, []);

  const entries = providers ? Object.entries(providers) : [];
  const canManage = !team?.team_mode || team?.user?.role === "admin";
  const panels = {
    general: (
      <>
        <SettingsPanelHeader title="General" description="Company identity and workspace defaults." />
        <BrandingSection canManage={canManage} />
        <div className="panel-grid">
          <div><PrivacySection canManage={canManage} /></div>
          <div><DefaultsSection canManage={canManage} /></div>
        </div>
      </>
    ),
    accounts: (
      <>
        <SettingsPanelHeader title="Accounts & Keys" description="Connect provider accounts, API keys, and local model access." />
        <div className="section-label">
          {canManage
            ? "Credentials stay in your system keychain, never in project files"
            : "Accounts and keys are managed by your workspace admin"}
        </div>
        {providers === null && <div className="s-sub settings-loading">Loading…</div>}
        {entries.map(([name, info]) => (
          <ProviderBlock key={name} name={name} info={info} onSaved={load} canManage={canManage} />
        ))}
      </>
    ),
    database: (
      <>
        <SettingsPanelHeader title="Database" description="Connect Orrery to your own PostgreSQL server." />
        <DatabaseSection canManage={canManage} />
      </>
    ),
    models: (
      <>
        <SettingsPanelHeader title="Models" description="Choose which connected models appear in Chat." />
        <ModelsSection canManage={canManage} />
      </>
    ),
    usage: (
      <>
        <SettingsPanelHeader title="Usage" description="Monitor API-key costs and set a local spending cap." />
        <SpendingSection canManage={canManage} />
      </>
    ),
    updates: (
      <>
        <SettingsPanelHeader title="Updates" description="Check for new Orrery desktop releases." />
        <UpdatesSection />
      </>
    ),
    integrations: (
      <>
        <SettingsPanelHeader title="Integrations" description="Manage external tools available to chats and workflows." />
        <IntegrationsSection />
      </>
    ),
    feedback: (
      <>
        <SettingsPanelHeader title="Feedback" description="Send product feedback from this installation." />
        <FeedbackSection />
      </>
    ),
  };

  return (
    <section className="view">
      <div className="settings-wrap">
        <div className="settings-page-header">
          <span className="view-title">Settings</span>
          <span>Configure this Orrery installation.</span>
        </div>
        <div className="settings-layout">
          <nav className="settings-nav" aria-label="Settings sections">
            {SETTINGS_SECTIONS.map(({ id, label, Icon }) => (
              <button
                key={id}
                className={`settings-nav-button${activeSection === id ? " active" : ""}`}
                aria-current={activeSection === id ? "page" : undefined}
                onClick={() => setActiveSection(id)}
              >
                <Icon />
                <span>{label}</span>
              </button>
            ))}
          </nav>
          <main className="settings-content">
            {panels[activeSection]}
          </main>
        </div>
      </div>
    </section>
  );
}
