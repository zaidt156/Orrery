import { useEffect, useState } from "react";
import { Lock, ShieldCheck } from "lucide-react";
import { getAdmin, setAdminFeatures, setAdminToken } from "../lib/api.js";

// Admin: an admin sets a token (kept in the OS keychain) and can turn Orrery capabilities on/off
// globally. Once a token is set, changes require it. Turned-off features are gated in the backend and
// their tabs are hidden across the app.
export default function Admin() {
  const [status, setStatus] = useState({ admin_set: false, features: [] });
  const [token, setToken] = useState("");
  const [newToken, setNewToken] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try { setStatus(await getAdmin()); } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { load(); }, []);

  async function saveToken() {
    if (!newToken.trim()) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      await setAdminToken(newToken.trim(), token.trim());
      setToken(newToken.trim()); setNewToken("");
      setMsg("Admin token saved.");
      await load();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function toggle(name, enabled) {
    setStatus((s) => ({ ...s, features: s.features.map((f) => (f.name === name ? { ...f, enabled } : f)) }));
    setErr(""); setMsg("");
    try {
      const res = await setAdminFeatures({ [name]: enabled }, token.trim());
      setStatus(res);
      window.dispatchEvent(new CustomEvent("orrery-features-changed"));
    } catch (e) { setErr(String(e.message || e)); await load(); }
  }

  return (
    <section className="view">
      <div className="admin-wrap">
        <div className="admin-head">
          <ShieldCheck />
          <div>
            <h2>Admin &amp; feature flags</h2>
            <p>
              Turn Orrery capabilities on or off for everyone.
              {status.admin_set ? " Enter your admin token to make changes." : " Set an admin token to lock these controls."}
            </p>
          </div>
        </div>

        {err && <div className="chat-banner">{err}</div>}
        {msg && <div className="admin-ok">{msg}</div>}

        <div className="admin-token">
          <Lock />
          {status.admin_set && (
            <input type="password" placeholder="Current admin token" value={token} onChange={(e) => setToken(e.target.value)} />
          )}
          <input
            type="password"
            placeholder={status.admin_set ? "New token (optional, to change)" : "Set an admin token"}
            value={newToken}
            onChange={(e) => setNewToken(e.target.value)}
          />
          <button className="btn" onClick={saveToken} disabled={busy || !newToken.trim()}>
            {status.admin_set ? "Change token" : "Set token"}
          </button>
        </div>

        <div className="admin-features">
          {status.features.map((f) => (
            <div key={f.name} className="admin-feature">
              <span><b>{f.label}</b><small>{f.name}</small></span>
              <span
                className={`toggle${f.enabled ? " on" : ""}`}
                role="switch" aria-checked={f.enabled} tabIndex={0}
                title={f.enabled ? "Enabled" : "Disabled"}
                onClick={() => toggle(f.name, !f.enabled)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(f.name, !f.enabled); } }}
              />
            </div>
          ))}
        </div>
        {status.admin_set && <p className="admin-note">Tip: enter your current token above before toggling a feature.</p>}
      </div>
    </section>
  );
}
