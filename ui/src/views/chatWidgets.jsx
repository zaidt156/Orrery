// Leaf UI components for Chat: file chips, generated-file cards, SVG renders, and the
// thinking/working indicators. Kept out of Chat.jsx to keep that file focused.
import { useEffect, useState } from "react";
import { Download, Eye } from "lucide-react";
import { saveClientFile } from "../lib/api.js";

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

// A file produced by the code-execution pipeline: name + size + Preview/Download.
export function GeneratedFileCard({ file, onPreview, onDownload }) {
  const [busy, setBusy] = useState(null);
  const canPreview = PREVIEWABLE_FILE.test(file.name || "");
  async function run(kind, fn) { setBusy(kind); try { await fn(); } finally { setBusy(null); } }
  return (
    <div className="file-card">
      <span className="file-card-icon">{fileExtIcon(file.name)}</span>
      <span className="file-card-meta">
        <span className="file-card-name">{file.name}</span>
        <span className="file-card-size">{formatBytes(file.size)}</span>
      </span>
      {canPreview && (
        <button className="file-chip" disabled={!!busy} onClick={() => run("preview", onPreview)} title="Preview in side panel">
          <Eye /> {busy === "preview" ? "Opening…" : "Preview"}
        </button>
      )}
      <button className="file-chip" disabled={!!busy} onClick={() => run("dl", onDownload)} title="Download to your computer">
        <Download /> {busy === "dl" ? "Saving…" : "Download"}
      </button>
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

// The "Thinking" indicator: a shimmer before the first token, and a collapsible
// reasoning trace (auto-open while streaming, collapsed once the answer is done).
export function ThinkingBlock({ text, streaming }) {
  const [open, setOpen] = useState(false);
  if (!text) {
    return (
      <div className="thinking">
        <span className="think-stars" aria-hidden="true"><i>✦</i><i>✦</i><i>✦</i></span>
        <span className="thinking-label">Thinking…</span>
      </div>
    );
  }
  const show = open || streaming;
  return (
    <div className={`think-block${streaming ? " live" : ""}`}>
      <button className="think-head" onClick={() => setOpen((v) => !v)}>
        {streaming ? "Thinking…" : "Thought process"}
        <span className="think-caret">{show ? "▾" : "▸"}</span>
      </button>
      {show && <div className="think-body">{text}</div>}
    </div>
  );
}
