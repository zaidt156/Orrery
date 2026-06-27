// the one place the UI talks to the backend; attaches the session token to every call
const params = new URLSearchParams(window.location.search);
const token = params.get("token") || sessionStorage.getItem("orrery_token") || "";
if (token) sessionStorage.setItem("orrery_token", token);

// dev: UI on Vite (:5173), API on :8765; built app: same origin
const API_BASE = import.meta.env.DEV ? "http://127.0.0.1:8765" : "";

function authHeaders(extra) {
  return { "X-Orrery-Token": token, ...extra };
}

async function errorText(res) {
  try {
    const j = await res.json();
    return j.detail || `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
}

export async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

export async function apiSend(path, method, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: authHeaders(body ? { "Content-Type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(await errorText(res));
  return res.status === 204 ? null : res.json();
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

export async function apiDownload(path, fallbackName) {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await errorText(res));
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match?.[1] || fallbackName;
  const blob = await res.blob();

  // Desktop: browser blob downloads are unreliable inside the webview — use pywebview's
  // native Save dialog (Python writes the bytes to the path the user picks).
  if (window.pywebview?.api?.save_file) {
    const b64 = await blobToBase64(blob);
    const result = await window.pywebview.api.save_file(filename, b64);
    if (result && result.ok === false && !result.cancelled) {
      throw new Error(result.error || "Could not save the file.");
    }
    return filename;
  }

  // Browser / dev fallback: anchor download
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}

// --- Endpoints ---
export const getHealth = () => apiGet("/api/health");
export const getModels = () => apiGet("/api/models");
export const getModelCatalog = () => apiGet("/api/models/catalog");
export const setModelActive = (id, label, provider, active) =>
  apiSend("/api/models/active", "POST", { id, label, provider, active });
export const addCustomModel = (label, base_url, model, key) =>
  apiSend("/api/custom-models", "POST", { label, base_url, model, key });
export const deleteCustomModel = (cid) => apiSend(`/api/custom-models/${cid}`, "DELETE");
export const getDatabase = () => apiGet("/api/database");
export const testDatabase = (url) => apiSend("/api/database/test", "POST", { url });
export const saveDatabase = (url) => apiSend("/api/database", "PUT", { url });
export const clearDatabase = () => apiSend("/api/database", "DELETE");
export const getBranding = () => apiGet("/api/branding");
export const setBranding = (branding) => apiSend("/api/branding", "PUT", branding);
export const getPrivacy = () => apiGet("/api/privacy");
export const setPrivacy = (mode) => apiSend("/api/privacy", "PUT", { mode });
export const getTasks = () => apiGet("/api/tasks");
export const cancelTask = (id) => apiSend(`/api/tasks/${id}/cancel`, "POST");
export const getUsage = () => apiGet("/api/usage");
export const setSpendCap = (cap) => apiSend("/api/usage/cap", "PUT", cap);
export const submitFeedback = (payload) => apiSend("/api/feedback", "POST", payload);
export const getProviders = () => apiGet("/api/providers");
export const setProviderKey = (provider, key) => apiSend(`/api/providers/${provider}/key`, "PUT", { key });
export const clearProviderKey = (provider) => apiSend(`/api/providers/${provider}/key`, "DELETE");
export const connectClaudePlan = () => apiSend("/api/providers/anthropic/claude-plan/connect", "POST");
export const disconnectClaudePlan = () => apiSend("/api/providers/anthropic/claude-plan", "DELETE");
export const connectChatgptPlan = (acknowledged) =>
  apiSend("/api/providers/openai/chatgpt-plan/connect", "POST", { acknowledged });
export const disconnectChatgptPlan = () => apiSend("/api/providers/openai/chatgpt-plan", "DELETE");
export const connectGeminiPlan = (acknowledged) =>
  apiSend("/api/providers/google/gemini-plan/connect", "POST", { acknowledged });
export const disconnectGeminiPlan = () => apiSend("/api/providers/google/gemini-plan", "DELETE");

const PLAN_PATH = {
  claude_plan: "/api/providers/anthropic/claude-plan",
  chatgpt_plan: "/api/providers/openai/chatgpt-plan",
  gemini_plan: "/api/providers/google/gemini-plan",
};

// connect/disconnect dispatch by subscription mode id (claude_plan | chatgpt_plan | gemini_plan)
export const connectPlan = (id, acknowledged = false) =>
  id === "chatgpt_plan"
    ? connectChatgptPlan(acknowledged)
    : id === "gemini_plan"
      ? connectGeminiPlan(acknowledged)
      : connectClaudePlan();
export const disconnectPlan = (id) =>
  id === "chatgpt_plan" ? disconnectChatgptPlan() : id === "gemini_plan" ? disconnectGeminiPlan() : disconnectClaudePlan();
export const installPlanCli = (id, acknowledged) =>
  apiSend(`${PLAN_PATH[id]}/install`, "POST", { acknowledged });
export const loginPlanCli = (id) => apiSend(`${PLAN_PATH[id]}/login`, "POST");
export const refreshPlan = (id) => apiSend(`${PLAN_PATH[id]}/refresh`, "POST");

export const getLocalModels = () => apiGet("/api/local-models");
export const installLocalRuntime = (acknowledged) =>
  apiSend("/api/local-models/install", "POST", { acknowledged });
export const startLocalRuntime = () => apiSend("/api/local-models/start", "POST");
export const setLocalModelActive = (model, active) =>
  apiSend("/api/local-models/active", "POST", { model, active });
export const removeLocalModel = (model) =>
  apiSend("/api/local-models/remove", "POST", { model });

export const listDataConnections = () => apiGet("/api/connections");
export const addDataConnection = (name, url) => apiSend("/api/connections", "POST", { name, url });
export const deleteDataConnection = (id) => apiSend(`/api/connections/${id}`, "DELETE");
export const listTables = (id) => apiGet(`/api/connections/${id}/tables`);
export const browseTable = (id, schema, table, limit = 100) =>
  apiGet(`/api/connections/${id}/browse?schema=${encodeURIComponent(schema)}&table=${encodeURIComponent(table)}&limit=${limit}`);

export const listCollections = () => apiGet("/api/collections");
export const createCollection = (name) => apiSend("/api/collections", "POST", { name });
export const deleteCollection = (id) => apiSend(`/api/collections/${id}`, "DELETE");
export const uploadDocuments = (id, files) => apiSend(`/api/collections/${id}/documents`, "POST", { files });

export const listProjects = () => apiGet("/api/projects");
export const createProject = (project) => apiSend("/api/projects", "POST", project);
export const getProject = (id) => apiGet(`/api/projects/${id}`);
export const updateProject = (id, project) => apiSend(`/api/projects/${id}`, "PATCH", project);
export const deleteProject = (id) => apiSend(`/api/projects/${id}`, "DELETE");
export const attachConversationToProject = (projectId, conversationId) =>
  apiSend(`/api/projects/${projectId}/conversations/${conversationId}`, "POST");
export const removeConversationFromProject = (conversationId) =>
  apiSend(`/api/conversations/${conversationId}/project`, "DELETE");

export const listConversations = () => apiGet("/api/conversations");
export const createConversation = (model, system_prompt, effort, context_window, project_id = null) =>
  apiSend("/api/conversations", "POST", { model, system_prompt, effort, context_window, project_id });
export const getConversation = (id) => apiGet(`/api/conversations/${id}`);
export const updateConversation = (id, patch) => apiSend(`/api/conversations/${id}`, "PATCH", patch);
export const deleteConversation = (id) => apiSend(`/api/conversations/${id}`, "DELETE");
export const downloadMessageExport = (conversationId, messageId, format) =>
  apiDownload(
    `/api/conversations/${conversationId}/messages/${messageId}/export/${format}`,
    `orrery-reply.${format}`
  );

// save content the UI already has (e.g. an SVG image) via the native dialog, blob fallback in a browser
export async function saveClientFile(filename, content, mime = "application/octet-stream") {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mime });
  if (window.pywebview?.api?.save_file) {
    const b64 = await blobToBase64(blob);
    const result = await window.pywebview.api.save_file(filename, b64);
    if (result && result.ok === false && !result.cancelled) {
      throw new Error(result.error || "Could not save the file.");
    }
    return;
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// register HTML for a sandboxed preview; returns an absolute URL for an <iframe src>
export async function createArtifact(html) {
  const data = await apiSend("/api/artifacts", "POST", { html });
  return `${API_BASE}${data.url}`;
}

// generated files (from the code-execution pipeline): download by id, preview by id
export const downloadGeneratedFile = (fileId, name) => apiDownload(`/api/files/${fileId}`, name || "file");
export async function previewGeneratedFile(fileId) {
  const data = await apiGet(`/api/files/${fileId}/preview`);
  return { ...data, url: `${API_BASE}${data.url}` };
}

// render a reply as a temporary preview artifact for the requested export format
export async function previewExport(conversationId, messageId, format) {
  const data = await apiGet(`/api/conversations/${conversationId}/messages/${messageId}/preview/${format}`);
  return { ...data, url: `${API_BASE}${data.url}` };
}

// read an SSE stream, calling onEvent per frame; signal aborts (Stop button)
async function streamSSE(path, { body, signal, method = "POST" } = {}, onEvent) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: authHeaders(body ? { "Content-Type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  if (!res.ok) throw new Error(await errorText(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 2);
      if (chunk.startsWith("data:")) {
        try {
          onEvent(JSON.parse(chunk.slice(5).trim()));
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  }
}

export const streamMessage = (cid, content, attachments, collectionId, onEvent, signal) =>
  streamSSE(`/api/conversations/${cid}/messages`, { body: { content, attachments, collection_id: collectionId }, signal }, onEvent);

export const streamCodeImage = (cid, content, onEvent, signal) =>
  streamSSE(`/api/conversations/${cid}/code-image`, { body: { content, attachments: [] }, signal }, onEvent);

export const pullLocalModel = (model, onEvent, signal) =>
  streamSSE("/api/local-models/pull", { body: { model }, signal }, onEvent);

export const regenerateMessage = (cid, onEvent, signal) =>
  streamSSE(`/api/conversations/${cid}/regenerate`, { signal }, onEvent);

// re-attach to a generation still running in the background after navigating away
export const resumeGeneration = (cid, onEvent, signal) =>
  streamSSE(`/api/conversations/${cid}/resume`, { method: "GET", signal }, onEvent);

// explicitly cancel backend generation (the Stop button — navigating away does NOT cancel)
export const stopGeneration = (cid) => apiSend(`/api/conversations/${cid}/stop`, "POST").catch(() => {});
