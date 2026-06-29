import { useState } from "react";
import { KeyRound, Lock as LockIcon } from "lucide-react";
import { unlockTeam } from "../lib/api.js";
import { Logo } from "../components/icons.jsx";

// Shown instead of the app when this Orrery is joined to a team database and the client has no valid
// access key stored. Entering a valid key unlocks the client (the key is kept in the OS keychain).
export default function Lock({ onUnlocked }) {
  const [key, setKey] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!key.trim()) return;
    setBusy(true); setErr("");
    try {
      const res = await unlockTeam(key.trim());
      onUnlocked?.(res.user);
    } catch (e2) { setErr(String(e2.message || e2)); } finally { setBusy(false); }
  }

  return (
    <div className="lock-screen">
      <form className="lock-card" onSubmit={submit}>
        <div className="lock-logo"><Logo /></div>
        <h1>Orrery</h1>
        <p className="lock-sub"><LockIcon /> This workspace is shared. Enter your access key to continue.</p>
        <div className="lock-input">
          <KeyRound />
          <input
            type="password" autoFocus value={key} onChange={(e) => setKey(e.target.value)}
            placeholder="Access key" spellCheck={false}
          />
        </div>
        {err && <div className="lock-err">{err}</div>}
        <button className="btn primary" type="submit" disabled={busy || !key.trim()}>
          {busy ? "Unlocking…" : "Unlock"}
        </button>
        <p className="lock-hint">Ask an admin for a key. Your model API keys stay private on this machine.</p>
      </form>
    </div>
  );
}
