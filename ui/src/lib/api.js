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
export const getAppUpdate = () => apiGet("/api/app/update");
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

export const getAttachmentText = (cid, source) =>
  apiGet(`/api/conversations/${cid}/attachment-text?source=${encodeURIComponent(source)}`);

// Answer evaluation: candidates + anonymous AI judge; adopting replaces the message
export const evaluateMessage = (cid, mid, models, judge) =>
  apiSend(`/api/conversations/${cid}/messages/${mid}/evaluate`, "POST", { models, judge });
export const adoptAnswer = (cid, mid, text, model) =>
  apiSend(`/api/conversations/${cid}/messages/${mid}/adopt`, "POST", { text, model });

// Workspace defaults (Settings → General)
export const getDefaults = () => apiGet("/api/defaults");
export const setDefaults = (model, effort) => apiSend("/api/defaults", "PUT", { model, effort });

// Imported datasets (CSV/Excel uploads + REST APIs) — BI-style sources for dashboards
export const listDatasets = () => apiGet("/api/datasets");
export const createDatasetFromFile = (name, filename, content, workspace_id = "") =>
  apiSend("/api/datasets/file", "POST", { name, filename, content, workspace_id });
export const createDatasetFromApi = (name, url, headers, workspace_id = "") =>
  apiSend("/api/datasets/api", "POST", { name, url, headers, workspace_id });
export const refreshDataset = (id) => apiSend(`/api/datasets/${id}/refresh`, "POST");
export const deleteDataset = (id) => apiSend(`/api/datasets/${id}`, "DELETE");
export const listWorkspaces = () => apiGet("/api/workspaces");
export const createWorkspace = (name) => apiSend("/api/workspaces", "POST", { name });
export const getSchemaMap = (cid) => apiGet(`/api/connections/${cid}/schema-map`);
export const listDataModels = (cid) => apiGet(`/api/datamodels?connection_id=${encodeURIComponent(cid || "")}`);
export const createDataModel = (connection_id, name, spec) => apiSend("/api/datamodels", "POST", { connection_id, name, spec });
export const deleteDataModel = (id) => apiSend(`/api/datamodels/${id}`, "DELETE");
export const setDashboardTransforms = (id, transforms) => apiSend(`/api/dashboards/${id}/transforms`, "PUT", { transforms });
export const setDashboardLayout = (id, order) => apiSend(`/api/dashboards/${id}/layout`, "PUT", { order });

// Dashboards: the AI designs the spec; refresh re-runs saved read-only SQL (no model call)
export const listDashboards = () => apiGet("/api/dashboards");
export const createDashboard = (model, connection_ids, description) =>
  apiSend("/api/dashboards", "POST", { model, connection_ids, description });
export const runDashboard = (id) => apiSend(`/api/dashboards/${id}/run`, "POST");
export const reviseDashboard = (id, model, instruction) =>
  apiSend(`/api/dashboards/${id}/revise`, "POST", { model, instruction });
export const rollbackDashboard = (id) => apiSend(`/api/dashboards/${id}/rollback`, "POST");
export const deleteDashboard = (id) => apiSend(`/api/dashboards/${id}`, "DELETE");

export const listCollections = () => apiGet("/api/collections");
export const createCollection = (name) => apiSend("/api/collections", "POST", { name });
export const deleteCollection = (id) => apiSend(`/api/collections/${id}`, "DELETE");
export const uploadDocuments = (id, files) => apiSend(`/api/collections/${id}/documents`, "POST", { files });

// Ontologies — reusable knowledge bases the user builds from their own files; "connected" ones are
// automatically used as standing context in every chat.
export const listOntologies = () => apiGet("/api/ontologies");
export const createOntology = (name, description) => apiSend("/api/ontologies", "POST", { name, description });
export const updateOntology = (id, patch) => apiSend(`/api/ontologies/${id}`, "PATCH", patch);
export const deleteOntology = (id) => apiSend(`/api/ontologies/${id}`, "DELETE");
export const listOntologyFiles = (id) => apiGet(`/api/ontologies/${id}/files`);
export const addOntologyFiles = (id, files) => apiSend(`/api/ontologies/${id}/files`, "POST", { files });
export const deleteOntologyFile = (id, source) =>
  apiSend(`/api/ontologies/${id}/files?source=${encodeURIComponent(source)}`, "DELETE");

// User-authored skills — reusable instruction playbooks the user creates/uploads; enabled ones are
// matched against each message (by trigger phrases, or always) and injected into the model's prompt.
export const listSkills = () => apiGet("/api/skills");
export const createSkill = (skill) => apiSend("/api/skills", "POST", skill);
export const uploadSkill = (markdown, name) => apiSend("/api/skills/upload", "POST", { markdown, name });
export const generateSkill = (description, model) => apiSend("/api/skills/generate", "POST", { description, model });

// MCP servers (config + storage; tool execution wired later)
export const listMcp = () => apiGet("/api/mcp");
export const createMcp = (server) => apiSend("/api/mcp", "POST", server);
export const updateMcp = (id, patch) => apiSend(`/api/mcp/${id}`, "PATCH", patch);
export const deleteMcp = (id) => apiSend(`/api/mcp/${id}`, "DELETE");
export const testMcp = (id) => apiSend(`/api/mcp/${id}/test`, "POST");
export const approveSkill = (id) => apiSend(`/api/skills/${id}/approve`, "POST");
export const approveMcp = (id) => apiSend(`/api/mcp/${id}/approve`, "POST");
export const updateSkill = (id, patch) => apiSend(`/api/skills/${id}`, "PATCH", patch);
export const deleteSkill = (id) => apiSend(`/api/skills/${id}`, "DELETE");

// Admin feature flags
export const getAdmin = () => apiGet("/api/admin");
export const setAdminToken = (token, current) => apiSend("/api/admin/token", "POST", { token, current });
export const setAdminFeatures = (flags, token) => apiSend("/api/admin/features", "PUT", { flags, token });

// Team access: identity, keys, roles (shared-database multi-user)
export const getTeam = () => apiGet("/api/team");
export const setupTeam = (name) => apiSend("/api/team/setup", "POST", { name });
export const unlockTeam = (key) => apiSend("/api/team/unlock", "POST", { key });
export const signOutTeam = () => apiSend("/api/team/signout", "POST");
export const listTeamUsers = () => apiGet("/api/team/users");
export const createTeamUser = (name, role) => apiSend("/api/team/users", "POST", { name, role });
export const updateTeamUser = (id, patch) => apiSend(`/api/team/users/${id}`, "PATCH", patch);
export const deleteTeamUser = (id) => apiSend(`/api/team/users/${id}`, "DELETE");

export const listProjects = () => apiGet("/api/projects");
export const createProject = (project) => apiSend("/api/projects", "POST", project);
export const getProject = (id) => apiGet(`/api/projects/${id}`);
export const updateProject = (id, project) => apiSend(`/api/projects/${id}`, "PATCH", project);
export const deleteProject = (id) => apiSend(`/api/projects/${id}`, "DELETE");
export const attachConversationToProject = (projectId, conversationId) =>
  apiSend(`/api/projects/${projectId}/conversations/${conversationId}`, "POST");
export const removeConversationFromProject = (conversationId) =>
  apiSend(`/api/conversations/${conversationId}/project`, "DELETE");

export const listProjectFiles = (id) => apiGet(`/api/projects/${id}/files`);
export const addProjectFiles = (id, files) => apiSend(`/api/projects/${id}/files`, "POST", { files });
export const deleteProjectFile = (id, source) =>
  apiSend(`/api/projects/${id}/files?source=${encodeURIComponent(source)}`, "DELETE");

// Read a browser File into the {name, mime, kind, content} shape the backend expects.
// Text-like files are sent as raw text; everything else (pdf/office/…) as a base64 data URL.
const TEXT_EXT = /\.(txt|md|markdown|csv|tsv|json|ya?ml|xml|html?|css|js|jsx|ts|tsx|py|java|c|cpp|cs|go|rs|rb|php|sh|sql|ini|toml|log)$/i;
export function readFileAsAttachment(file) {
  const name = file.name || "file";
  const isText = TEXT_EXT.test(name) || (file.type || "").startsWith("text/");
  const isImage = (file.type || "").startsWith("image/");
  const isPdf = /\.pdf$/i.test(name) || file.type === "application/pdf";
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () =>
      resolve({
        name,
        mime: file.type || "",
        kind: isImage ? "image" : isPdf ? "pdf" : isText ? "text" : "file",
        content: String(reader.result || ""),
      });
    if (isText) reader.readAsText(file);
    else reader.readAsDataURL(file);
  });
}

export const listConversations = () => apiGet("/api/conversations");
export const createConversation = (model, system_prompt, effort, context_window, project_id = null) =>
  apiSend("/api/conversations", "POST", { model, system_prompt, effort, context_window, project_id });
export const getConversation = (id) => apiGet(`/api/conversations/${id}`);
export const updateConversation = (id, patch) => apiSend(`/api/conversations/${id}`, "PATCH", patch);
export const deleteConversation = (id) => apiSend(`/api/conversations/${id}`, "DELETE");
export const saveReasoning = (conversationId, messageId, reasoning) =>
  apiSend(`/api/conversations/${conversationId}/messages/${messageId}/reasoning`, "POST", { reasoning });
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
