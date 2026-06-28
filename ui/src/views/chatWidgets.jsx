// Leaf UI components for Chat: file chips, generated-file cards, SVG renders, and the
// thinking/working indicators. Kept out of Chat.jsx to keep that file focused.
import { useEffect, useState } from "react";
import {
  AlertTriangle, Brain, CheckCircle2, Cog, Download, Eye, FileText, GitBranch, Loader2, Search, ShieldCheck, Terminal,
} from "lucide-react";
import { saveClientFile, getTasks, cancelTask } from "../lib/api.js";

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
export function ReplyFiles({ formats, onPreview, onDownload }) {
  const [busy, setBusy] = useState(null);
  async function run(kind, fn) {
    setBusy(kind);
    try { await fn(); } finally { setBusy(null); }
  }
  return (
    <div className="reply-files">
      <span className="reply-files-label">Requested file:</span>
      {formats.map(({ id, label, Icon }) => (
        <span key={id} className="file-pair">
          <button
            className="file-chip file-main"
            disabled={!!busy}
            onClick={() => run(`${id}:preview`, () => onPreview(id))}
            title={`Preview ${label}`}
          >
            <Icon /> {busy === `${id}:preview` ? "Opening..." : label}
          </button>
          <button
            className="file-chip file-save"
            disabled={!!busy}
            onClick={() => run(`${id}:download`, () => onDownload(id))}
            title={`Download ${label}`}
            aria-label={`Download ${label}`}
          >
            <Download />
          </button>
        </span>
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

const PREVIEWABLE_FILE = /\.(pdf|png|jpe?g|gif|webp|svg|pptx|xlsx|docx|csv|md|markdown|txt|html?|json)$/i;

function formatBytes(n) {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fileExtIcon(name = "") {
  const ext = (name.split(".").pop() || "").toLowerCase();
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
  if (["zip", "tar", "gz"].includes(ext)) return "Archive";
  if (["json", "yaml", "yml", "xml"].includes(ext)) return "Data";
  if (["html", "htm", "js", "jsx", "ts", "tsx", "py", "css", "md", "sql"].includes(ext)) return "Code";
  if (["txt", "log"].includes(ext)) return "Text";
  if (["wav", "mp3"].includes(ext)) return "Audio";
  return "File";
}

// A produced file shown as a rich card: thumbnail + name + "Type · EXT · size" + Preview/Download.
export function GeneratedFileCard({ file, onPreview, onDownload }) {
  const [busy, setBusy] = useState(null);
  const canPreview = PREVIEWABLE_FILE.test(file.name || "");
  const ext = (file.name?.split(".").pop() || "file").toUpperCase();
  const meta = [fileTypeLabel(file.name), ext, file.size ? formatBytes(file.size) : ""].filter(Boolean).join(" · ");
  async function run(kind, fn) { setBusy(kind); try { await fn(); } finally { setBusy(null); } }
  return (
    <div className="file-card2">
      <span className="file-thumb" aria-hidden="true">{fileExtIcon(file.name)}</span>
      <span className="file-card2-meta">
        <span className="file-card2-name" title={file.name}>{file.name}</span>
        <span className="file-card2-sub">{meta}</span>
      </span>
      <span className="file-card2-actions">
        {canPreview && (
          <button className="file-btn ghost" disabled={!!busy} onClick={() => run("preview", onPreview)} title="Preview in side panel">
            <Eye /> {busy === "preview" ? "Opening…" : "Preview"}
          </button>
        )}
        <button className="file-btn primary" disabled={!!busy} onClick={() => run("dl", onDownload)} title="Download to your computer">
          <Download /> {busy === "dl" ? "Saving…" : "Download"}
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

// Two-layer reasoning panel, like a high-end AI workspace:
//   • collapsed = a one-line activity headline;
//   • expanded = the model's live reasoning + a trace line of what it actually did
//     (searched the web, ran Python, produced files) and the sources it used.
// Auto-opens while streaming so you watch it think; collapses — but stays — once the answer is done.
export function ReasoningPanel({ outer, trace, thinking, summary, sources, streaming }) {
  const [open, setOpen] = useState(false);
  const steps = trace || [];
  if (!steps.length && !summary && !outer && !sources?.length && !thinking) return null;
  const show = open || streaming;
  const title = streaming
    ? (outer?.title || "Thinking…")
    : (outer?.title || summary?.title || "Reasoning");
  return (
    <div className={`think-block${streaming ? " live" : ""}`}>
      <button className="think-head" onClick={() => setOpen((v) => !v)}>
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
                <span className="trace-think-body">{thinking}{streaming ? <span className="caret" /> : null}</span>
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
