import { memo, useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Eye,
  FileDown,
  FileSpreadsheet,
  FileText,
  Pencil,
  RefreshCw,
  Repeat2,
  Scale,
  Globe2,
  Telescope,
  WandSparkles,
  X,
} from "lucide-react";
import { AttachIcon, SendIcon } from "../components/icons.jsx";
import Markdown from "../components/Markdown.jsx";
import { isCodeImagePrompt } from "../lib/chatCommands.js";
import { copyTextResult } from "../lib/clipboard.js";
import {
  appendDeltaToThread,
  createClientMessage,
  ensureStreamingAssistant,
  messageKey,
  messageRowPropsEqual,
} from "../lib/chatThread.js";
import { previewFrameSandbox, previewNotice } from "../lib/officePreview.js";
import {
  getModels, listCollections, listConversations, getConversation, createConversation,
  updateConversation, deleteConversation, streamMessage, regenerateMessage,
  downloadMessageExport, streamCodeImage, createArtifact, previewExport, saveClientFile,
  downloadGeneratedFile, previewGeneratedFile, appBundleUrl, stopGeneration, resumeGeneration, listProjects, saveReasoning,
  getDefaults, readFileAsAttachment, getAttachmentText, activateMessageVersion,
} from "../lib/api.js";
import {
  EXPORT_FORMATS, requestedFileFormats, isFileFailureNote,
  extractHtml, stripDocSpec, specFormats, extractSvgs,
} from "./chatHelpers.jsx";
import {
  ReplyFiles, InlineSvg, CodeImageArtifact, GeneratedFileCard, ThinkingPulse, ReasoningPanel, TaskBrainPanel,
  EvaluatePanel, LazyAttachmentImg,
} from "./chatWidgets.jsx";
import {
  appendRawThinking,
  applyReasoningEvent,
  createReasoningSnapshot,
  hasReasoning,
  splitInlineThinking,
} from "./reasoningState.js";

// Reasoning depth modes shown to the user; the stored value is the underlying effort (see backend
// reasoning.py for the canonical mapping). Standard = "" (the provider's own default depth).
const REASONING_MODES = [["", "Standard"], ["low", "Quick"], ["high", "Deep"], ["xhigh", "Max"]];
// Context sizes are offered per model: standard tiers up to the model's real maximum, plus the
// maximum itself — so a 200K model shows 32K/64K/128K/200K, never a 1M it doesn't have.
const CONTEXT_TIERS = [32768, 65536, 131072, 262144, 524288, 1000000];
const fmtTokens = (n) =>
  n >= 1000000 ? `${(n / 1000000).toFixed(n % 1000000 ? 1 : 0)}M` : `${Math.round(n / 1024)}K`;
function contextOptionsFor(maxCtx) {
  const max = Number(maxCtx) > 0 ? Number(maxCtx) : 131072;
  const opts = CONTEXT_TIERS.filter((t) => t < max).map((t) => [String(t), `context: ${fmtTokens(t)}`]);
  opts.push([String(max), `context: ${fmtTokens(max)} (max)`]);
  return opts;
}
const DEFAULT_CTX = 131072;
// A model's real context window from the loaded list (the /api/models entries carry it). Used to
// default a new chat's window to what the model actually supports instead of a blanket 1M.
function modelCtx(list, id) {
  return Number(list.find((m) => m.id === id)?.context_window) || DEFAULT_CTX;
}

// Turn a base64 data URL (how the composer holds a freshly attached image/PDF/office file) into a
// blob URL so the preview pane can render the real file, not a text extract.
function dataUrlToBlobUrl(dataUrl) {
  const comma = dataUrl.indexOf(",");
  const mime = (dataUrl.slice(0, comma).match(/data:([^;]+)/) || [])[1] || "application/octet-stream";
  const bin = atob(dataUrl.slice(comma + 1));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return { url: URL.createObjectURL(new Blob([bytes], { type: mime })), mime };
}

// The header chip shows a short model name; long descriptors ("adaptive thinking", "reasoning")
// and the "<Brand> plan -" prefix become a small plan badge — the menu keeps the full labels.
const MODEL_DESCRIPTOR = /^(adaptive thinking|reasoning|fast( reasoning)?|thinking|default|best available.*)$/i;
function compactModelLabel(label) {
  const parts = String(label || "").split(/\s+[-·]\s+/).map((p) => p.trim()).filter(Boolean);
  if (parts.length <= 1) return { name: label || "", plan: false };
  const isPlan = /\bplan$/i.test(parts[0]) || /^google cli$/i.test(parts[0]);
  if (!isPlan) return { name: label, plan: false };
  const brand = parts[0].replace(/\s*plan$/i, "").replace(/^google cli$/i, "Gemini");
  const names = parts.slice(1).filter((p) => !MODEL_DESCRIPTOR.test(p));
  if (!names.length) return { name: `${brand} (auto)`, plan: true };
  const name = names.join(" ");
  return { name: brand.toLowerCase() === "claude" && !/^claude/i.test(name) ? `${brand} ${name}` : name, plan: true };
}

const CMDS = [
  ["/research", false], ["/image", true],
];

const PROVIDER_NAME = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Google",
  openrouter: "OpenRouter",
  ollama: "Ollama",
  claude_plan: "Claude plan",
  chatgpt_plan: "Codex / ChatGPT plan",
  gemini_plan: "Google CLI",
};

const CHAT_ATTACHMENT_ACCEPT = [
  "image/*", "application/pdf", ".pdf", "text/*",
  ".docx", ".pptx", ".xlsx", ".xlsm",
  ".md", ".markdown", ".csv", ".tsv", ".json", ".txt", ".py", ".js", ".ts", ".jsx", ".tsx",
  ".html", ".css", ".yml", ".yaml", ".xml", ".log", ".sql", ".ini", ".toml",
].join(",");
const CHAT_TEXT_EXT = /\.(txt|md|markdown|csv|tsv|json|ya?ml|xml|html?|css|js|jsx|ts|tsx|py|java|c|cpp|cs|go|rs|rb|php|sh|sql|ini|toml|log)$/i;
const CHAT_OFFICE_EXT = /\.(docx|pptx|xlsx|xlsm)$/i;

export default function Chat({ features = null }) {
  const researchEnabled = features?.deep_research !== false;
  const webSearchEnabled = features?.web_search !== false;
  const [convos, setConvos] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [models, setModels] = useState([]);
  const [model, setModel] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [modelMenu, setModelMenu] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const [banner, setBanner] = useState(null);
  const threadRef = useRef(null);
  const abortRef = useRef(null);
  const activeIdRef = useRef(null);
  const fileRef = useRef(null);
  const composerRef = useRef(null);
  const messageActionsRef = useRef({});
  const [attachments, setAttachments] = useState([]);
  const [useData, setUseData] = useState(false);
  const [researchMode, setResearchMode] = useState(false);
  const [webMode, setWebMode] = useState(false);
  const [collections, setCollections] = useState([]);
  const [dataColl, setDataColl] = useState("");
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [effort, setEffort] = useState("");
  const [artifact, setArtifact] = useState(null); // preview sidebar state; iframe capabilities deny by default

  useEffect(() => {
    if (!researchEnabled) setResearchMode(false);
  }, [researchEnabled]);

  useEffect(() => {
    if (!webSearchEnabled) setWebMode(false);
  }, [webSearchEnabled]);

  async function openHtmlPreview(html, title) {
    try {
      const url = await createArtifact(html);
      setArtifact({ url, title: title || "Preview", frameSandbox: previewFrameSandbox(true) });
    } catch (e) {
      setBanner(String(e.message || e));
    }
  }

  async function openFilePreview(messageId, format, title) {
    if (!activeId || !messageId) return;
    setBanner(null);
    try {
      const preview = await previewExport(activeId, messageId, format);
      const label = EXPORT_FORMATS.find((item) => item.id === format)?.label || format.toUpperCase();
      setArtifact({
        url: preview.url,
        title: title || `${label} preview`,
        frameSandbox: previewFrameSandbox(false),
      });
    } catch (e) {
      setBanner(String(e.message || e));
    }
  }

  function openSvgPreview(svg, title) {
    setArtifact({ image: `data:image/svg+xml,${encodeURIComponent(svg)}`, title: title || "SVG preview" });
  }

  // Render a real file in the preview pane by its type: image → <img>, av → player, html → sandboxed
  // iframe, everything else (PDF, Office, text) → a plain iframe that shows the file as-is.
  function showFileArtifact(url, mime, name, preview = null) {
    const m = mime || "";
    const notice = previewNotice(preview);
    if (m.startsWith("image/")) setArtifact({ image: url, title: name, notice });
    else if (m.startsWith("video/")) setArtifact({ media: url, mediaType: "video", title: name, notice });
    else if (m.startsWith("audio/")) setArtifact({ media: url, mediaType: "audio", title: name, notice });
    else setArtifact({ url, title: name, frameSandbox: previewFrameSandbox(false), notice });
  }

  async function openGeneratedPreview(file) {
    setBanner(null);
    try {
      const preview = await previewGeneratedFile(file.id);
      showFileArtifact(preview.url, preview.mime, file.name, preview);
    } catch (e) {
      setBanner(String(e.message || e));
    }
  }

  // Open a generated app bundle live in the side panel. previewFrameSandbox(true) gives an
  // interactive but opaque-origin iframe (allow-scripts, NO allow-same-origin), so the app cannot
  // touch the workspace or its token; the server's strict CSP blocks any network egress.
  function openApp(file) {
    setBanner(null);
    setArtifact({
      url: appBundleUrl(file.id),
      title: file.name?.replace(/\.zip$/i, "") || "App",
      frameSandbox: previewFrameSandbox(true),
    });
  }
  const [contextWindow, setContextWindow] = useState("1000000");
  const [evalFor, setEvalFor] = useState(null); // {messageId, content} — the answer being evaluated
  const [copiedKey, setCopiedKey] = useState(""); // which copy button just fired (✓ flash)
  const [convoTotal, setConvoTotal] = useState(0); // sidebar pagination (plan Task 2)

  async function loadMoreConvos() {
    try {
      const page = await listConversations(100, convos.length);
      setConvos((prev) => {
        const seen = new Set(prev.map((c) => c.id));
        return [...prev, ...(page.conversations || []).filter((c) => !seen.has(c.id))];
      });
      setConvoTotal(page.total ?? convoTotal);
    } catch (e) {
      setBanner(String(e.message || e));
    }
  }

  useEffect(() => {
    let alive = true;
    (async () => {
      const modelsReq = getModels();
      const collectionsReq = listCollections();
      const projectsReq = listProjects();
      let hasConversations = false;
      let startBlankProject = false;

      try {
        const c = await listConversations();
        if (!alive) return;
        setConvos(c.conversations);
        setConvoTotal(c.total ?? c.conversations.length);
        hasConversations = c.conversations.length > 0;
        const newProjectId = sessionStorage.getItem("orrery_new_project_chat");
        const pending = sessionStorage.getItem("orrery_open_conversation");
        // open the handoff target directly by id — it may live beyond the first page
        const target = pending ? { id: pending } : null;
        if (newProjectId) {
          sessionStorage.removeItem("orrery_new_project_chat");
          const firstMessage = sessionStorage.getItem("orrery_project_first_message");
          sessionStorage.removeItem("orrery_project_first_message");
          startBlankProject = true;
          activeIdRef.current = null;
          setActiveId(null);
          setMessages([]);
          setProjectId(newProjectId);
          setSystemPrompt("");
          setEffort("");
          setContextWindow("1000000");
          if (firstMessage) setInput(firstMessage);  // composer pre-filled; user reviews and sends
        } else if (target) {
          sessionStorage.removeItem("orrery_open_conversation");
          await open(target.id);
        } else if (hasConversations) {
          await open(c.conversations[0].id);
        }
      } catch (e) {
        if (alive) setBanner(String(e.message || e));
      }

      const [m, cols, projs] = await Promise.allSettled([modelsReq, collectionsReq, projectsReq]);
      if (!alive) return;
      if (m.status === "fulfilled") {
        setModels(m.value.models);
        const preferred = sessionStorage.getItem("orrery_preferred_model");
        const preferredModel = m.value.models.find((item) => item.id === preferred);
        if (preferredModel) {
          setActiveId(null);
          setMessages([]);
          setModel(preferredModel.id);
          setSystemPrompt("");
          setEffort("");
          setContextWindow(String(modelCtx(m.value.models, preferredModel.id)));  // this model's real window
          sessionStorage.removeItem("orrery_preferred_model");
        } else if (!hasConversations || startBlankProject) {
          // workspace defaults (Settings → General): default model + reasoning depth for new chats
          try {
            const d = await getDefaults();
            const defModel = m.value.models.find((x) => x.id === d.model);
            const chosenId = defModel ? defModel.id : (m.value.models[0] ? m.value.models[0].id : "");
            setModel(chosenId);
            setContextWindow(String(modelCtx(m.value.models, chosenId)));  // default to the model's max, not 1M
            if (d.effort) setEffort(d.effort);
          } catch {
            const firstId = m.value.models[0] ? m.value.models[0].id : "";
            setModel(firstId);
            setContextWindow(String(modelCtx(m.value.models, firstId)));
          }
        }
      } else {
        setBanner(String(m.reason?.message || m.reason));
      }
      if (cols.status === "fulfilled") {
        setCollections(cols.value.collections);
        if (cols.value.collections[0]) setDataColl(cols.value.collections[0].id);
      }
      if (projs.status === "fulfilled") {
        setProjects(projs.value.projects);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    // only keep pinned to the bottom if the user is already there — no yanking, less jump
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [input]);

  useEffect(() => { activeIdRef.current = activeId; }, [activeId]);

  // Keep the model picker in sync when accounts/models change in Settings (connect/disconnect,
  // key added/removed, model toggled) — refetch and drop a selection that's no longer available.
  useEffect(() => {
    async function refreshModels() {
      try {
        const m = await getModels();
        setModels(m.models);
        setModel((cur) => (m.models.some((x) => x.id === cur) ? cur : (m.models[0]?.id || "")));
      } catch { /* keep the current list on a transient failure */ }
    }
    window.addEventListener("orrery-models-changed", refreshModels);
    return () => window.removeEventListener("orrery-models-changed", refreshModels);
  }, []);

  useEffect(() => {
    async function refreshProjects() {
      try {
        const data = await listProjects();
        setProjects(data.projects);
      } catch { /* keep current project list on transient failures */ }
    }
    window.addEventListener("orrery-projects-changed", refreshProjects);
    return () => window.removeEventListener("orrery-projects-changed", refreshProjects);
  }, []);

  async function open(id) {
    const full = await getConversation(id);
    activeIdRef.current = id;
    setActiveId(id);
    setMessages(full.messages.map(hydrateReasoning));
    setModel(full.model);
    setProjectId(full.project_id || "");
    setSystemPrompt(full.system_prompt || "");
    setEffort(full.effort || "");
    setContextWindow(String(full.context_window || 1000000));
    setPromptOpen(false);
    if (full.running && !sending) resumeRun(id);  // a reply is still being generated — re-attach
  }

  async function chooseEffort(v) {
    setEffort(v);
    if (activeId) await updateConversation(activeId, { effort: v || null });
  }

  async function chooseContextWindow(v) {
    setContextWindow(v);
    if (activeId) {
      await updateConversation(activeId, { context_window: Number(v) });
    }
  }

  async function chooseProject(v) {
    setProjectId(v);
    if (activeId) {
      const patch = await updateConversation(activeId, { project_id: v || null });
      setConvos((p) => p.map((c) => (c.id === activeId ? { ...c, project_id: patch.project_id || null } : c)));
    }
  }

  async function newChat() {
    if (!model) { setBanner("Connect an account or add an API key in Settings to pick a model."); return; }
    const conv = await createConversation(
      model,
      systemPrompt || null,
      effort || null,
      Number(contextWindow),
      projectId || null
    );
    setConvos((p) => [{ id: conv.id, title: conv.title, model: conv.model, project_id: conv.project_id || null }, ...p]);
    activeIdRef.current = conv.id;
    setActiveId(conv.id);
    setMessages([]);
  }

  async function removeChat(id, e) {
    e.stopPropagation();
    if (!window.confirm("Delete this chat? This can't be undone.")) return;
    try { await deleteConversation(id); } catch { /* already gone */ }
    setConvos((p) => p.filter((c) => c.id !== id));
    if (id === activeId) { setActiveId(null); setMessages([]); }
  }

  async function toggleModelMenu() {
    const opening = !modelMenu;
    setModelMenu(opening);
    if (opening) {
      try { const m = await getModels(); setModels(m.models); } catch { /* keep list */ }
    }
  }

  async function chooseModel(id) {
    setModel(id);
    setModelMenu(false);
    // Track the new model's real window. If the user was at the old model's full window (the default),
    // move to the new model's full window; if they'd deliberately dialed it below the old max, keep
    // that choice, clamped to the new model's max. This keeps the window "set according to the model".
    const oldMax = modelCtx(models, model);
    const newMax = modelCtx(models, id);
    const cur = Number(contextWindow) || newMax;
    const next = cur >= oldMax ? newMax : Math.min(cur, newMax);
    setContextWindow(String(next));
    if (activeId) {
      await updateConversation(activeId, { model: id, context_window: next });
      setConvos((p) => p.map((c) => (c.id === activeId ? { ...c, model: id } : c)));
    }
  }

  async function savePrompt() {
    if (activeId) await updateConversation(activeId, { system_prompt: systemPrompt });
    setPromptOpen(false);
  }

  // Shared streaming runner: appends an assistant placeholder, then applies events.
  async function runStream(cid, start) {
    setSending(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const isActive = () => activeIdRef.current === cid;
    if (isActive()) {
      setMessages((p) => [...p, createClientMessage({ role: "assistant", content: "", streaming: true })]);
    }
    const setLast = (patch) => {
      if (!isActive()) return;
      setMessages((p) => {
        const a = [...p];
        if (!a.length || a[a.length - 1].role !== "assistant" || !a[a.length - 1].streaming) {
          a.push(createClientMessage({ role: "assistant", content: "", streaming: true }));
        }
        a[a.length - 1] = { ...a[a.length - 1], ...patch };
        return a;
      });
    };
    let savedMsgId = null;
    let reasoningAcc = createReasoningSnapshot();
    // High-frequency token deltas coalesce into ONE React commit per animation frame — the
    // per-token full-thread re-render was the main "long chats stream janky" cause. Any other
    // event (and every stream-end path) flushes first, so event ordering never changes.
    let pendingDelta = "", pendingThinking = "", flushHandle = 0;
    const flushDeltas = () => {
      if (flushHandle) { cancelAnimationFrame(flushHandle); flushHandle = 0; }
      if (pendingDelta) { const d = pendingDelta; pendingDelta = ""; appendDelta(setMessages, d); }
      if (pendingThinking) { const t = pendingThinking; pendingThinking = ""; appendThinking(setMessages, t); }
    };
    const scheduleFlush = () => {
      if (!flushHandle) flushHandle = requestAnimationFrame(() => { flushHandle = 0; flushDeltas(); });
    };
    const handleEvent = (ev) => {
        // Keep the persisted snapshot on the same exact path as the live panel. In particular,
        // reasoning_delta text is appended verbatim and compatibility events are stored once.
        reasoningAcc = applyReasoningEvent(reasoningAcc, ev);
        if (ev.message_id) savedMsgId = ev.message_id;

        if (ev.project) {
          setProjects((p) => [ev.project, ...p.filter((item) => item.id !== ev.project.id)]);
          if (isActive()) setProjectId(ev.project.id);
          setConvos((p) => p.map((c) => (c.id === cid ? { ...c, project_id: ev.project.id } : c)));
          window.dispatchEvent(new CustomEvent("orrery-projects-changed"));
          return;
        }
        if (ev.title) {
          setConvos((p) => p.map((c) => (c.id === cid ? { ...c, title: ev.title } : c)));
          return;
        }
        if (!isActive()) return;

        if (ev.delta) { pendingDelta += ev.delta; scheduleFlush(); return; }
        if (ev.reasoning_delta) { pendingThinking += ev.reasoning_delta; scheduleFlush(); return; }
        flushDeltas();  // buffered text lands before any other event applies

        if (ev.reasoning_outer) setLast({ outer: ev.reasoning_outer });
        else if (ev.reasoning_step) appendTrace(setMessages, ev.reasoning_step);
        else if (ev.reasoning_event) appendTrace(setMessages, ev.reasoning_event);
        else if (ev.reasoning_summary) setLast({ summary: ev.reasoning_summary });
        else if (ev.artifact) setLast({ artifacts: [ev.artifact] });
        else if (ev.files) setLast({ artifacts: ev.files, status: "" });
        else if (ev.project) {
          setProjects((p) => [ev.project, ...p.filter((item) => item.id !== ev.project.id)]);
          setProjectId(ev.project.id);
          setConvos((p) => p.map((c) => (c.id === cid ? { ...c, project_id: ev.project.id } : c)));
          window.dispatchEvent(new CustomEvent("orrery-projects-changed"));
        }
        else if (ev.status) appendStep(setMessages, ev.status);
        else if (ev.title) setConvos((p) => p.map((c) => (c.id === cid ? { ...c, title: ev.title } : c)));
        else if (ev.sources) setLast({ sources: ev.sources });
        else if (ev.message_id) setLast({ id: ev.message_id });
        else if (ev.message_usage) setLast({ tokens: ev.message_usage });
        else if (ev.resumed) appendStep(setMessages, "Resuming background generation…");
        else if (ev.error) setLast({ content: ev.error, error: true, streaming: false });
        else if (ev.done) setLast({ streaming: false });
    };
    try {
      const streamResult = await start(handleEvent, ctrl.signal);
      flushDeltas();
      if (streamResult?.done === false && isActive()) {
        try {
          const full = await getConversation(cid);
          if (full.running) {
            appendStep(setMessages, "Connection ended before completion; reattaching to the running response...");
            const resumed = await resumeGeneration(cid, (ev) => {
              if (isActive()) handleEvent(ev);
            }, ctrl.signal);
            if (resumed?.done === false) appendStep(setMessages, "The response is still running in the background.");
          } else {
            setMessages(full.messages.map(hydrateReasoning));
          }
        } catch {
          setLast({ streaming: false });
        }
      }
    } catch (e) {
      flushDeltas();  // keep whatever streamed before the failure/abort
      if (e.name === "AbortError") setLast({ streaming: false }); // keep the partial reply
      else setLast({ content: String(e.message || e), error: true, streaming: false });
    } finally {
      flushDeltas();
      setSending(false);
      abortRef.current = null;
      if (savedMsgId && hasReasoning(reasoningAcc)) {
        try {
          // Wait for the snapshot before submitPrompt/syncThread reloads the saved conversation.
          await saveReasoning(cid, savedMsgId, reasoningAcc);
        } catch { /* keep the complete local panel if persistence is temporarily unavailable */ }
      }
    }
  }

  // Reload the saved thread (ids + ‹ › version metadata land only via a fetch — the stream
  // doesn't carry them). Keeps whatever streamed if the fetch fails. Fields that only exist
  // locally right after a stream (reasoning being saved fire-and-forget, data-URL attachment
  // thumbnails, live token counts) are carried over so the refresh never blanks them.
  async function syncThread(cid) {
    try {
      const full = await getConversation(cid);
      if (cid !== activeIdRef.current) return;
      setMessages((prev) => {
        const local = new Map(prev.filter((x) => x.id).map((x) => [x.id, x]));
        return full.messages.map((m) => {
          const base = hydrateReasoning(m);
          const mine = local.get(m.id);
          if (!mine) return base;
          const out = { ...base };
          if (!m.reasoning && (mine.trace?.length || mine.thinking || mine.outer || mine.summary || mine.sources)) {
            out.thinking = mine.thinking; out.trace = mine.trace; out.outer = mine.outer;
            out.summary = mine.summary; out.sources = mine.sources;
          }
          if (mine.attachments?.length && !base.attachments?.length) out.attachments = mine.attachments;
          if (mine.tokens && !base.tokens) out.tokens = mine.tokens;
          return out;
        });
      });
    } catch { /* keep what streamed */ }
  }

  // Re-attach to a generation that kept running in the background while we were away, then
  // reload the saved reply (the resume stream only carries the tail it didn't already emit).
  async function resumeRun(cid) {
    await runStream(cid, (onEvent, signal) => resumeGeneration(cid, onEvent, signal));
    await syncThread(cid);
  }

  async function submitPrompt(
    rawContent,
    rawAttachments = [],
    { clearComposer = false, siblingOf = null, webSearch = false } = {}
  ) {
    const content = String(rawContent || "").trim();
    if ((!content && rawAttachments.length === 0) || sending) return;
    if (!model) { setBanner("Connect an account or add an API key in Settings to pick a model."); return; }

    let cid = activeId;
    if (!cid) {
      const conv = await createConversation(
        model,
        systemPrompt || null,
        effort || null,
        Number(contextWindow),
        projectId || null
      );
      cid = conv.id;
      activeIdRef.current = cid;
      setActiveId(cid);
      setConvos((p) => [{ id: conv.id, title: conv.title, model: conv.model, project_id: conv.project_id || null }, ...p]);
    }
    const atts = rawAttachments;
    const collectionId = useData && dataColl ? dataColl : null;
    if (clearComposer) {
      setInput("");
      setAttachments([]);
    }
    const codeImage = atts.length === 0 && isCodeImagePrompt(content);
    const sid = codeImage ? null : siblingOf; // the code-image route has no in-place versioning
    if (sid) {
      // resubmit-in-place: the revised prompt replaces the old one on screen (the old version
      // stays switchable via ‹ ›), so drop it and everything after before streaming the new turn
      setMessages((p) => {
        const at = p.findIndex((x) => x.id === sid);
        return at >= 0 ? p.slice(0, at) : p;
      });
    }
    setMessages((p) => [...p, createClientMessage({ role: "user", content, attachments: atts })]);
    await runStream(cid, (onEvent, signal) =>
      codeImage
        ? streamCodeImage(cid, content, onEvent, signal)
        : streamMessage(cid, content, atts, collectionId, onEvent, signal, sid, webSearch)
    );
    await syncThread(cid); // pick up saved ids + ‹ › version metadata
  }

  async function send() {
    // Deep Research toggle routes the turn through the decompose→gather→cited-report workflow.
    const text = researchEnabled && researchMode && input.trim() && !/^\s*\/research\b/i.test(input)
      ? `/research ${input.trim()}`
      : input;
    try {
      await submitPrompt(text, attachments, {
        clearComposer: true,
        webSearch: webSearchEnabled && webMode,
      });
    } finally {
      // Web access is approved one message at a time; make the next outbound search explicit too.
      setWebMode(false);
    }
  }

  async function resubmitPrompt(message) {
    // saved messages revise in place (a new ‹ › version); unsaved ones fall back to an append
    await submitPrompt(message.content || "", message.attachments || [], { siblingOf: message.id || null });
  }

  function editPrompt(text) {
    setInput(text || "");
    composerRef.current?.focus();
  }

  async function rewritePrompt(text) {
    const prompt = (text || "").trim();
    if (!prompt) return;
    await submitPrompt(
      `Rewrite this prompt to be clearer and more complete while preserving the original intent. Return only the rewritten prompt.\n\n${prompt}`,
      []
    );
  }

  async function regen() {
    if (sending || !activeId) return;
    setMessages((p) => {
      const a = [...p];
      while (a.length && a[a.length - 1].role === "assistant") a.pop();
      return a;
    });
    const cid = activeId;
    await runStream(cid, (onEvent, signal) => regenerateMessage(cid, onEvent, signal));
    await syncThread(cid); // the old reply is now a switchable ‹ › version of the new one
  }

  async function switchVersion(targetId) {
    if (sending || !activeId) return;
    const cid = activeId;
    try {
      const full = await activateMessageVersion(cid, targetId);
      if (cid === activeIdRef.current) setMessages(full.messages.map(hydrateReasoning));
    } catch (e) {
      setBanner(String(e.message || e));
    }
  }

  function stop() {
    if (activeId) stopGeneration(activeId); // cancel on the backend too (it now runs detached)
    abortRef.current?.abort();
  }

  async function copy(text, key, event) {
    event?.preventDefault();
    event?.stopPropagation();
    const result = await copyTextResult(String(text ?? ""));
    if (!result.ok) {
      setBanner(`Copy failed: ${result.error || "clipboard is unavailable."}`);
      return;
    }
    setBanner(null);
    if (key) {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey((cur) => (cur === key ? "" : cur)), 1200);
    }
  }

  // Open an attachment as the ACTUAL file (a PDF renders as a PDF, an image as an image), not a text
  // extract. Reloaded files fetch their stored bytes by id; a just-sent file is still in the composer
  // as a data URL; plain-text files carry their text; only as a last resort do we show indexed text.
  async function openAttachment(a) {
    try {
      if (a.file_id) {
        const preview = await previewGeneratedFile(a.file_id);
        showFileArtifact(preview.url, preview.mime || a.mime, a.name, preview);
        return;
      }
      if (typeof a.content === "string" && a.content.startsWith("data:")) {
        const { url, mime } = dataUrlToBlobUrl(a.content);
        showFileArtifact(url, a.mime || mime, a.name);
        return;
      }
      if (a.kind === "text" && a.content != null) {
        const url = URL.createObjectURL(new Blob([a.content], { type: "text/plain;charset=utf-8" }));
        setArtifact({ url, title: a.name, frameSandbox: previewFrameSandbox(false) });
        return;
      }
      const r = await getAttachmentText(activeId, a.name);
      const url = URL.createObjectURL(new Blob([r.text], { type: "text/plain;charset=utf-8" }));
      setArtifact({ url, title: a.name, frameSandbox: previewFrameSandbox(false) });
    } catch {
      setBanner(`No stored preview for ${a.name} — it may not have been saved.`);
    }
  }

  async function handleFiles(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    await addFiles(files);
  }

  async function addFiles(files) {
    const ok = [];
    for (const f of files) {
      const isImage = f.type.startsWith("image/");
      const isPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name);
      const isText = f.type.startsWith("text/") || CHAT_TEXT_EXT.test(f.name);
      const isOffice = CHAT_OFFICE_EXT.test(f.name);
      if (!isImage && !isPdf && !isText && !isOffice) {
        const legacyWord = /\.doc$/i.test(f.name) ? " Legacy .doc files are not readable yet; save as .docx and attach again." : "";
        setBanner(`Unsupported file type (skipped ${f.name}).${legacyWord}`);
        continue;
      }
      if (f.size > 12 * 1024 * 1024) { setBanner(`${f.name} is too large (max 12 MB).`); continue; }
      ok.push(await readFileAsAttachment(f));
    }
    if (ok.length) setAttachments((p) => [...p, ...ok]);
  }

  const fileIcon = (kind) => (kind === "image" ? "🖼" : kind === "pdf" ? "📕" : "📄");

  const title = convos.find((c) => c.id === activeId)?.title || "New chat";
  const projectName = (id) => projects.find((p) => p.id === id)?.name || "";
  const current = models.find((m) => m.id === model);
  const modelLabel = current?.label || model || "pick a model";
  const compact = compactModelLabel(modelLabel);
  const noKey = !!model && !current;
  const prefix = model.includes("/") ? model.split("/")[0] : "";
  const provider = PROVIDER_NAME[prefix] || "this provider";

  Object.assign(messageActionsRef.current, {
    copy,
    editPrompt,
    fileIcon,
    openApp,
    openAttachment,
    openFilePreview,
    openGeneratedPreview,
    openHtmlPreview,
    openSvgPreview,
    regen,
    resubmitPrompt,
    rewritePrompt,
    setBanner,
    setEvalFor,
    switchVersion,
  });

  let nearestUserMessage = null;
  const messageRows = messages.map((message, index) => {
    const precedingPrompt = nearestUserMessage?.content || "";
    const lastPrompt = nearestUserMessage;
    if (message.role === "user") nearestUserMessage = message;
    const copyPrefix = message.role === "user" ? "p" : "r";
    return (
      <ChatMessageRow
        key={messageKey(message, index)}
        message={message}
        index={index}
        isLast={index === messages.length - 1}
        sending={sending}
        copied={copiedKey === `${copyPrefix}${index}`}
        activeId={activeId}
        activeTitle={title}
        precedingPrompt={precedingPrompt}
        lastPrompt={lastPrompt}
        actions={messageActionsRef}
      />
    );
  });

  return (
    <section className="view">
      <aside className="chat-side">
        <button className="btn primary" onClick={newChat}>+ New chat</button>
        <input className="search" placeholder="Search chats…" />
        <div className="convo-list">
          {convos.length === 0 && <div className="convo-empty">No chats yet</div>}
          {convos.map((c) => (
            <div
              key={c.id}
              className={`convo${c.id === activeId ? " active" : ""}`}
              tabIndex={0}
              onClick={() => open(c.id)}
            >
              <div className="c-main">
                <div className="c-title">{c.title}</div>
                <div className="c-meta">{projectName(c.project_id) ? `${projectName(c.project_id)} · ` : ""}{c.model}</div>
              </div>
              <button className="convo-del" title="Delete chat" onClick={(e) => removeChat(c.id, e)}>×</button>
            </div>
          ))}
          {convos.length < convoTotal && (
            <button className="convo-more" onClick={loadMoreConvos}>
              Show older chats ({convoTotal - convos.length} more)
            </button>
          )}
        </div>
        <TaskBrainPanel onOpenConversation={open} />
      </aside>

      <div className="chat-main">
        <div className="chat-header">
          <span className="view-title">{title}</span>
          <div className="pickwrap">
            <span className={`pill model-pill${noKey ? " no-key" : ""}`} title={`${modelLabel} — switch model`} onClick={toggleModelMenu}>
              <b>{compact.name}</b>
              {compact.plan && <em className="plan-tag">plan</em>}
              {noKey ? " · no key" : ""}
              <span className="pill-caret">⌄</span>
            </span>
            {modelMenu && (
              <div className="model-menu">
                {models.length === 0 && (
                  <div className="model-opt" style={{ cursor: "default", color: "var(--faint)" }}>
                    No active models — add a key, connect Claude plan, or turn models on in Settings
                  </div>
                )}
                {models.map((m) => (
                  <div
                    key={m.id}
                    className={`model-opt${m.id === model ? " on" : ""}`}
                    onClick={() => chooseModel(m.id)}
                  >
                    {m.label}
                  </div>
                ))}
              </div>
            )}
          </div>
          <span className="pill" title="Edit system prompt" onClick={() => setPromptOpen((v) => !v)}>
            System prompt
          </span>
          <select
            className="effort-pick context-pick project-pick"
            value={projectId}
            onChange={(e) => chooseProject(e.target.value)}
            title="Attach this chat to a project. Project instructions are used as trusted context."
          >
            <option value="">No project</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select
            className="effort-pick context-pick"
            value={contextWindow}
            onChange={(e) => chooseContextWindow(e.target.value)}
            title="Per-chat token window, limited to what this model actually supports. Orrery reserves 25% for the reply."
          >
            {(() => {
              const maxCtx = models.find((m) => m.id === model)?.context_window || 131072;
              const opts = contextOptionsFor(maxCtx);
              // keep the stored value selectable even if it predates the per-model limits
              if (!opts.some(([v]) => v === contextWindow)) opts.push([contextWindow, `context: ${fmtTokens(Number(contextWindow) || 0)}`]);
              return opts.map(([value, label]) => <option key={value} value={value}>{label}</option>);
            })()}
          </select>
          <select className="effort-pick" value={effort === "medium" ? "" : effort} onChange={(e) => chooseEffort(e.target.value)} title="Reasoning depth (where the model supports it)">
            {REASONING_MODES.map(([v, label]) => <option key={v || "std"} value={v}>{label}</option>)}
          </select>
          <span className="rag-toggle" title="Answer using your document collections">
            Use my data
            <span
              className={`toggle${useData ? " on" : ""}`}
              role="switch"
              aria-checked={useData}
              tabIndex={0}
              onClick={() => {
                if (!collections.length) { setBanner("Create a collection in the Data tab first."); return; }
                setUseData((v) => !v);
              }}
            />
            {useData && collections.length > 0 && (
              <select
                value={dataColl}
                onChange={(e) => setDataColl(e.target.value)}
                style={{ background: "var(--bg2)", border: "1px solid var(--line)", borderRadius: "6px", color: "var(--muted)", fontSize: "11px", padding: "2px 6px", fontFamily: "var(--font-mono)" }}
              >
                {collections.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.chunks})</option>)}
              </select>
            )}
          </span>
        </div>

        {noKey && (
          <div className="model-warn">
            No connected account or key for <b>{provider}</b> — open the model menu to pick an available route, or
            update <b>Settings</b>.
          </div>
        )}

        {promptOpen && (
          <div className="sys-panel">
            <label>System prompt</label>
            <textarea
              rows={3}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Optional instructions that guide every reply in this chat…"
            />
            <div className="sys-actions">
              <button className="btn primary" onClick={savePrompt}>Save</button>
              <button className="btn ghost" onClick={() => setPromptOpen(false)}>Cancel</button>
            </div>
          </div>
        )}

        {banner && <div className="chat-banner">{banner}</div>}

        <div
          className="thread"
          ref={threadRef}
          onDragOver={(e) => { e.preventDefault(); }}
          onDrop={(e) => { e.preventDefault(); if (e.dataTransfer?.files?.length) addFiles(Array.from(e.dataTransfer.files)); }}
        >
          {messages.length === 0 && (
            <div className="thread-empty">
              <div className="constellation">✦ &nbsp; · &nbsp; ✦ &nbsp;· &nbsp;✦</div>
            </div>
          )}
          {messageRows}
        </div>

        <div className="composer">
          <div className="cmd-row">
            <span className="cmd-lead">available commands:</span>
            {CMDS.map(([c, warm]) => (
              <span key={c} className={`cmd-chip${warm ? " warm" : ""}`} onClick={() => setInput(c + " ")}>{c}</span>
            ))}
          </div>
          {attachments.length > 0 && (
            <div className="attach-row">
              {attachments.map((a, i) => (
                a.kind === "image" ? (
                  <span className="attach-chip attach-chip-img" key={i} title={a.name}>
                    <img src={a.content} alt={a.name} />
                    <span className="attach-imgname">{a.name}</span>
                    <button onClick={() => setAttachments((p) => p.filter((_, j) => j !== i))}>×</button>
                  </span>
                ) : (
                  <span className="attach-chip" key={i}>
                    {fileIcon(a.kind)} {a.name}
                    <button onClick={() => setAttachments((p) => p.filter((_, j) => j !== i))}>×</button>
                  </span>
                )
              ))}
            </div>
          )}
          <div className="composer-box">
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              accept={CHAT_ATTACHMENT_ACCEPT}
              onChange={handleFiles}
            />
            <button className="icon-btn" aria-label="Attach file" title="Attach images, PDFs, Office docs, or text files" onClick={() => fileRef.current?.click()}><AttachIcon /></button>
            {webSearchEnabled && (
              <button
                className={`research-toggle${webMode ? " on" : ""}`}
                aria-label="Use web search for this message"
                aria-pressed={webMode}
                title="Use web search for this message. The screened query leaves this device; common PII and secrets are masked first."
                onClick={() => setWebMode((v) => !v)}
              >
                <Globe2 /> {webMode ? "Web" : ""}
              </button>
            )}
            {researchEnabled && (
              <button
                className={`research-toggle${researchMode ? " on" : ""}`}
                aria-pressed={researchMode}
                title={webMode
                  ? "Deep Research: break the question down, search your documents and the web, and write a cited report"
                  : "Deep Research: break the question down and search your documents. Turn on Web to include current web results."}
                onClick={() => setResearchMode((v) => !v)}
              >
                <Telescope /> {researchMode ? "Research" : ""}
              </button>
            )}
            <textarea
              ref={composerRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              onPaste={(e) => {
                const files = Array.from(e.clipboardData?.files || []);
                if (files.length) { e.preventDefault(); addFiles(files); }  // paste screenshots/files directly
              }}
              placeholder="Ask anything, attach files or screenshots, or use the available Chat tools…"
            />
            {sending ? (
              <button className="send stop" aria-label="Stop" title="Stop" onClick={stop}>
                <span className="stop-sq" />
              </button>
            ) : (
              <button className="send" aria-label="Send" onClick={send}><SendIcon /></button>
            )}
          </div>
          <div className="hint">saved as you go — in your database, nowhere else</div>
        </div>
      </div>

      {artifact && (
        <aside className="artifact-panel">
          <div className="artifact-bar">
            <span className="artifact-title">{artifact.title || "Preview"}</span>
            <div className="artifact-actions">
              {artifact.url && <a className="artifact-btn" href={artifact.url} target="_blank" rel="noreferrer" title="Open in your browser">Open ↗</a>}
              <button className="artifact-btn" title="Close preview" aria-label="Close preview" onClick={() => setArtifact(null)}><X /></button>
            </div>
          </div>
          {artifact.notice && (
            <div className={`artifact-preview-notice ${artifact.notice.state}`} role="status">
              <strong>{artifact.notice.label}</strong>
              {artifact.notice.hint && <span>{artifact.notice.hint}</span>}
            </div>
          )}
          {artifact.image ? (
            <div className="artifact-frame artifact-image"><img src={artifact.image} alt="SVG preview" /></div>
          ) : artifact.mediaType === "video" ? (
            <div className="artifact-frame artifact-media"><video src={artifact.media} controls playsInline /></div>
          ) : artifact.mediaType === "audio" ? (
            <div className="artifact-frame artifact-media"><audio src={artifact.media} controls /></div>
          ) : (
            <iframe
              className="artifact-frame"
              src={artifact.url}
              title={artifact.frameSandbox ? "Interactive HTML preview" : "File preview"}
              sandbox={artifact.frameSandbox ?? previewFrameSandbox(false)}
            />
          )}
        </aside>
      )}

      {evalFor && activeId && (
        <EvaluatePanel
          convId={activeId}
          messageId={evalFor.messageId}
          models={models}
          currentModel={model}
          onClose={() => setEvalFor(null)}
          onAdopted={(text, adoptedModel) => {
            setMessages((p) => p.map((x) => (x.id === evalFor.messageId ? { ...x, content: text, model: adoptedModel || x.model } : x)));
            setEvalFor(null);
          }}
        />
      )}
    </section>
  );
}


const ChatMessageRow = memo(function ChatMessageRow(props) {
  return props.message.role === "user"
    ? <UserMessageRow {...props} />
    : <AssistantMessageRow {...props} />;
}, messageRowPropsEqual);


function UserMessageRow({ message, index, sending, copied, actions }) {
  const current = actions.current;
  const attachments = message.attachments?.length
    ? message.attachments
    : (message.artifacts || [])
      .filter((artifact) => artifact.kind === "attachment")
      .map((artifact) => ({
        name: artifact.name,
        kind: artifact.att || "file",
        mime: artifact.mime,
        file_id: artifact.file_id,
      }));
  const promptText = (message.content || "").replace(/\n*📎 .*$/s, "");
  const copyKey = `p${index}`;

  return (
    <div className="msg user">
      {promptText && <div className="prompt-text"><Markdown plain>{promptText}</Markdown></div>}
      {attachments.length > 0 && (
        <div className="msg-attach">
          {attachments.map((attachment, attachmentIndex) => (
            attachment.kind === "image" && attachment.content
              ? (
                <figure
                  key={attachmentIndex}
                  className="msg-thumb-fig"
                  onClick={() => current.openAttachment(attachment)}
                  title="Click to view full size"
                >
                  <img src={attachment.content} alt={attachment.name} className="msg-thumb" />
                  <figcaption>{attachment.name}</figcaption>
                </figure>
              )
              : attachment.kind === "image" && attachment.file_id
                ? (
                  <LazyAttachmentImg
                    key={attachmentIndex}
                    fileId={attachment.file_id}
                    name={attachment.name}
                    onClick={() => current.openAttachment(attachment)}
                  />
                )
                : (
                  <button
                    key={attachmentIndex}
                    className="attach-chip"
                    onClick={() => current.openAttachment(attachment)}
                    title="Click to see what's inside"
                  >
                    {current.fileIcon(attachment.kind)} {attachment.name}
                  </button>
                )
          ))}
        </div>
      )}
      <div className="prompt-actions">
        <VersionSwitch m={message} disabled={sending} onSwitch={current.switchVersion} />
        <button
          type="button"
          title="Copy prompt"
          aria-label="Copy prompt"
          className={copied ? "copied-pop" : ""}
          onClick={(event) => current.copy(promptText || "", copyKey, event)}
        >
          {copied ? <Check /> : <Copy />}
        </button>
        <button title="Edit prompt" aria-label="Edit prompt" onClick={() => current.editPrompt(promptText)}>
          <Pencil />
        </button>
        <button
          title="Resubmit prompt"
          aria-label="Resubmit prompt"
          disabled={sending}
          onClick={() => current.resubmitPrompt(message)}
        >
          <Repeat2 />
        </button>
        <button
          title="Rewrite prompt"
          aria-label="Rewrite prompt"
          disabled={sending || !message.content?.trim()}
          onClick={() => current.rewritePrompt(message.content)}
        >
          <WandSparkles />
        </button>
      </div>
    </div>
  );
}


function AssistantMessageRow({
  message,
  index,
  isLast,
  sending,
  copied,
  activeId,
  activeTitle,
  precedingPrompt,
  lastPrompt,
  actions,
}) {
  const current = actions.current;
  const { thinking: inlineThinking, body, svgs, cleaned } = deriveAiView(message);
  const rawThinking = message.thinking || inlineThinking;
  const copyKey = `r${index}`;
  const fileArtifacts = (message.artifacts || []).filter((artifact) => artifact.kind === "file");

  return (
    <div className={`msg ai${message.error ? " err" : ""}`}>
      <div className="who">
        Orrery
        {tokenLabel(message) && (
          <span className="token-chip" title="Exact for API models; estimated otherwise">
            {tokenLabel(message)}
          </span>
        )}
      </div>
      {message.streaming && !body && <ThinkingPulse />}
      {(message.trace?.length || message.summary || message.outer || message.sources?.length || rawThinking) && (
        <ReasoningPanel
          outer={message.outer}
          trace={message.trace}
          thinking={rawThinking}
          summary={message.summary}
          sources={message.sources}
          streaming={message.streaming}
        />
      )}
      <div className="ai-text">
        {message.streaming
          ? (body ? <div className="stream-live">{body}</div> : null)
          : (cleaned ? <Markdown>{cleaned}</Markdown> : null)}
        {message.streaming && body && <span className="caret" />}
      </div>
      {svgs.map((svg, svgIndex) => (
        <InlineSvg
          key={svgIndex}
          svg={svg}
          onPreview={() => current.openSvgPreview(svg, activeTitle)}
          onError={(error) => current.setBanner(String(error.message || error))}
        />
      ))}
      {message.artifacts?.map((artifact, artifactIndex) => (
        artifact.kind === "file" ? (
          <GeneratedFileCard
            key={`${artifact.id}-${artifactIndex}`}
            file={artifact}
            onPreview={() => current.openGeneratedPreview(artifact)}
            onOpenApp={() => current.openApp(artifact)}
            onDownload={() => downloadGeneratedFile(artifact.id, artifact.name)
              .catch((error) => current.setBanner(String(error.message || error)))}
          />
        ) : (
          <CodeImageArtifact
            key={`${artifact.name}-${artifactIndex}`}
            artifact={artifact}
            onPreview={(svg) => current.openSvgPreview(svg, activeTitle)}
            onError={(error) => current.setBanner(String(error.message || error))}
          />
        )
      ))}
      {fileArtifacts.length > 1 && (
        <button
          className="file-downloadall"
          onClick={() => fileArtifacts.forEach((artifact) => (
            downloadGeneratedFile(artifact.id, artifact.name)
              .catch((error) => current.setBanner(String(error.message || error)))
          ))}
        >
          <Download /> Download all
        </button>
      )}
      {!message.streaming && !message.error && (
        <div className="msg-actions">
          <VersionSwitch m={message} disabled={sending} onSwitch={current.switchVersion} />
          <button
            type="button"
            title="Copy reply"
            aria-label="Copy reply"
            className={copied ? "copied-pop" : ""}
            onClick={(event) => current.copy(message.content, copyKey, event)}
          >
            {copied ? <Check /> : <Copy />}
          </button>
          {extractHtml(message.content) && (
            <button
              title="Open the HTML in a live preview"
              aria-label="Preview HTML"
              onClick={() => current.openHtmlPreview(extractHtml(message.content), activeTitle)}
            >
              <Eye />
            </button>
          )}
          {isLast && !sending && (
            <button title="Regenerate reply" aria-label="Regenerate reply" onClick={current.regen}>
              <RefreshCw />
            </button>
          )}
          {isLast && !sending && (
            <button
              title="Resubmit last prompt"
              aria-label="Resubmit last prompt"
              onClick={() => { if (lastPrompt) current.resubmitPrompt(lastPrompt); }}
            >
              <Repeat2 />
            </button>
          )}
          {message.id && !sending && (
            <button
              title="Evaluate answers — compare candidates from other models and pick the best"
              aria-label="Evaluate answers"
              onClick={() => current.setEvalFor({ messageId: message.id, content: message.content })}
            >
              <Scale />
            </button>
          )}
        </div>
      )}
      {message.id && !message.streaming && !message.error && (() => {
        if (fileArtifacts.length) return null;
        if (isFileFailureNote(message.content)) return null;
        const formats = requestedFileFormats(precedingPrompt);
        const shown = formats.length ? formats : specFormats(message.content);
        if (!shown.length) return null;
        return (
          <ReplyFiles
            formats={shown}
            onPreview={(format) => current.openFilePreview(message.id, format, activeTitle)}
            onDownload={(format) => downloadMessageExport(activeId, message.id, format)
              .catch((error) => current.setBanner(String(error.message || error)))}
          />
        );
      })()}
    </div>
  );
}

// Token count for an assistant message: exact when the provider reported usage (API/custom),
// otherwise a live ~estimate from the streamed text (~4 chars/token) so every model shows one.
function tokenLabel(m) {
  if (m.tokens) {
    const ti = m.tokens.in || 0;
    const to = m.tokens.out || 0;
    return `${ti + to} tokens · ${ti} in / ${to} out`;
  }
  const chars = (m.content || "").length;
  if (!chars) return null;
  return `≈${Math.max(1, Math.round(chars / 4))} tokens`;
}

// Per-message view derivation (strip docspec, split think, extract SVGs). Completed messages
// keep stable object identity across renders, so their result is cached — a streaming token no
// longer re-runs these regexes over every message in the thread. While streaming, markdown
// parsing is skipped entirely (plain text + caret); the finished message renders Markdown once.
const _derivedCache = new WeakMap();
function deriveAiView(m) {
  if (!m.streaming && _derivedCache.has(m)) return _derivedCache.get(m);
  const { thinking, body } = splitInlineThinking(stripDocSpec(m.content));
  const { svgs, cleaned } = m.streaming ? { svgs: [], cleaned: body } : extractSvgs(body);
  const out = { thinking, body, svgs, cleaned };
  if (!m.streaming) _derivedCache.set(m, out);
  return out;
}

// Append a streamed delta to the active assistant message.
function appendDelta(setMessages, delta) {
  setMessages((messages) => appendDeltaToThread(messages, delta));
}

// Accumulate a progress step into the last assistant message's activity timeline.
function appendStep(setMessages, step) {
  setMessages((p) => {
    const a = ensureStreamingAssistant(p);
    const last = a[a.length - 1];
    const steps = last.steps ? [...last.steps] : [];
    if (step && steps[steps.length - 1] !== step) steps.push(step);
    a[a.length - 1] = { ...last, steps, status: step };
    return a;
  });
}

// ‹ n/m › switcher shown on any message that has sibling versions (regenerated or resubmitted).
function VersionSwitch({ m, disabled, onSwitch }) {
  if (!m?.id || !(m.versions > 1)) return null;
  const at = (m.version || 1) - 1;
  const go = (delta) => {
    const target = (m.siblings || [])[at + delta];
    if (target && target !== m.id) onSwitch(target);
  };
  return (
    <span className="version-switch">
      <button type="button" title="Previous version" aria-label="Previous version" disabled={disabled || at <= 0} onClick={() => go(-1)}>
        <ChevronLeft />
      </button>
      <span className="version-count">{at + 1}/{m.versions}</span>
      <button type="button" title="Next version" aria-label="Next version" disabled={disabled || at + 1 >= m.versions} onClick={() => go(1)}>
        <ChevronRight />
      </button>
    </span>
  );
}

// Rebuild a loaded message's reasoning panel fields from its persisted reasoning snapshot.
function hydrateReasoning(m) {
  const r = m?.reasoning;
  if (!r) return m;
  return {
    ...m,
    thinking: r.thinking || "",
    trace: r.trace || [],
    outer: r.outer || null,
    summary: r.summary || null,
    sources: r.sources || null,
  };
}

// Append streamed raw model reasoning to the last assistant message (shown in the reasoning panel).
function appendThinking(setMessages, text) {
  setMessages((p) => {
    const a = ensureStreamingAssistant(p);
    const last = a[a.length - 1];
    // Keep one provider-authored stream separate from Orrery's backend-authored trace steps.
    // This is the same shape that is persisted, so completion cannot move or rewrite the text.
    a[a.length - 1] = appendRawThinking(last, text);
    return a;
  });
}

// Append a safe work-trace step (reasoning_event) to the last assistant message.
function appendTrace(setMessages, event) {
  setMessages((p) => {
    const a = ensureStreamingAssistant(p);
    const last = a[a.length - 1];
    const trace = last.trace ? [...last.trace] : [];
    trace.push(event);
    a[a.length - 1] = { ...last, trace };
    return a;
  });
}
