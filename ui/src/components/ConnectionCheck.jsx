import { useEffect, useRef, useState } from "react";
import { checkConnections } from "../lib/api.js";

// Sidebar "Check connections" button. Idle it reflects the passive database poll; a click
// live-probes the database + every configured model connection and answers green Connected /
// red Not connected, with a per-check breakdown above the button.
export default function ConnectionCheck({ db }) {
  const [phase, setPhase] = useState("idle"); // idle | running | done
  const [result, setResult] = useState(null); // {ok, at, checks:[...]}
  const [open, setOpen] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  function onPillClick() {
    if (open) {  // second click collapses the breakdown instead of re-probing
      setOpen(false);
      return;
    }
    run();
  }

  async function run() {
    if (phase === "running") return;
    setPhase("running");
    try {
      const r = await checkConnections();
      if (!alive.current) return;
      setResult(r);
      setOpen(true);
      setPhase("done");
    } catch (e) {
      if (!alive.current) return;
      setResult({ ok: false, checks: [{ id: "backend", label: "Orrery backend", ok: false, detail: String(e.message || e), ms: 0 }] });
      setOpen(true);
      setPhase("done");
    }
  }

  const passing = result ? result.checks.filter((c) => c.ok).length : 0;
  const tone = phase === "done" ? (result?.ok ? "" : "red") : db === "ok" ? "" : db === "down" ? "red" : "amber";
  const headline =
    phase === "running" ? "Checking…"
    : phase === "done" ? (result?.ok ? "Connected" : "Not connected")
    : "Check connections";
  const subline =
    phase === "running" ? "Probing database and models"
    : phase === "done" ? `${passing} of ${result.checks.length} checks passed`
    : db === "ok" ? "Database connected — click to test everything"
    : "Database issue — click to diagnose";

  return (
    <div className="conn-check">
      {open && result && (
        <div className="rail-checks" role="status" title="Click to hide" onClick={() => setOpen(false)}>
          {result.checks.map((c) => (
            <div key={c.id} className="rail-check" title={c.detail}>
              <i className={`pulse ${c.ok ? "" : "red"}`} />
              <span className="rail-check-label">{c.label}</span>
              <span className="rail-check-ms">{c.ms}ms</span>
              {!c.ok && <span className="rail-check-detail">{c.detail}</span>}
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        className={`rail-health ${tone}`}
        disabled={phase === "running"}
        onClick={onPillClick}
        aria-expanded={open}
        title={open ? "Hide the connection details" : "Live-check the database and every configured model connection"}
      >
        <div className={`pulse ${phase === "running" ? "amber" : tone}`} />
        <div className="rail-health-text">
          <b>{headline}</b>
          <span>{subline}</span>
        </div>
      </button>
    </div>
  );
}
