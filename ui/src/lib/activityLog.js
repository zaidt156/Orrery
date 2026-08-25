// A readable record of what actually happened during a chat turn.
//
// Every line here comes from an event the backend really sent — nothing is inferred and nothing is
// invented. That is the whole point: if the log says a tool ran or a document was retrieved, it is
// because the stream said so, so the panel can be trusted to show what the model was given and what
// it did.
//
// Token-level events are the exception to one-line-per-event: `delta` and `reasoning_delta` arrive
// hundreds of times per turn, so they fold into a single growing entry instead of flooding the log.

export const ACTIVITY_LIMIT = 500;   // a long turn should not grow without bound

const TONE = { error: "error", warn: "warn", ok: "ok" };

function entry(kind, text, now, tone) {
  return { at: now, kind, text, tone };
}

/** Fold one stream event into the log. Returns a NEW array; never mutates the input. */
export function applyActivityEvent(log, ev, now = Date.now()) {
  if (!ev || typeof ev !== "object") return log;

  // --- coalesced streams -------------------------------------------------------------------
  if (ev.delta !== undefined) return grow(log, "answer", "Answer", ev.delta, now);
  if (ev.reasoning_delta !== undefined) return grow(log, "thinking", "Thinking", ev.reasoning_delta, now);

  // --- one line per event ------------------------------------------------------------------
  const line = describe(ev, now);
  if (!line) return log;
  return cap([...log, line]);
}

// `reasoning_step`, `reasoning_event` and `reasoning_summary` arrive as OBJECTS, not strings. Each
// used to be passed through String(), so every tool call and every retrieval rendered as
// "[object Object]" — the panel said something happened and never what. These read the fields.

/** The visible line for a work-trace step: its stage, and its detail when there is one. */
function stepText(step) {
  if (typeof step === "string") return step;
  if (!step || typeof step !== "object") return "";
  const stage = String(step.stage || "").trim();
  const detail = String(step.detail || "").trim();
  if (stage && detail) return `${stage} · ${detail}`;
  return stage || detail;
}

// The panel styles entries by kind, so a tool call should not look like ordinary narration. Kinds
// come from the backend's trace vocabulary (work|tool|file|script|validation|result|safety|route|
// context); anything unrecognised falls back to a plain step.
const STEP_KINDS = new Set(["tool", "file", "script", "validation", "result", "safety", "route", "context"]);

function stepTone(step) {
  const level = String(step?.level || "").toLowerCase();
  const status = String(step?.status || "").toLowerCase();
  if (level === "error" || status === "error") return TONE.error;
  if (level === "warning" || status === "warning") return TONE.warn;
  if (level === "success" || status === "done") return TONE.ok;
  return undefined;
}

function describeStep(step, now) {
  const text = stepText(step);
  if (!text) return null;
  const kind = String(step?.kind || "").toLowerCase();
  return entry(STEP_KINDS.has(kind) ? kind : "step", text, now, stepTone(step));
}

function describe(ev, now) {
  if (ev.status) return entry("status", String(ev.status), now);
  if (ev.reasoning_step) return describeStep(ev.reasoning_step, now);
  if (ev.reasoning_event) return describeStep(ev.reasoning_event, now);
  if (ev.reasoning_summary) {
    const summary = ev.reasoning_summary;
    if (typeof summary === "string") return entry("step", `Summary: ${summary}`, now);
    const title = String(summary?.title || "How this was produced").trim();
    const items = Array.isArray(summary?.items) ? summary.items.filter(Boolean).map(String) : [];
    return entry("step", items.length ? `${title}: ${items.join(" · ")}` : title, now);
  }

  if (ev.sources) {
    const n = Array.isArray(ev.sources) ? ev.sources.length : 0;
    return entry("sources", `Retrieved ${n} source${n === 1 ? "" : "s"}`, now, TONE.ok);
  }
  if (ev.files) {
    const names = (ev.files || []).map((f) => f?.name || f?.filename).filter(Boolean);
    return entry("file", `Created ${names.length || (ev.files || []).length} file(s)${names.length ? `: ${names.join(", ")}` : ""}`, now, TONE.ok);
  }
  if (ev.artifact) return entry("file", `Artifact: ${ev.artifact.name || ev.artifact.kind || "created"}`, now, TONE.ok);
  if (ev.svg) return entry("file", "Rendered an inline diagram", now, TONE.ok);
  if (ev.project) return entry("project", `Project: ${ev.project.name || ev.project.id || ""}`.trim(), now);

  if (ev.approval) {
    const what = ev.approval.tool || ev.approval.title || "an action";
    return entry("approval", `Approval requested for ${what}`, now, TONE.warn);
  }
  if (ev.approval_resolved) {
    const status = ev.approval_resolved.status || "resolved";
    return entry("approval", `Approval ${status}`, now, status === "approved" ? TONE.ok : TONE.warn);
  }

  if (ev.message_usage) {
    const u = ev.message_usage;
    const bits = [];
    if (u.tokens_in != null) bits.push(`${u.tokens_in} in`);
    if (u.tokens_out != null) bits.push(`${u.tokens_out} out`);
    return entry("usage", `Tokens ${bits.join(" · ") || "counted"}`, now);
  }
  if (ev.missing_key) return entry("error", `No API key configured for ${ev.missing_key}`, now, TONE.error);
  if (ev.error) return entry("error", String(ev.error), now, TONE.error);
  if (ev.resumed) return entry("status", "Resumed a generation still running in the background", now);
  if (ev.done) return entry("done", "Finished", now, TONE.ok);
  return null;
}

/** Append to the trailing entry of `kind`, or start one. Used for token-level streams. */
function grow(log, kind, label, chunk, now) {
  const text = typeof chunk === "string" ? chunk : "";
  const last = log[log.length - 1];
  if (last && last.kind === kind) {
    const chars = (last.chars || 0) + text.length;
    const updated = { ...last, chars, text: `${label} · ${chars} characters`, at: now };
    return [...log.slice(0, -1), updated];
  }
  return cap([...log, { at: now, kind, chars: text.length, text: `${label} · ${text.length} characters` }]);
}

function cap(log) {
  return log.length > ACTIVITY_LIMIT ? log.slice(log.length - ACTIVITY_LIMIT) : log;
}

/** Wall-clock label for one entry, relative to when the turn started. */
export function elapsedLabel(at, startedAt) {
  if (!startedAt || !at || at < startedAt) return "0.0s";
  return `${((at - startedAt) / 1000).toFixed(1)}s`;
}
