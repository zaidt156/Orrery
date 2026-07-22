// Leaf UI components for Chat: file chips, generated-file cards, SVG renders, and the
// thinking/working indicators. Kept out of Chat.jsx to keep that file focused.
import { useEffect, useState } from "react";
import {
  AlertTriangle, AppWindow, Brain, CheckCircle2, Cog, Download, Eye, FileText, GitBranch, Loader2, Scale, Search, ShieldCheck, Terminal, X,
} from "lucide-react";
import { saveClientFile, getTasks, cancelTask, evaluateMessage, adoptAnswer, decideToolApproval } from "../lib/api.js";

// Inline approval card for the central tool gate: an external/destructive tool call pauses the
// turn until the user decides. "Always allow" remembers the tool so it asks once, not per call.
export function ApprovalCard({ approval }) {
  const [busy, setBusy] = useState(false);
  const [remember, setRemember] = useState(false);
  const status = approval.status || "pending";
  const pending = status === "pending";

  async function decide(approve) {
    setBusy(true);
    try { await decideToolApproval(approval.id, approve, remember); } catch { /* the stream event reconciles */ }
  }

  return (
    <div className={`approval-card ${status}`} role="group" aria-label="Tool approval">
      <div className="approval-head">
        <ShieldCheck aria-hidden="true" />
        <span className="approval-title">
          {pending ? "Approval needed" : status === "approved" ? "Approved" : status === "denied" ? "Denied" : "Expired"}
          {" — "}{approval.label || approval.tool}
        </span>
      </div>
      {approval.summary && <div className="approval-summary">{approval.summary}</div>}
      {pending && (
        <div className="approval-actions">
          <button className="approval-approve" disabled={busy} onClick={() => decide(true)}>Approve</button>
          <button className="approval-deny" disabled={busy} onClick={() => decide(false)}>Deny</button>
          <label className="approval-remember">
            <input
              type="checkbox"
              checked={remember}
              onChange={(event) => setRemember(event.target.checked)}
            />
            Always allow this tool
          </label>
        </div>
      )}
    </div>
  );
}

// Task Brain: a live, collapsible ledger of background work (chat generations, jobs, automations)
// so the user can see what's running, jump to it, or cancel it. Polls; also refreshes on demand.
export function TaskBrainPanel({ onOpenConversation }) {
  const [tasks, setTasks] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => getTasks().then((r) => alive && setTasks(r.tasks || [])).catch(() => {});
    load();
    const id = setInterval(load, 4000);
    window.addEventListener("orrery-tasks-changed", load);
    return () => { alive = false; clearInterval(id); window.removeEventListener("orrery-tasks-changed", load); };
  }, []);

  if (!tasks.length) return null;
  const active = tasks.filter((t) => t.status === "running" || t.status === "queued");

  async function cancel(id) {
    try { await cancelTask(id); } finally { window.dispatchEvent(new Event("orrery-tasks-changed")); }
  }

  return (
    <div className="taskbrain">
      <button className="tb-head" onClick={() => setOpen((v) => !v)}>
        Activity{active.length ? <span className="tb-badge">{active.length}</span> : null}
        <span className="think-caret">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="tb-list">
          {tasks.slice(0, 10).map((t) => (
            <div key={t.id} className={`tb-row tb-${t.status}`}>
              <span className="tb-dot" aria-hidden="true" />
              <button
                className="tb-title"
                title={t.detail || t.status}
                onClick={() => t.conversation_id && onOpenConversation?.(t.conversation_id)}
              >
                {t.title}
              </button>
              <span className="tb-status">{t.status}</span>
              {(t.status === "running" || t.status === "queued") && (
                <button className="tb-cancel" title="Cancel" onClick={() => cancel(t.id)}>×</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Requested file controls: click the file chip to preview; use the download icon to save.
// The reply can be turned into the file the user asked for (rendered on demand). Presented as the
// SAME rich file card as a pre-generated file (GeneratedFileCard) so the experience is consistent —
// the user always sees "a file to preview/download", not a different-looking row of chips.
export function ReplyFiles({ formats, onPreview, onDownload }) {
  const [busy, setBusy] = useState(null);
  async function run(kind, fn) {
    setBusy(kind);
    try { await fn(); } finally { setBusy(null); }
  }
  return (
    <div className="reply-files">
      {formats.map(({ id, label, Icon }) => (
        <div key={id} className="file-card2">
          <span className="file-thumb" aria-hidden="true"><Icon /></span>
          <span className="file-card2-meta">
            <span className="file-card2-name">{label} file</span>
            <span className="file-card2-sub">Made from this reply · {label}</span>
          </span>
          <span className="file-card2-actions">
            <button
              className="file-btn ghost"
              disabled={!!busy}
              onClick={() => run(`${id}:preview`, () => onPreview(id))}
              title={`Preview ${label}`}
            >
              <Eye /> {busy === `${id}:preview` ? "Opening…" : "Preview"}
            </button>
            <button
              className="file-btn primary"
              disabled={!!busy}
              onClick={() => run(`${id}:download`, () => onDownload(id))}
              title={`Download ${label}`}
              aria-label={`Download ${label}`}
            >
              <Download /> {busy === `${id}:download` ? "Saving…" : "Download"}
            </button>
          </span>
        </div>
      ))}
    </div>
  );
}

// A model-generated SVG (raw <svg> in a reply) rendered as an actual image, not code.
export function InlineSvg({ svg, onPreview, onError }) {
  const url = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  async function download() {
    try { await saveClientFile("orrery-image.svg", svg, "image/svg+xml"); }
    catch (e) { onError?.(e); }
  }
  return (
    <figure className="code-image">
      <img src={url} alt="Generated SVG image" />
      <figcaption>
        <span>SVG image</span>
        <button onClick={() => onPreview?.()} title="Preview larger"><Eye /> Preview</button>
        <button onClick={download} title="Download SVG"><Download /> Download</button>
      </figcaption>
    </figure>
  );
}

export function CodeImageArtifact({ artifact, onPreview, onError }) {
  const [url, setUrl] = useState("");

  useEffect(() => {
    if (artifact?.kind !== "svg" || !artifact.content) return undefined;
    const next = URL.createObjectURL(new Blob([artifact.content], { type: "image/svg+xml" }));
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [artifact]);

  async function download() {
    try { await saveClientFile(artifact.name || "orrery-image.svg", artifact.content, "image/svg+xml"); }
    catch (e) { onError?.(e); }
  }

  if (!url) return null;
  return (
    <figure className="code-image">
      <img src={url} alt="AI-generated code-rendered SVG" />
      <figcaption>
        <span>Sanitized SVG</span>
        {onPreview && <button onClick={() => onPreview(artifact.content)} title="Preview larger"><Eye /> Preview</button>}
        <button onClick={download} title="Download SVG"><Download /> Download</button>
      </figcaption>
    </figure>
  );
}

const PREVIEWABLE_FILE = /\.(pdf|png|jpe?g|gif|webp|svg|pptx|xlsx|docx|csv|md|markdown|txt|html?|json|tex|wav|mp3|mp4|webm)$/i;

function formatBytes(n) {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fileExtIcon(name = "") {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (ext === "tex") return "TeX";
  if (ext === "pdf") return "📕";
  if (["xlsx", "xls", "csv"].includes(ext)) return "📊";
  if (["pptx", "ppt"].includes(ext)) return "📑";
  if (["docx", "doc"].includes(ext)) return "📝";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) return "🖼";
  if (["zip", "tar", "gz"].includes(ext)) return "🗜";
  return "📄";
}

// Human "Type" label for the card subtitle (e.g. "Document · PDF").
function fileTypeLabel(name = "") {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (["pdf", "doc", "docx"].includes(ext)) return "Document";
  if (["xls", "xlsx", "csv", "tsv"].includes(ext)) return "Spreadsheet";
  if (["ppt", "pptx"].includes(ext)) return "Presentation";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) return "Image";
  if (["mp4", "webm"].includes(ext)) return "Video";
  if (["zip", "tar", "gz"].includes(ext)) return "Archive";
  if (["json", "yaml", "yml", "xml"].includes(ext)) return "Data";
  if (["html", "htm", "js", "jsx", "ts", "tsx", "py", "css", "md", "sql", "tex"].includes(ext)) return "Code";
  if (["txt", "log"].includes(ext)) return "Text";
  if (["wav", "mp3"].includes(ext)) return "Audio";
  return "File";
}

// A produced file shown as a rich card: thumbnail + name + "Type · EXT · size" + Preview/Download.
const IMAGE_FILE = /\.(png|jpe?g|gif|webp|svg)$/i;

// Thumbnail for an uploaded image attachment after a reload: bytes live in the file library
// (file_id), fetched lazily so old chats render fast.
export function LazyAttachmentImg({ fileId, name, onClick }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let alive = true;
    import("../lib/api.js").then(({ previewGeneratedFile }) =>
      previewGeneratedFile(fileId).then(({ url: u }) => { if (alive) setUrl(u); }).catch(() => {})
    );
    return () => { alive = false; };
  }, [fileId]);
  if (!url) return <span className="attach-chip">🖼 {name}</span>;
  return (
    <figure className="msg-thumb-fig" onClick={onClick} title="Click to view full size">
      <img src={url} alt={name} className="msg-thumb" />
      <figcaption>{name}</figcaption>
    </figure>
  );
}

export function GeneratedFileCard({ file, onPreview, onDownload, onOpenApp }) {
  const [busy, setBusy] = useState(null);
  const [thumb, setThumb] = useState("");
  const isApp = file.artifact_type === "app_bundle";
  const canPreview = !isApp && PREVIEWABLE_FILE.test(file.name || "");
  const ext = (file.name?.split(".").pop() || "file").toUpperCase();
  const appMeta = isApp
    ? ["App", file.member_count ? `${file.member_count} files` : "", file.size ? formatBytes(file.size) : ""]
    : [fileTypeLabel(file.name), ext, file.size ? formatBytes(file.size) : ""];
  const meta = appMeta.filter(Boolean).join(" · ");
  async function run(kind, fn) { setBusy(kind); try { await fn(); } finally { setBusy(null); } }

  // real thumbnails for generated images, so "which image is which" is visible at a glance
  useEffect(() => {
    let alive = true;
    if (file.id && IMAGE_FILE.test(file.name || "")) {
      import("../lib/api.js").then(({ previewGeneratedFile }) =>
        previewGeneratedFile(file.id).then(({ url }) => { if (alive) setThumb(url); }).catch(() => {})
      );
    }
    return () => { alive = false; };
  }, [file.id, file.name]);

  return (
    <div className="file-card2">
      {thumb
        ? <img className="file-thumb file-thumb-img" src={thumb} alt={file.name} onClick={() => run("preview", onPreview)} title="Preview" />
        : <span className="file-thumb" aria-hidden="true">{fileExtIcon(file.name)}</span>}
      <span className="file-card2-meta">
        <span className="file-card2-name" title={file.name}>{file.name}</span>
        <span className="file-card2-sub">{meta}</span>
      </span>
      <span className="file-card2-actions">
        {isApp && onOpenApp && (
          <button className="file-btn primary" disabled={!!busy} onClick={() => run("open", onOpenApp)} title="Run this app in a sandboxed panel">
            <AppWindow /> {busy === "open" ? "Opening…" : "Open app"}
          </button>
        )}
        {canPreview && (
          <button className="file-btn ghost" disabled={!!busy} onClick={() => run("preview", onPreview)} title="Preview in side panel">
            <Eye /> {busy === "preview" ? "Opening…" : "Preview"}
          </button>
        )}
        <button className={`file-btn ${isApp ? "ghost" : "primary"}`} disabled={!!busy} onClick={() => run("dl", onDownload)} title={isApp ? "Download the app as a ZIP" : "Download to your computer"}>
          <Download /> {busy === "dl" ? "Saving…" : isApp ? "Download ZIP" : "Download"}
        </button>
      </span>
    </div>
  );
}

// Playful, on-brand status lines that rotate while a response is being produced.
const CREATIVE_LINES = [
  "Consulting the constellations…",
  "Charting your request…",
  "Aligning the orbits…",
  "Designing something polished…",
  "Gathering stardust…",
  "Plotting the trajectory…",
  "Crunching the structure…",
  "Arranging slides and cells…",
  "Calibrating the instruments…",
  "Drafting with care…",
  "Polishing every pixel…",
  "Running the numbers…",
  "Mapping the details…",
  "Tuning the typography…",
  "Threading the logic together…",
  "Composing the layout…",
  "Reticulating splines…",
  "Bringing it all together…",
  "Almost in orbit…",
  "Reading the star charts…",
  "Spinning up the orrery…",
  "Winding the gears…",
  "Setting the planets in motion…",
  "Triangulating the answer…",
  "Sketching the blueprint…",
  "Weighing the options…",
  "Connecting the dots…",
  "Distilling the essence…",
  "Sharpening the details…",
  "Balancing the composition…",
  "Lining up the facts…",
  "Stitching the sections together…",
  "Refining the draft…",
  "Double-checking the math…",
  "Sorting through the data…",
  "Framing the narrative…",
  "Choosing the right words…",
  "Measuring twice, cutting once…",
  "Assembling the pieces…",
  "Smoothing the edges…",
  "Cross-referencing the sources…",
  "Laying the groundwork…",
  "Warming up the engines…",
  "Scanning the horizon…",
  "Following the thread…",
  "Shaping the response…",
  "Adding the finishing touches…",
  "Syncing the moving parts…",
  "Charting a course…",
  "Tracing the orbit lines…",
  "Focusing the telescope…",
  "Letting the ideas settle into place…",
];

// The Orrery "working" pulse: the three twinkling stars + a creative line that
// changes at random while the model is processing.
export function ThinkingPulse() {
  const pick = () => CREATIVE_LINES[Math.floor(Math.random() * CREATIVE_LINES.length)];
  const [line, setLine] = useState(pick);
  useEffect(() => {
    const id = setInterval(() => {
      setLine((prev) => {
        let next = pick();
        if (CREATIVE_LINES.length > 1) while (next === prev) next = pick();
        return next;
      });
    }, 2600);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="thinking">
      <span className="think-stars" aria-hidden="true"><i>✦</i><i>✦</i><i>✦</i></span>
      <span className="thinking-label">{line}</span>
    </div>
  );
}

// One timeline-row glyph per step. The shape comes from the step KIND (so a tool stays a terminal
// even once it's done); colour comes from STATUS via the trace-<status> class.
function StepIcon({ kind, status }) {
  if (status === "running") return <Loader2 className="trace-spin" />;
  switch (kind) {
    case "route": return <GitBranch />;
    case "context": return <Search />;
    case "tool":
    case "script": return <Terminal />;
    case "file": return <FileText />;
    case "validation":
    case "safety": return <ShieldCheck />;
    case "warning":
    case "error": return <AlertTriangle />;
    case "work": return <Cog />;
    case "result":
    default: return <CheckCircle2 />;
  }
}

function hostLabel(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch { return url; }
}

// Sources rendered inside the trace: web URLs become clickable links (domain label), document
// names become non-clickable chips. Shown where the search/research actually happened.
function SourceLinks({ urls }) {
  if (!urls?.length) return null;
  return (
    <span className="trace-sources">
      {urls.map((u, i) => (/^https?:\/\//i.test(u)
        ? <a key={i} className="trace-source" href={u} target="_blank" rel="noreferrer noopener" title={u}>{hostLabel(u)}</a>
        : <span key={i} className="trace-source doc" title={u}>{u}</span>
      ))}
    </span>
  );
}

// Two-layer work-trace panel, like a high-end AI workspace:
//   • collapsed = a one-line activity headline;
//   • expanded = clean public progress + a trace line of what Orrery actually did
//     (searched the web, ran Python, produced files) and the sources it used.
// Auto-opens while streaming and stays open when that answer finishes; historical panels load collapsed.
export function ReasoningPanel({ outer, trace, thinking, summary, sources, streaming }) {
  // A panel that appeared during this response stays open when streaming ends. Historical panels
  // still load collapsed, and the user can collapse either kind explicitly.
  const [open, setOpen] = useState(Boolean(streaming));
  const steps = trace || [];
  if (!steps.length && !summary && !outer && !sources?.length && !thinking) return null;
  const show = open || streaming;
  const title = streaming
    ? (outer?.title || "Thinking…")
    : (outer?.title || summary?.title || "Reasoning");
  return (
    <div className={`think-block${streaming ? " live" : ""}`}>
      <button type="button" className="think-head" aria-expanded={show} onClick={() => setOpen((v) => !v)}>
        <span className="think-headings">
          <span className="think-title">{title}</span>
          {outer?.summary ? <span className="think-sub">{outer.summary}</span> : null}
        </span>
        <span className="think-caret">{show ? "▾" : "▸"}</span>
      </button>
      {show && (
        <div className="think-body">
          {thinking ? (
            <div className="trace-step trace-think">
              <span className="trace-icon" aria-hidden="true"><Brain /></span>
              <span className="trace-text">
                <span className="trace-stage">Raw model thinking</span>
                <span className="trace-think-body">{thinking}{streaming ? <span className="caret" /> : null}</span>
              </span>
            </div>
          ) : !streaming ? (
            <div className="trace-step trace-info">
              <span className="trace-icon" aria-hidden="true"><Brain /></span>
              <span className="trace-text">
                <span className="trace-stage">Raw model thinking unavailable</span>
                <span className="trace-detail">
                  This model connection did not expose a raw-thinking stream. The activity below is Orrery&apos;s execution trace, not rewritten model thoughts.
                </span>
              </span>
            </div>
          ) : null}
          {steps.map((s, i) => {
            // Steps are append-only and a "running" step is never re-emitted as done, so once the
            // turn has finished (not streaming) any lingering "running" step is really complete.
            const st = !streaming && s.status === "running" ? "done" : (s.status || "done");
            return (
              <div key={s.id || i} className={`trace-step trace-${st}`}>
                <span className="trace-icon" aria-hidden="true"><StepIcon kind={s.kind} status={st} /></span>
                <span className="trace-text">
                  <span className="trace-stage">{s.stage}</span>
                  {s.detail ? <span className="trace-detail">{s.detail}</span> : null}
                  {s.think ? (
                    <span className="trace-rawthink">{s.think}{streaming && i === steps.length - 1 ? <span className="caret" /> : null}</span>
                  ) : null}
                  {s.metadata?.sources?.length ? <SourceLinks urls={s.metadata.sources} /> : null}
                </span>
              </div>
            );
          })}
          {!streaming && summary?.items?.length ? (
            <ol className="trace-summary">
              {summary.items.map((it, i) => <li key={i}>{it}</li>)}
            </ol>
          ) : null}
          {sources?.length ? (
            <div className="trace-sources-foot">
              <span className="trace-sources-label">Sources</span>
              <SourceLinks urls={sources} />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// Answer evaluation ("pick the best answer"): re-answers the same prompt with the models the user
// picks, sends all candidates ANONYMOUSLY to a judge model for 0-10 scoring, and lets the user adopt
// the winner — which rewrites the assistant message through the normal persistence path.
export function EvaluatePanel({ convId, messageId, models, currentModel, onClose, onAdopted }) {
  const [picked, setPicked] = useState([]);
  const [judge, setJudge] = useState(currentModel || models[0]?.id || "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");
  const [expanded, setExpanded] = useState("");

  function togglePick(id) {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length < 3 ? [...p, id] : p));
  }

  async function run() {
    setBusy(true); setErr(""); setResult(null);
    try { setResult(await evaluateMessage(convId, messageId, picked, judge)); }
    catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  async function adopt(c) {
    setBusy(true); setErr("");
    try {
      await adoptAnswer(convId, messageId, c.text, c.model);
      onAdopted?.(c.text, c.model);
    } catch (e) { setErr(String(e.message || e)); setBusy(false); }
  }

  return (
    <div className="eval-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="eval-panel">
        <div className="eval-head">
          <Scale /> <b>Evaluate answers</b>
          <span className="eval-sub">candidates are judged anonymously (A, B, C…)</span>
          <button className="icon-btn" title="Close" onClick={onClose}><X /></button>
        </div>

        {!result && (
          <>
            <div className="eval-label">Also answer with (up to 3 — the current answer is always included):</div>
            <div className="eval-models">
              {models.map((m) => (
                <label key={m.id} className={`eval-model${picked.includes(m.id) ? " on" : ""}`}>
                  <input type="checkbox" checked={picked.includes(m.id)} onChange={() => togglePick(m.id)} />
                  {m.label}
                </label>
              ))}
            </div>
            <div className="eval-label">Judge model:</div>
            <select className="eval-judge" value={judge} onChange={(e) => setJudge(e.target.value)}>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
            {err && <div className="chat-banner">{err}</div>}
            <button className="btn primary" onClick={run} disabled={busy || !judge || picked.length === 0}>
              {busy ? "Generating & judging… (this makes model calls)" : `Compare ${picked.length + 1} answers`}
            </button>
          </>
        )}

        {result && (
          <div className="eval-results">
            {!result.judged && <div className="chat-banner">The judge didn't return scores — showing unranked candidates.</div>}
            {(result.failed || []).map((f) => (
              <div key={f.model} className="eval-failed">⚠ {f.model}: {f.error}</div>
            ))}
            {result.candidates.map((c) => (
              <div key={c.letter} className={`eval-card${result.best === c.letter ? " best" : ""}`}>
                <div className="eval-card-head">
                  <span className="eval-letter">{c.letter}</span>
                  <b>{c.model}</b>
                  {c.current && <em className="eval-tag">current</em>}
                  {result.best === c.letter && <em className="eval-tag win">judge's pick</em>}
                  {c.scores?.overall != null && <span className="eval-score">{c.scores.overall}/10</span>}
                </div>
                {c.scores?.overall != null && (
                  <div className="eval-dims">
                    accuracy {c.scores.accuracy ?? "–"} · completeness {c.scores.completeness ?? "–"} · clarity {c.scores.clarity ?? "–"}
                  </div>
                )}
                {c.comment && <div className="eval-comment">{c.comment}</div>}
                <div className={`eval-text${expanded === c.letter ? " open" : ""}`}>{c.text}</div>
                <div className="eval-card-actions">
                  <button className="btn ghost sm" onClick={() => setExpanded((v) => (v === c.letter ? "" : c.letter))}>
                    {expanded === c.letter ? "Collapse" : "Read full answer"}
                  </button>
                  {!c.current && (
                    <button className="btn primary sm" disabled={busy} onClick={() => adopt(c)}>
                      Use this answer
                    </button>
                  )}
                </div>
              </div>
            ))}
            {err && <div className="chat-banner">{err}</div>}
            <button className="btn ghost sm" onClick={() => setResult(null)}>Run again with different models</button>
          </div>
        )}
      </div>
    </div>
  );
}
