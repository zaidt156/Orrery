import { useEffect, useState } from "react";
import { approveLifeProposal, createLifeProposal, getLife } from "../lib/api.js";

// First-run questions that seed LIFE.md — the app's living memory ("soul"). Shown only while
// LIFE.md is still fresh (nothing personal in it) and never again once answered or skipped.
const SKIP_KEY = "orrery-life-onboarding-skipped";

const QUESTIONS = [
  { key: "name", label: "What should Orrery call you?", ph: "e.g. Zaid", rows: 1 },
  { key: "work", label: "What do you do?", ph: "e.g. founder building a local-first data product", rows: 1 },
  { key: "use", label: "What will you mainly use Orrery for?", ph: "e.g. research, dashboards from our Postgres, automations", rows: 2 },
  { key: "prefs", label: "Anything Orrery should always remember?", ph: "e.g. keep answers short · never touch production data", rows: 2 },
];

function composeLife(a) {
  const parts = ["# Orrery Life"];
  const who = [];
  if (a.name?.trim()) who.push(`- Name: ${a.name.trim()}`);
  if (a.work?.trim()) who.push(`- Work: ${a.work.trim()}`);
  if (who.length) parts.push(`## Who you are\n${who.join("\n")}`);
  if (a.use?.trim()) parts.push(`## What Orrery is for\n- ${a.use.trim()}`);
  if (a.prefs?.trim()) parts.push(`## Standing preferences\n- ${a.prefs.trim()}`);
  parts.push("_Set at first run — edit any time in Settings › Life Memory. Chats propose additions; you approve every change._");
  return parts.join("\n\n") + "\n";
}

export default function FirstRunSetup() {
  const [open, setOpen] = useState(false);
  const [answers, setAnswers] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (localStorage.getItem(SKIP_KEY)) return;
    getLife().then((d) => { if (d?.fresh) setOpen(true); }).catch(() => { /* locked or offline — stay closed */ });
  }, []);

  const answered = QUESTIONS.some((q) => answers[q.key]?.trim());

  async function start() {
    if (!answered) { skip(); return; }
    setBusy(true); setErr("");
    try {
      const proposal = await createLifeProposal(composeLife(answers), "First-run setup");
      await approveLifeProposal(proposal.id, proposal.target_hash);
      setOpen(false);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  function skip() {
    localStorage.setItem(SKIP_KEY, "1");
    setOpen(false);
  }

  if (!open) return null;
  return (
    <div className="firstrun-back" role="dialog" aria-modal="true" aria-label="Welcome to Orrery">
      <div className="firstrun surface-1">
        <h2>Welcome to Orrery</h2>
        <p className="firstrun-sub">
          A few questions to give Orrery its soul. Your answers live in <b>LIFE.md</b> — a private,
          versioned memory on this machine that chats can add to only with your approval.
        </p>
        {QUESTIONS.map((q) => (
          <label key={q.key} className="firstrun-q">
            {q.label}
            {q.rows === 1 ? (
              <input value={answers[q.key] || ""} placeholder={q.ph}
                onChange={(e) => setAnswers((s) => ({ ...s, [q.key]: e.target.value }))} />
            ) : (
              <textarea rows={q.rows} value={answers[q.key] || ""} placeholder={q.ph}
                onChange={(e) => setAnswers((s) => ({ ...s, [q.key]: e.target.value }))} />
            )}
          </label>
        ))}
        {err && <div className="key-err">{err}</div>}
        <div className="firstrun-actions">
          <button className="btn ghost" onClick={skip} disabled={busy}>Skip for now</button>
          <button className="btn primary" onClick={start} disabled={busy}>
            {busy ? "Saving…" : answered ? "Start with this memory" : "Start blank"}
          </button>
        </div>
      </div>
    </div>
  );
}
