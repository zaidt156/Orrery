import { useEffect, useRef, useState } from "react";
import {
  Copy,
  Download,
  Eye,
  FileDown,
  FileSpreadsheet,
  FileText,
  Pencil,
  RefreshCw,
  Repeat2,
  WandSparkles,
  X,
} from "lucide-react";
import { AttachIcon, SendIcon } from "../components/icons.jsx";
import Markdown from "../components/Markdown.jsx";
import { isCodeImagePrompt } from "../lib/chatCommands.js";
import {
  getModels, listCollections, listConversations, getConversation, createConversation,
  updateConversation, deleteConversation, streamMessage, regenerateMessage,
  downloadMessageExport, streamCodeImage, createArtifact, previewExport, saveClientFile,
  downloadGeneratedFile, previewGeneratedFile, stopGeneration, resumeGeneration, listProjects,
} from "../lib/api.js";
import {
  EXPORT_FORMATS, requestedFileFormats, precedingUserText,
  extractHtml, stripDocSpec, specFormats, extractSvgs, splitThink,
} from "./chatHelpers.jsx";
import {
  ReplyFiles, InlineSvg, CodeImageArtifact, GeneratedFileCard, ThinkingPulse, ReasoningPanel, TaskBrainPanel,
} from "./chatWidgets.jsx";

const EFFORTS = ["", "low", "medium", "high", "xhigh"];
const CONTEXT_WINDOWS = [
  ["131072", "context: 128K"],
  ["262144", "context: 256K"],
  ["1000000", "context: 1M"],
];

const CMDS = [
  ["/image", true], ["/video", true], ["/run automation", false],
  ["/agent", false], ["/dashboard", false], ["/search docs", false],
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

export default function Chat() {
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
  const [attachments, setAttachments] = useState([]);
  const [useData, setUseData] = useState(false);
  const [collections, setCollections] = useState([]);
  const [dataColl, setDataColl] = useState("");
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [effort, setEffort] = useState("");
  const [artifact, setArtifact] = useState(null); // { url, title, sandbox } for the preview sidebar

  async function openHtmlPreview(html, title) {
    try {
      const url = await createArtifact(html);
      setArtifact({ url, title: title || "Preview", sandbox: true });
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
        sandbox: preview.kind !== "pdf",
      });
    } catch (e) {
      setBanner(String(e.message || e));
    }
  }

  function openSvgPreview(svg, title) {
    setArtifact({ image: `data:image/svg+xml,${encodeURIComponent(svg)}`, title: title || "SVG preview" });
  }

  async function openGeneratedPreview(file) {
    setBanner(null);
    try {
      const { url, mime } = await previewGeneratedFile(file.id);
      if ((mime || "").startsWith("image/")) setArtifact({ image: url, title: file.name });
      else setArtifact({ url, title: file.name, sandbox: (mime || "").startsWith("text/html") });
    } catch (e) {
      setBanner(String(e.message || e));
    }
  }
  const [contextWindow, setContextWindow] = useState("1000000");

  useEffect(() => {
    let alive = true;
    (async () => {
      const modelsReq = getModels();
      const collectionsReq = listCollections();
      const projectsReq = listProjects();
      let hasConversations = false;

      try {
        const c = await listConversations();
        if (!alive) return;
        setConvos(c.conversations);
        hasConversations = c.conversations.length > 0;
        const pending = sessionStorage.getItem("orrery_open_conversation");
        const target = pending && c.conversations.find((item) => item.id === pending);
        if (target) {
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
          setContextWindow("1000000");
          sessionStorage.removeItem("orrery_preferred_model");
        } else if (!hasConversations) {
          setModel(m.value.models[0] ? m.value.models[0].id : "");
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
    setMessages(full.messages);
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
    if (activeId) {
      await updateConversation(activeId, { model: id });
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
    setMessages((p) => [...p, { role: "assistant", content: "", streaming: true }]);
    const setLast = (patch) =>
      setMessages((p) => {
        const a = [...p];
        a[a.length - 1] = { ...a[a.length - 1], ...patch };
        return a;
      });
    try {
      await start((ev) => {
        if (ev.delta) appendDelta(setMessages, ev.delta);
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
      }, ctrl.signal);
    } catch (e) {
      if (e.name === "AbortError") setLast({ streaming: false }); // keep the partial reply
      else setLast({ content: String(e.message || e), error: true, streaming: false });
    } finally {
      setSending(false);
      abortRef.current = null;
    }
  }

  // Re-attach to a generation that kept running in the background while we were away, then
  // reload the saved reply (the resume stream only carries the tail it didn't already emit).
  async function resumeRun(cid) {
    await runStream(cid, (onEvent, signal) => resumeGeneration(cid, onEvent, signal));
    try {
      const full = await getConversation(cid);
      if (cid === activeIdRef.current) setMessages(full.messages);
    } catch { /* keep what streamed */ }
  }

  async function submitPrompt(rawContent, rawAttachments = [], { clearComposer = false } = {}) {
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
      setActiveId(cid);
      setConvos((p) => [{ id: conv.id, title: conv.title, model: conv.model, project_id: conv.project_id || null }, ...p]);
    }
    const atts = rawAttachments;
    const collectionId = useData && dataColl ? dataColl : null;
    if (clearComposer) {
      setInput("");
      setAttachments([]);
    }
    setMessages((p) => [...p, { role: "user", content, attachments: atts }]);
    const codeImage = atts.length === 0 && isCodeImagePrompt(content);
    await runStream(cid, (onEvent, signal) =>
      codeImage
        ? streamCodeImage(cid, content, onEvent, signal)
        : streamMessage(cid, content, atts, collectionId, onEvent, signal)
    );
  }

  async function send() {
    await submitPrompt(input, attachments, { clearComposer: true });
  }

  async function resubmitPrompt(message) {
    await submitPrompt(message.content || "", message.attachments || []);
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
  }

  function stop() {
    if (activeId) stopGeneration(activeId); // cancel on the backend too (it now runs detached)
    abortRef.current?.abort();
  }

  function copy(text) {
    navigator.clipboard?.writeText(String(text || ""));
  }

  function readFile(file, kind) {
    return new Promise((resolve) => {
      const r = new FileReader();
      r.onload = () => resolve({ name: file.name, mime: file.type, kind, content: r.result });
      if (kind === "image" || kind === "pdf") r.readAsDataURL(file);
      else r.readAsText(file);
    });
  }

  async function handleFiles(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    const ok = [];
    for (const f of files) {
      const isImage = f.type.startsWith("image/");
      const isPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name);
      const isText = f.type.startsWith("text/") || /\.(md|csv|json|txt|py|js|ts|jsx|tsx|html|css|ya?ml|log|sql)$/i.test(f.name);
      const kind = isImage ? "image" : isPdf ? "pdf" : isText ? "text" : null;
      if (!kind) { setBanner(`Unsupported file type (skipped ${f.name}).`); continue; }
      if (f.size > 12 * 1024 * 1024) { setBanner(`${f.name} is too large (max 12 MB).`); continue; }
      ok.push(await readFile(f, kind));
    }
    if (ok.length) setAttachments((p) => [...p, ...ok]);
  }

  const fileIcon = (kind) => (kind === "image" ? "🖼" : kind === "pdf" ? "📕" : "📄");

  const title = convos.find((c) => c.id === activeId)?.title || "New chat";
  const projectName = (id) => projects.find((p) => p.id === id)?.name || "";
  const current = models.find((m) => m.id === model);
  const modelLabel = current?.label || model || "pick a model";
  const noKey = !!model && !current;
  const prefix = model.includes("/") ? model.split("/")[0] : "";
  const provider = PROVIDER_NAME[prefix] || "this provider";

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
        </div>
        <TaskBrainPanel onOpenConversation={open} />
      </aside>

      <div className="chat-main">
        <div className="chat-header">
          <span className="view-title">{title}</span>
          <div className="pickwrap">
            <span className={`pill model-pill${noKey ? " no-key" : ""}`} title="Switch model" onClick={toggleModelMenu}>
              <b>{modelLabel}</b>{noKey ? " · no key" : ""} ⌄
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
            title="Approximate per-chat token window. Orrery reserves 25% for the reply; the selected model may support less."
          >
            {CONTEXT_WINDOWS.map(([value, label]) => (
              <option key={value || "auto"} value={value}>{label}</option>
            ))}
          </select>
          <select className="effort-pick" value={effort} onChange={(e) => chooseEffort(e.target.value)} title="Reasoning effort (where the model supports it)">
            {EFFORTS.map((v) => <option key={v || "auto"} value={v}>{v ? `effort: ${v}` : "effort: auto"}</option>)}
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

        <div className="thread" ref={threadRef}>
          {messages.length === 0 && (
            <div className="thread-empty">
              <div className="constellation">✦ &nbsp; · &nbsp; ✦ &nbsp;· &nbsp;✦</div>
            </div>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div className="msg user" key={i}>
                {m.attachments?.length > 0 && (
                  <div className="msg-attach">
                    {m.attachments.map((a, k) =>
                      a.kind === "image"
                        ? <img key={k} src={a.content} alt={a.name} className="msg-thumb" />
                        : <span key={k} className="attach-chip">{fileIcon(a.kind)} {a.name}</span>
                    )}
                  </div>
                )}
                {m.content && <div className="prompt-text"><Markdown plain>{m.content}</Markdown></div>}
                <div className="prompt-actions">
                  <button title="Copy prompt" aria-label="Copy prompt" onClick={() => copy(m.content || "")}>
                    <Copy />
                  </button>
                  <button title="Edit prompt" aria-label="Edit prompt" onClick={() => editPrompt(m.content)}>
                    <Pencil />
                  </button>
                  <button
                    title="Resubmit prompt"
                    aria-label="Resubmit prompt"
                    disabled={sending}
                    onClick={() => resubmitPrompt(m)}
                  >
                    <Repeat2 />
                  </button>
                  <button
                    title="Rewrite prompt"
                    aria-label="Rewrite prompt"
                    disabled={sending || !m.content?.trim()}
                    onClick={() => rewritePrompt(m.content)}
                  >
                    <WandSparkles />
                  </button>
                </div>
              </div>
            ) : (
              <div className={`msg ai${m.error ? " err" : ""}`} key={i}>
                <div className="who">
                  Orrery
                  {m.sources?.length > 0 && <span className="rag-chip">searched: {m.sources.join(", ")}</span>}
                  {tokenLabel(m) && <span className="token-chip" title="Exact for API models; estimated otherwise">{tokenLabel(m)}</span>}
                </div>
                {(() => {
                  const { body } = splitThink(stripDocSpec(m.content)); // strip raw <think>, never shown
                  const { svgs, cleaned } = m.streaming ? { svgs: [], cleaned: body } : extractSvgs(body);
                  const svgTitle = convos.find((c) => c.id === activeId)?.title;
                  return (
                    <>
                      {m.streaming && !body && <ThinkingPulse />}
                      {(m.trace?.length || m.summary) && (
                        <ReasoningPanel trace={m.trace} summary={m.summary} streaming={m.streaming} />
                      )}
                      <div className="ai-text">
                        {cleaned ? <Markdown>{cleaned}</Markdown> : null}
                        {m.streaming && body && <span className="caret" />}
                      </div>
                      {svgs.map((svg, si) => (
                        <InlineSvg
                          key={si}
                          svg={svg}
                          onPreview={() => openSvgPreview(svg, svgTitle)}
                          onError={(e) => setBanner(String(e.message || e))}
                        />
                      ))}
                    </>
                  );
                })()}
                {m.artifacts?.map((artifact, artifactIndex) => (
                  artifact.kind === "file" ? (
                    <GeneratedFileCard
                      key={`${artifact.id}-${artifactIndex}`}
                      file={artifact}
                      onPreview={() => openGeneratedPreview(artifact)}
                      onDownload={() => downloadGeneratedFile(artifact.id, artifact.name).catch((e) => setBanner(String(e.message || e)))}
                    />
                  ) : (
                    <CodeImageArtifact
                      key={`${artifact.name}-${artifactIndex}`}
                      artifact={artifact}
                      onPreview={(svg) => openSvgPreview(svg, convos.find((c) => c.id === activeId)?.title)}
                      onError={(e) => setBanner(String(e.message || e))}
                    />
                  )
                ))}
                {!m.streaming && !m.error && (
                  <div className="msg-actions">
                    <button title="Copy reply" aria-label="Copy reply" onClick={() => copy(m.content)}>
                      <Copy />
                    </button>
                    {extractHtml(m.content) && (
                      <button
                        title="Open the HTML in a live preview"
                        aria-label="Preview HTML"
                        onClick={() => openHtmlPreview(extractHtml(m.content), convos.find((c) => c.id === activeId)?.title)}
                      >
                        <Eye />
                      </button>
                    )}
                    {i === messages.length - 1 && !sending && (
                      <button title="Regenerate reply" aria-label="Regenerate reply" onClick={regen}>
                        <RefreshCw />
                      </button>
                    )}
                    {i === messages.length - 1 && !sending && (
                      <button
                        title="Resubmit last prompt"
                        aria-label="Resubmit last prompt"
                        onClick={() => {
                          const lastPrompt = [...messages].slice(0, i).reverse().find((x) => x.role === "user");
                          if (lastPrompt) resubmitPrompt(lastPrompt);
                        }}
                      >
                        <Repeat2 />
                      </button>
                    )}
                  </div>
                )}
                {m.id && !m.streaming && !m.error && (() => {
                  const formats = requestedFileFormats(precedingUserText(messages, i));
                  const shown = formats.length ? formats : specFormats(m.content);
                  if (!shown.length) return null;
                  const previewTitle = convos.find((c) => c.id === activeId)?.title;
                  return (
                    <ReplyFiles
                      formats={shown}
                      onPreview={(format) => openFilePreview(m.id, format, previewTitle)}
                      onDownload={(format) => downloadMessageExport(activeId, m.id, format).catch((e) => setBanner(String(e.message || e)))}
                    />
                  );
                })()}
              </div>
            )
          )}
        </div>

        <div className="composer">
          <div className="cmd-row">
            <span className="cmd-lead">type / to run anything:</span>
            {CMDS.map(([c, warm]) => (
              <span key={c} className={`cmd-chip${warm ? " warm" : ""}`} onClick={() => setInput(c + " ")}>{c}</span>
            ))}
          </div>
          {attachments.length > 0 && (
            <div className="attach-row">
              {attachments.map((a, i) => (
                <span className="attach-chip" key={i}>
                  {fileIcon(a.kind)} {a.name}
                  <button onClick={() => setAttachments((p) => p.filter((_, j) => j !== i))}>×</button>
                </span>
              ))}
            </div>
          )}
          <div className="composer-box">
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              accept="image/*,application/pdf,.pdf,text/*,.md,.csv,.json,.txt,.py,.js,.ts,.jsx,.tsx,.html,.css,.yml,.yaml,.log,.sql"
              onChange={handleFiles}
            />
            <button className="icon-btn" aria-label="Attach file" title="Attach images or text files" onClick={() => fileRef.current?.click()}><AttachIcon /></button>
            <textarea
              ref={composerRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask, or type / to generate media, run automations, start agents, build dashboards…"
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
          {artifact.image ? (
            <div className="artifact-frame artifact-image"><img src={artifact.image} alt="SVG preview" /></div>
          ) : artifact.sandbox ? (
            <iframe
              className="artifact-frame"
              src={artifact.url}
              title="HTML preview"
              sandbox="allow-scripts allow-popups allow-forms allow-modals"
            />
          ) : (
            <iframe className="artifact-frame" src={artifact.url} title="File preview" />
          )}
        </aside>
      )}
    </section>
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

// Append a streamed delta to the last (assistant) message.
function appendDelta(setMessages, delta) {
  setMessages((p) => {
    const a = [...p];
    const last = a[a.length - 1];
    a[a.length - 1] = { ...last, content: last.content + delta };
    return a;
  });
}

// Accumulate a progress step into the last assistant message's activity timeline.
function appendStep(setMessages, step) {
  setMessages((p) => {
    const a = [...p];
    const last = a[a.length - 1];
    const steps = last.steps ? [...last.steps] : [];
    if (step && steps[steps.length - 1] !== step) steps.push(step);
    a[a.length - 1] = { ...last, steps, status: step };
    return a;
  });
}

// Append a safe work-trace step (reasoning_event) to the last assistant message.
function appendTrace(setMessages, event) {
  setMessages((p) => {
    const a = [...p];
    const last = a[a.length - 1];
    const trace = last.trace ? [...last.trace] : [];
    trace.push(event);
    a[a.length - 1] = { ...last, trace };
    return a;
  });
}
