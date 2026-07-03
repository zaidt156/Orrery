import { useEffect, useState } from "react";
import { Check, Copy, KeyRound, Lock, LogOut, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react";
import {
  createTeamUser, deleteTeamUser, getAdmin, getTeam, listTeamUsers, setAdminFeatures, setAdminToken,
  setupTeam, signOutTeam, updateTeamUser,
} from "../lib/api.js";
import { copyTextResult } from "../lib/clipboard.js";

// Admin: feature flags + team access (identity, keys, roles). In team mode the controls are admin-only
// and authorized by role; in single-user (solo) mode an optional token locks the feature toggles.
export default function Admin() {
  const [status, setStatus] = useState({ admin_set: false, features: [] });
  const [team, setTeam] = useState(null); // {team_mode, locked, user}
  const [users, setUsers] = useState([]);
  const [token, setToken] = useState("");
  const [newToken, setNewToken] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [setupName, setSetupName] = useState("");
  const [newUserName, setNewUserName] = useState("");
  const [newUserRole, setNewUserRole] = useState("member");
  const [issued, setIssued] = useState(null); // {name, key} — shown once after create/setup
  const [copied, setCopied] = useState(false);

  const isAdmin = !team?.team_mode || team?.user?.role === "admin";

  async function load() {
    try {
      const [a, t] = await Promise.all([getAdmin(), getTeam()]);
      setStatus(a); setTeam(t);
      if (t.team_mode && t.user?.role === "admin") setUsers((await listTeamUsers()).users || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { load(); }, []);

  async function toggle(name, enabled) {
    setStatus((s) => ({ ...s, features: s.features.map((f) => (f.name === name ? { ...f, enabled } : f)) }));
    setErr(""); setMsg("");
    try {
      setStatus(await setAdminFeatures({ [name]: enabled }, token.trim()));
      window.dispatchEvent(new CustomEvent("orrery-features-changed"));
    } catch (e) { setErr(String(e.message || e)); await load(); }
  }

  async function saveToken() {
    if (!newToken.trim()) return;
    setBusy(true); setErr(""); setMsg("");
    try { await setAdminToken(newToken.trim(), token.trim()); setToken(newToken.trim()); setNewToken(""); setMsg("Token saved."); await load(); }
    catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function doSetup() {
    if (!setupName.trim()) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      const res = await setupTeam(setupName.trim());
      setIssued({ name: `${setupName.trim()} · admin`, key: res.key });
      setSetupName("");
      window.dispatchEvent(new CustomEvent("orrery-team-changed"));
      await load();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function addUser() {
    if (!newUserName.trim()) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      const u = await createTeamUser(newUserName.trim(), newUserRole);
      setIssued({ name: `${u.name} · ${u.role}`, key: u.key });
      setNewUserName(""); setNewUserRole("member");
      await load();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function patchUser(u, patch) {
    setErr(""); setMsg("");
    try { await updateTeamUser(u.id, patch); await load(); }
    catch (e) { setErr(String(e.message || e)); }
  }
  async function removeUser(u) {
    if (!window.confirm(`Remove ${u.name}? Their key stops working immediately.`)) return;
    try { await deleteTeamUser(u.id); await load(); } catch (e) { setErr(String(e.message || e)); }
  }
  async function doSignOut() {
    try { await signOutTeam(); } finally { window.dispatchEvent(new CustomEvent("orrery-team-changed")); window.location.reload(); }
  }
  async function copyKey() {
    const result = await copyTextResult(issued.key);
    if (!result.ok) {
      setErr(`Copy failed: ${result.error || "clipboard is unavailable."}`);
      return;
    }
    setErr("");
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <section className="view">
      <div className="admin-wrap">
        <div className="admin-inner">
        <div className="admin-head">
          <ShieldCheck />
          <div>
            <h2>Admin &amp; team</h2>
            <p>{team?.team_mode
              ? (isAdmin ? "Manage who can use this shared workspace and what's turned on." : "This shared workspace is managed by your admins.")
              : "Turn capabilities on/off, or set up shared team access."}</p>
          </div>
        </div>

        {err && <div className="chat-banner">{err}</div>}
        {msg && <div className="admin-ok">{msg}</div>}

        {/* one-time key reveal */}
        {issued && (
          <div className="key-reveal">
            <div className="key-reveal-head"><KeyRound /> Access key for <b>{issued.name}</b></div>
            <p>Copy it now — it's shown once and can't be retrieved later. Share it with that person privately.</p>
            <div className="key-reveal-row">
              <code>{issued.key}</code>
              <button className={`btn${copied ? " copied-pop" : ""}`} onClick={copyKey}>{copied ? <><Check /> Copied</> : <><Copy /> Copy</>}</button>
            </div>
            <button className="btn ghost sm" onClick={() => setIssued(null)}>I've saved it</button>
          </div>
        )}

        {/* TEAM ACCESS */}
        <div className="admin-section">
          <div className="admin-section-label"><Users /> Team access</div>

          {team && !team.team_mode && (
            <div className="team-setup">
              <p>Right now this is a single-user workspace. Set up team access to require an access key and
                let you (the founding admin) issue keys to teammates. Everyone who points their Orrery at
                this same database will then share skills, ontologies and MCP servers.</p>
              <div className="team-setup-row">
                <input value={setupName} onChange={(e) => setSetupName(e.target.value)} placeholder="Your name (founding admin)" />
                <button className="btn primary" onClick={doSetup} disabled={busy || !setupName.trim()}><Lock /> Set up team access</button>
              </div>
            </div>
          )}

          {team?.team_mode && (
            <div className="team-me">
              Signed in as <b>{team.user?.name}</b> <span className={`role-chip ${team.user?.role}`}>{team.user?.role}</span>
              <button className="btn ghost sm" onClick={doSignOut}><LogOut /> Sign out</button>
            </div>
          )}

          {team?.team_mode && isAdmin && (
            <>
              <div className="team-add">
                <input value={newUserName} onChange={(e) => setNewUserName(e.target.value)} placeholder="Teammate name" />
                <select value={newUserRole} onChange={(e) => setNewUserRole(e.target.value)}>
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </select>
                <button className="btn" onClick={addUser} disabled={busy || !newUserName.trim()}><UserPlus /> Create key</button>
              </div>
              <div className="team-users">
                {users.map((u) => (
                  <div key={u.id} className={`team-user${u.disabled ? " off" : ""}`}>
                    <span className="tu-name"><b>{u.name}</b>{u.disabled && <small>revoked</small>}</span>
                    <select value={u.role} onChange={(e) => patchUser(u, { role: e.target.value })}>
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button className="btn ghost sm" onClick={() => patchUser(u, { disabled: !u.disabled })}>{u.disabled ? "Restore" : "Revoke"}</button>
                    <button className="icon-btn" title="Delete" onClick={() => removeUser(u)}><Trash2 /></button>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* FEATURE FLAGS — admins only */}
        {isAdmin && (
          <div className="admin-section">
            <div className="admin-section-label"><ShieldCheck /> Features</div>
            {!team?.team_mode && (
              <div className="admin-token">
                <Lock />
                {status.admin_set && <input type="password" placeholder="Current token" value={token} onChange={(e) => setToken(e.target.value)} />}
                <input type="password" placeholder={status.admin_set ? "New token (to change)" : "Optional: lock these toggles with a token"} value={newToken} onChange={(e) => setNewToken(e.target.value)} />
                <button className="btn" onClick={saveToken} disabled={busy || !newToken.trim()}>{status.admin_set ? "Change" : "Set token"}</button>
              </div>
            )}
            <div className="admin-features">
              {status.features.map((f) => (
                <div key={f.name} className="admin-feature">
                  <span><b>{f.label}</b><small>{f.name}</small></span>
                  <span className={`toggle${f.enabled ? " on" : ""}`} role="switch" aria-checked={f.enabled} tabIndex={0}
                    onClick={() => toggle(f.name, !f.enabled)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(f.name, !f.enabled); } }} />
                </div>
              ))}
            </div>
          </div>
        )}
        </div>
      </div>
    </section>
  );
}
