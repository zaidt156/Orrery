# Orrery Roadmap

Read this when planning a phase or deciding whether something belongs now or later. It lists the phases with the reasoning behind the order and the decisions deliberately deferred. The rule that governs all of it: **build the phases in order, and keep each layer solid before the next leans on it.** Pulling a later phase's complexity into an earlier one is how the project gets tangled.

## Why this order

Each phase depends on the one before it. Chat needs the database and model layer to exist. Data/RAG needs Chat to consume it. Dashboards, Automations, and Agents all read and write through the same database and model layer, so those foundations must be trustworthy first. Agents are the most powerful and dangerous of the core feature tabs, so they are built on top of patterns (the tool registry, run history, scope, approval gates) already proven by Automations. The **Media Hub** then adds a creation surface that registers as just another tool. The **Chat command surface** comes last of the build-out because it is glue: it can only invoke features that already exist, and it leans on the scope/approval enforcement proven by Agents so that driving actions from Chat is safe rather than a back door.

## The phases

### Phase 0 — Skeleton (2–3 days)
`app.py` connects to Postgres, runs migrations, enables pgvector, generates the session auth token, starts FastAPI plus the Procrastinate worker, and opens the window showing the React shell. First run prompts for the connection string. **Done when:** running one command opens a window served by the local backend, talking to the database.
Deliberately tiny on purpose — it proves the whole spine (window ↔ backend ↔ database ↔ worker) end to end before any feature leans on it.

### Phase 1 — Chat (~1 week)
Model routing wired in; streaming chat over SSE; conversation history persisted to Postgres; model picker; editable system prompt; accounts/API keys stored in and read from the keychain. **Done when:** a user can connect an account or paste a key, pick a model, and hold a streaming conversation that persists.

### Phase 2 — Data / RAG (~1 week)
Connection manager (multiple databases, each isolated, with test-connection); document collections (chunk → embed → pgvector); **hybrid retrieval** combining vector similarity with Postgres full-text keyword search for accuracy; a **local-embeddings option** (sentence-transformers / BGE / nomic-embed) so RAG can run with no document text leaving the machine; **PII redaction** (`security.md` §10) applied before any content reaches a cloud model; the read-only table browser; the "use my data" path in Chat with visible sources. **Done when:** a user can connect a database, build a collection, and get chat answers grounded in it with citations.

### Phase 3 — Dashboards (~1 week)
The spec builder (chosen model inspects schema, writes SQL, picks charts) using **structured outputs** for a schema-checked spec and **SQL validation** — every generated query is parsed (sqlglot) and dry-run read-only before it is saved or shown, with self-correction on error; ECharts widgets, free read-only refresh, revise (possibly with a different model), and spec versioning with rollback. Pin-from-Chat. **Done when:** a user can describe a dashboard, watch a model build it, refresh it at zero token cost, and roll back a bad revision.

### Phase 4 — Automations (~2 weeks)
The DAG engine on Procrastinate; 8–10 core nodes across triggers/AI/data/logic/code; AI nodes use **structured outputs** so a node returns schema-valid data downstream nodes can rely on; the React Flow canvas with config panels and `{{node.output}}` templating; cron and manual triggers; the run-debug view showing per-node input/output and retries. The code node ships only with its subprocess sandbox (`security.md` §5). **Done when:** a user can build, run, schedule, and debug a multi-step workflow, and a failed node retries per policy.

### Phase 5 — Agents (~2 weeks)
The agent loop (plan → act → self-check → improve) running as Procrastinate jobs; scope enforcement at the tool layer; **structured outputs** for every tool call so arguments are schema-validated before the tool runs; learning notes; the run modes (continuous / until done / timer / trigger); the live activity feed; budget/loop/confidence limits with an always-working stop; approval gates; the shared handoff queue connecting agents to automations, to each other, and to the user. **Done when:** a scoped agent can pursue a goal across loops, improve from its notes, stay inside its limits, escalate low-confidence work, and be stopped instantly.

This is the phase to build last and most carefully. Reuse Phase 4's tool registry, run history, and approval-gate plumbing rather than inventing parallel versions.

### Phase 6 — Media Hub (~1.5 weeks)
Image and video generation on the user's own media-model keys via provider adapters, plus an **optional local backend** (Stable Diffusion / ComfyUI) for on-device generation; the create panel (prompt, model, parameters, image→image / image→video); the media library with **files on disk and metadata in Postgres**; pin-to-Chat. Generation is registered as a **tool** in the shared registry so Chat and Automations can use it. Content safety per `security.md` §11. **Done when:** a user can generate image/video on their own keys (or locally), keep a reusable library, and pin an asset into Chat.

### Phase 7 — Chat command surface (~1 week)
Expose the **shared tool registry to Chat** so the user can invoke any feature — generate media, run an automation, start or query an agent, build or refresh a dashboard, search data — by typing `/` or asking in natural language. Critically, every invoked action runs through the **same enforcement** as elsewhere: approval gates for sensitive/destructive actions, agent/tool scope, read-only defaults, and PII redaction (`security.md` §3, §4, §6, §10). This phase comes after the major invokable features exist (so there is something to invoke) and after Agents (so scope/approval plumbing is proven). **Done when:** a user can drive media, automations, agents, and dashboards from the chat box, and a sensitive action triggered from Chat still stops at an approval gate.

### Phase 8 — Power (ongoing)
Database-change triggers (LISTEN/NOTIFY) and external webhook exposure (opt-in, validated); MCP server support (user-added tools in Chat and as workflow/agent tools, treated as untrusted — `security.md` §6, §7); packaging with PyInstaller bundled into Tauri builds for Windows/macOS/Linux; the Tauri shell migration from pywebview when polished installers and auto-update are wanted.

## Deferred decisions (intentionally not settled yet)

- **The detailed agent execution model** — the exact planner/critic structure, how a loop is decomposed, the precise self-review format. Deferred to Phase 5, by agreement. The *constraints* (scope at the tool layer, limits, approval gates, notes, durable jobs) are fixed now; the internal mechanism is designed when we get there.
- **Code-node hardening beyond the subprocess sandbox** — a stronger isolation path (e.g. WASM/Pyodide) is a future upgrade; the subprocess-with-strict-limits is the minimum bar until then (`security.md` §5).
- **pywebview → Tauri** — start on pywebview for speed of iteration; migrate when release polish (installers, auto-update, smaller binaries) justifies the move. No code outside the shell layer should depend on which one is in use.
- **First-run database fallback** — whether to offer a bundled local Postgres or require the user to supply one is an onboarding decision to settle at Phase 0/1; either way Postgres is the store, and nothing about the BYO-database model changes.

## Competitive context (why Orrery is worth building)

Pieces of Orrery exist across three separate product categories — chat+RAG+agents apps (AnythingLLM, LibreChat, Open WebUI), visual workflow/agent platforms (Dify, n8n), and AI-dashboard/text-to-SQL tools (WrenAI, Chat2DB, Vanna). What none of them do is combine all six tabs in one **desktop, local-first** app where the **user's own Postgres is the single store** for chats, RAG, dashboards, workflows, and agent memory, with **per-widget and per-agent model choice** and the **"AI designs once, refreshes free"** dashboard pattern. To replicate Orrery today a user would run three separate server tools. That gap is the reason for the project; keep decisions pointed at preserving it: local-first, BYO-accounts/keys-and-database, one Postgres, multi-model throughout.
