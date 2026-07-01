# Orrery — Development Plan (v3: Postgres-first, robust automations)

A desktop AI app where you bring your own model accounts/API keys and your own **PostgreSQL** database, and automate AI workflows visually (n8n-style). The core backend remains Python; the desktop shell is migrating to Electron so React stays the UI and Python stays the local application backend.

---

## 1. The Stack

**Python side (all the logic):**

```
pip install fastapi uvicorn litellm sqlalchemy psycopg "procrastinate[psycopg]" pgvector keyring
```

| What it does | Tool | Notes |
|---|---|---|
| Desktop shell | **Electron** | Production direction: launches the local Python backend and hosts the existing React UI. |
| Legacy package shell | **PyInstaller + Qt WebEngine** | Kept during migration so current Windows packages still run. |
| Backend / API | **FastAPI** | Chat, data, automation routes + SSE streaming. |
| AI providers | **litellm + official account adapters** | API-key providers use litellm; official subscription-backed routes can be added only when providers support them safely. |
| Database | **PostgreSQL** (SQLAlchemy + psycopg) | Single source of truth: chats, documents, workflows, runs, queue. |
| RAG / vectors | **pgvector** | Real vector search inside Postgres. `CREATE EXTENSION vector;` |
| Job queue + scheduler | **Procrastinate** | Postgres-native task queue: durable runs, automatic retries, cron-style periodic tasks, concurrency control — **no Redis, no Celery, no extra infrastructure.** |
| DB-change triggers | **LISTEN/NOTIFY** | Workflows can react to new rows in the user's tables, natively. |
| Accounts/API keys | **keyring** | OS keychain; no raw secrets are stored in Postgres or returned to the UI. |
| Packaging | **Electron Builder + packaged Python backend** | Target direction for signed installers and in-app update support. |

**Screen side (just the visuals):** one **React + Vite** app — plain JavaScript for now.

- **React Flow** (`@xyflow/react`) for the automation canvas — the industry-standard node editor library; smooth drag-drop, zoom, minimap, custom nodes.
- **Apache ECharts** for dashboard charts — lines, bars, stats, tables from one library.
- One-time setup: `npm create vite@latest ui` → during development `npm run dev`, for release `npm run build` produces static files that FastAPI serves. You rarely touch this layer once the components exist.

**AI quality & safety layer (added — five reinforcements to the two floors, privacy and accuracy):**

| Capability | Tool | What it adds | Phase |
|---|---|---|---|
| Local embeddings | `sentence-transformers` (BGE / nomic-embed) | RAG can run fully offline — document text never leaves the machine. A cloud embedding model stays optional, not required. | 2 |
| Hybrid search | pgvector **+** Postgres full-text (`tsvector`) | Combines semantic and keyword matching for materially better retrieval — no new infrastructure, both live in Postgres. | 2 |
| Structured outputs | `instructor` / constrained JSON-schema decoding | Forces valid, schema-checked model output — the single biggest reliability lever for agent tool calls and generated SQL. | 3–5 |
| SQL validation | `sqlglot` (parse + dry-run) | Schema-aware generation, parse-check, and a read-only dry-run before any generated query runs; self-correct on error. Accuracy for Dashboards. | 3 |
| PII redaction | `presidio` | Scans rows/documents and strips personal data **before** it is sent to a cloud model. Critical for a tool wired to a real database. See `security.md` §10. | 2 (cross-cutting) |

These are additive and local-first: none introduce a server, and four of the five live in phases already on the roadmap.

**Media generation (Media Hub):** image/video via the user's chosen provider through a small provider-adapter (mirroring the litellm approach), with an **optional local backend** (e.g. a local Stable Diffusion / ComfyUI endpoint) for fully on-device generation. Chat also supports a narrower safe path today: text models can produce declarative SVG code for illustrations and diagrams, which Orrery validates against a strict allowlist without executing model-written code; if a model returns unusable SVG repeatedly, Orrery creates a safe built-in SVG fallback. Generated Media Hub **files live in a local media library directory**; only their **metadata** (prompt, model, parameters, seed, file path, tags) goes in Postgres ? large binaries never go in the database. Content-safety rules for generated media are in `security.md` ?11.

---

## 2. How Orrery Runs

```
python app.py
 ├─ connects to Postgres (first run: asks for connection string, runs migrations, enables pgvector)
 ├─ starts FastAPI on localhost
 ├─ starts the Procrastinate worker (asyncio task in the same process)
 └─ opens the desktop shell window

Window (React)  ←SSE/HTTP→  FastAPI (Python)
                              ├─ model account/API adapters → AI providers
                              ├─ SQLAlchemy → PostgreSQL (+ pgvector)
                              └─ Procrastinate worker → executes workflow runs
```

The backend is a modular monolith: chat, providers, projects, data, RAG, jobs, settings, and admin/team features live in one local Python application. Sidecars handle isolated or heavy work such as Docker sandbox runs, local model runtimes, and official provider CLIs. Because the queue lives in Postgres, runs are **durable**: if the app closes mid-workflow, the run resumes/retries on next launch.

---

## 3. Interface (8 tabs)

**🗨 Chat** — conversation list, streaming replies, model picker, "use my data" (pgvector RAG) toggle. **Also a universal command surface:** typing `/` (or just asking) lets the user generate media, run an automation, start or query an agent, build or refresh a dashboard, or search their data — straight from the chat box, under the same guardrails (approval gates, scope, read-only defaults), because Chat shares the one tool registry used by Automations and Agents.

**🗄 Data** — Postgres connection manager, document collections (upload → chunk → embed → pgvector), table browser.

**📊 Dashboards** — describe a dashboard in plain words and pick **which model builds it**. The model writes the queries and chooses the charts; Orrery saves the result and refreshes it from live data. Revise anytime ("add a churn widget") with the same or a different model.

**⚡ Automations** (standalone tab)
- Workflow list: status, last run, success rate
- **React Flow canvas**: node palette on the left, drag-drop, connect edges, config panel on the right
- Run history: click any past run → see each node's input, output, duration, errors
- Toolbar: Run now · Activate · Pause · Duplicate · Export/Import JSON

**🎬 Media Hub** — a creative playground for image and video generation using the user's own media-model keys (or a local model). Prompt, pick a model, tune parameters (aspect, seed, count, negative prompt), do image→image and image→video, and keep a reusable media library. Prompts and settings are saved to the database; files live in a local media library; any asset can be pinned into Chat or used by an Automation.

**🪐 Agents** — give a goal instead of a recipe. An agent loops — plan, act, check its own work, improve — until the goal is met, a limit is hit, or you stop it. Each agent has a strict scope, its own model, a run mode (continuous / until done / timer / trigger), and a live activity feed.

**Local Models** — install the fixed official Ollama runtime on Windows with explicit consent, start its local service, download reviewed starter models with progress, control which installed models appear in Chat, and remove them. No API key is required.

**⚙ Settings** — responsive General, Accounts & Keys, Models, Usage, Integrations, and Feedback sections; optional company header; secrets remain in the keychain.

---

## 4. Automation Engine (the "better stack")

A workflow = a DAG of nodes saved as JSON in Postgres (with version snapshots on every save).

**Execution model:**
1. A trigger fires → a **Procrastinate job** is enqueued in Postgres.
2. The worker picks it up, topologically sorts the DAG, executes nodes async, passing outputs forward.
3. Every node's input/output is written to `workflow_run_steps` → powers the debug view.
4. Failures follow per-node policy: stop, continue, or **retry with exponential backoff** (Procrastinate built-in).

**Triggers:**

| Trigger | Implementation |
|---|---|
| Schedule (cron) | Procrastinate periodic tasks |
| Database change | Postgres trigger function → `NOTIFY` → listener enqueues a run |
| Webhook | FastAPI endpoint per workflow (localhost; tunnel for external) |
| Manual | UI button |

**Node palette (v1):** LLM prompt (with `{{node.output}}` templating) · Search my documents · DB query · DB insert/update · HTTP request · If/branch · Loop · Delay · Python snippet (sandboxed subprocess) · Refresh dashboard · Start agent · MCP tool (Phase 6).

Each node type = one Python class with `async def execute(inputs, config)` registered in a registry — adding nodes is one file.

---

## 5. Dashboards — designed by AI, refreshed without it

The user describes what they want to see and picks the model. The model inspects the connected schema, writes the SQL for each widget, and chooses chart types. Orrery saves the result as a **spec** — JSON in the database:

```json
{ "name": "Sales overview", "built_by": "claude-sonnet-4-6",
  "widgets": [
    {"title": "Revenue this month", "chart": "stat",
     "sql": "SELECT SUM(total) FROM orders WHERE ...", "by": "claude-sonnet-4-6"},
    {"title": "Top products", "chart": "bar",
     "sql": "SELECT product, SUM(total) ...", "by": "claude-sonnet-4-6"}
  ]}
```

Why this design:

- **Reusable and free to refresh** — opening or refreshing a dashboard just re-runs the saved SQL (read-only) against live data. No AI call, no token cost. The model is the *designer*, not the renderer.
- **Multi-model** — every dashboard and every widget records which model made it; a revision can use a different model than the original.
- **Composable** — a chart a model produces in Chat can be pinned to a dashboard, and an automation node can refresh or snapshot a dashboard on a schedule.
- **Versioned** — specs are snapshotted on every revision, like workflows, so a bad AI edit rolls back in one click.

## 6. Agents — continuous, scoped, self-improving

Where an automation follows a fixed recipe, an **agent gets a goal and figures out the steps** — then loops: plan → act → check its own work → improve → repeat, until the goal is met, a limit is hit, or the user stops it.

Every agent is defined by four things:

- **Goal** — plain words ("keep every new ticket triaged; ask me when unsure").
- **Scope** — the only area it may touch: named tables with read/write split, allowed tools, hard limits (loops per day, spend per day, confidence bar). Enforced at the tool layer, so the agent *cannot* act outside it.
- **Model** — each agent runs on the model the user picks, like dashboards.
- **Run mode** — continuous (until stopped) · until done · on a timer · on a trigger.

**"Improving again and again":** every iteration ends with a self-review, and the agent writes short **learning notes** to its own memory table; the next iteration reads them first. Mistake patterns become rules over time, per agent.

**Working together:** agents and automations share the same tool registry, so an automation can start an agent, an agent can fire an automation, and agents hand work to each other — or to the user through approval gates — via a shared handoff queue in the database. Solo, alongside each other, or in collaboration, wired the same way workflows are.

**Oversight is non-negotiable:** a live activity feed of every action and learning, a daily budget meter, approval gates for low-confidence or sensitive writes, and a stop button that always works. Iterations run as Procrastinate jobs, so a continuous agent survives app restarts.

*(The detailed execution model gets designed when we reach Phase 5 — agreed.)*

## 7. Build Phases

| Phase | Goal | Time |
|---|---|---|
| **0 — Skeleton** | `python app.py` → connects to Postgres, runs migrations, opens window with the React shell | 2–3 days |
| **1 ? Chat** | Streaming chat via model routing, history in Postgres, model picker, keychain accounts/keys, reasoning controls, requested-file exports/previews, safe SVG artifacts, local Ollama model manager | ~1 week |
| **2 — Data** | Connection manager, RAG with pgvector + **hybrid (vector+keyword) search**, **local-embeddings option**, **PII redaction before cloud models**, "use my data" in chat | ~1.5 weeks |
| **3 — Dashboards** | Spec builder with **schema-aware SQL + dry-run validation** and **structured outputs**, ECharts widgets, refresh, revise, versioning | ~1.5 weeks |
| **4 — Automations** | Procrastinate engine, 8–10 nodes, React Flow canvas, cron + manual triggers, run debug view (**structured outputs** for AI nodes) | ~2 weeks |
| **5 — Agents** | Agent loop on Procrastinate, scope enforcement, learning notes, activity feed, handoff queue (**structured outputs** for tool calls) | ~2 weeks |
| **6 — Media Hub** | Image/video generation (provider adapters + optional local backend), parameters, media library (files on disk, metadata in Postgres), pin-to-Chat, content safety | ~1.5 weeks |
| **7 — Chat command surface** | Expose the shared tool registry to Chat so `/` or natural language can generate media, run automations, start/query agents, build dashboards — with the same approval/scope/read-only guardrails | ~1 week |
| **8 — Power** | LISTEN/NOTIFY + webhook triggers, MCP tools, Electron packaging/update path | ongoing |

---

## 8. Project Structure

```
orrery/
├── app.py                    # run this — DB check, API, worker, window
├── README.md                 # setup and project overview
├── backend/
│   ├── api.py                # FastAPI routes and local-session protection
│   ├── core/                 # config, database, models, migrations, queue
│   ├── providers/            # accounts, model routing, model catalog
│   ├── features/             # chat, code images, local models, data, RAG, usage, feedback
│   └── security/             # secrets, privacy, network guards
├── tests/                    # mirrors the backend domain folders
├── ui/                       # React + Vite (plain JS)
├── docs/                     # planning, history, research, security, design
├── scripts/setup/            # environment/dependency setup helpers
└── assets/desktop/           # Windows and desktop icon assets
```

---

## 9. Deliberately Avoided

- **Microservices now** → modular monolith keeps packaging and local security manageable; split only sandbox/RAG/model-gateway workers later if scale requires it.
- **Celery + Redis** → Procrastinate gives queues, retries, and cron using only Postgres.
- **Embedding n8n itself** → its fair-code license restricts embedding; our engine stays pure Python and fully ours.
- **TypeScript** → plain-JS React is enough; logic lives in Python anyway.

---

# 10. Task Routing & Capability Agent (single source of truth)

> This section folds in `TASK_ROUTING_ARCHITECTURE.md` and the `architecture_imp/` production review.
> Those files remain for detail; this is the authoritative summary.

**Principle (from OpenClaw + Hermes):** the user should never have to phrase a request a special way.
One loop per turn: build context (app rules + skills + tool descriptions + project/user memory +
history + RAG-as-untrusted) → the model reasons → the model may call a tool → the result is fed back →
loop → finalize → remember. Capabilities, not raw permissions; the only powerful tool is the sandbox.

**Today (regex planner):** `taskrouter.plan()` classifies a turn (chat/file/image/audio/project),
loads skills, and picks a safe executor (chat → `ai`; image → sanitized SVG; file → `docgen` first,
sandboxed `filegen` when code/visuals/audio/computation; project → workspace). Work is observable via
`reasoning_event` trace + the Task Brain ledger + `route_telemetry`.

**Target (Capability Agent):** demote the planner to a *hint*; give the model tools and let it decide.
- `run_code(python)` — universal artifact maker in the locked-down sandbox (PDF/deck/sheet/image/audio/zip).
- `render_svg(brief)` — fast vector image. `build_doc(spec)` — deterministic docgen.
- **Hybrid, model-agnostic execution:** native litellm tool-calling where supported; a universal
  fenced-block convention (one ```python or ```orrery-doc block) everywhere else (CLI plans, tool-less
  local models). One executor + one validator behind both. Safety unchanged: model code only runs in the
  sandbox; the backend validates every artifact; untrusted context is never executed.

**Capability Agent phases:** (1) sandbox-as-tool universal convention (model decides on the fly);
(2) native tool-call loop; (3) skill memory (record the winning skill/tool stack per project, replay it);
(4) voice/media tools; (5) tool telemetry.

---

# 11. Status — Done & Remaining (updated 2026-07-01)

### Done — foundation & hardening
- **Phases 0–2:** desktop shell, streaming chat, model routing (API keys + Claude/ChatGPT/Gemini CLI
  plans + Ollama + custom OpenAI-compatible + **OpenRouter**), Postgres history, RAG (pgvector + hybrid +
  local embeddings + PII redaction), "use my data".
- **File generation:** code-execution sandbox (`filegen`) + deterministic `docgen`, backend validation
  (open/parse each file, reject placeholders/thin content, enforce requested format, retry on failure),
  previews, document-title naming, presentations routed to the rich code-exec path (offline visuals).
- **Thinking:** `ThinkStream` condenses the model's *actual* reasoning (separate channel OR inline
  `<think>`) into multi-step trace summaries — universal across chat, docgen, and code-exec, every model.
- **Security:** cloud privacy boundary (Off/Basic/Strict), centralized `redact_secrets`, fail-closed
  keyring, netguard hardening, CLI error scrubbing, `docs/security-boundaries.md`.
- **DB:** versioned migrations (`schema_migrations`), CHECK constraints, pgvector HNSW index, typed app
  settings.
- **Prompts:** all system prompts consolidated in `prompting.py` (`FORMAT_INSTRUCTIONS`,
  `FILE_SYSTEM_PROMPT`, `SVG_SYSTEM_PROMPT`) + layered `build_system_prompt` (RAG = untrusted layer).
- **Providers:** model manifest (IDs/versions out of code), CLI flag-safety tests, honest `pricing_known`.
- **Ops:** request IDs + structured logs, route telemetry (`task_route_events`), **Task Brain** ledger +
  Activity panel + background-run resume, live token count, connect/disconnect → picker, no flashing
  console windows, generated-file TTL cleanup, branding fix, Ollama pre-flight, Windows onedir release,
  macOS `.app` packaging scaffolding, Electron shell scaffold, and in-app update checks.
- **Projects:** model + API + hierarchical chat listing + scoped chat start + chat assignment + trusted
  project context in prompts.
- **Polish:** refined app logo (in-app mark + favicon); `chat.py` split (`chat_context.py`).

### Remaining — by priority
1. **Projects UX polish** *(near-term):* chats shown nested under their project; clicking a project opens
   it and offers "new chat inside this project".
2. **Capability Agent** *(core vision):* phases 1→5 above (model decides + sandbox tool loop, skill memory).
3. **Provider adapter split** (`accounts.py` → per-provider adapters + `ProviderAdapter` interface) and
   **JSONB** columns — production polish, lower urgency (most P0/P1 hardening already shipped).
4. **Phases 3–6 (product surface):** Dashboards, Automations, Agents, Media Hub.
5. **Release polish:** Electron Builder Windows installer, signed/notarized macOS packages,
   architecture-specific macOS artifacts if needed, in-app automatic update publishing, then Linux
   packaging.
6. **Voice/TTS/STT**, sandbox security tests, DB read-only role guidance, and the long-term
   **Ollama-free local inference engine**.
7. **Speed:** only *perceived* speed can improve at high effort (never cut effort).

---

# 12. Production-Hardening Plan — Task-Routing Core

> "Fragile" here is specific and grounded, not a vibe. The *pieces* are well-tested
> (`taskrouter`, `filegen`, `docgen`, `prompting`, `route_telemetry`, `_generate` — ~36 tests). The
> risk is concentrated in **`chat.stream_reply`** (~158 lines): it does DB I/O *inline*, then planning,
> then five route branches, detached-run wiring, and telemetry — all in one async generator, with **no
> integration tests on the orchestration itself**. So the executors are safe, but changing the *glue*
> can't be verified. The fix is seams + tests + decomposition, each phase shippable and green.

### Phase A — Seams (make it testable)
1. [x] Extract `_prepare_turn(conv_id, content, attachments) -> TurnContext` (load conversation + history +
   persist the user message). One mockable DB seam instead of inline I/O in the orchestrator.
2. [ ] Add a `fake_db` pytest fixture (in-memory async session) so DB-touching code is testable without Postgres.

### Phase B — Decompose the orchestrator
3. [x] Split `stream_reply` into a thin dispatcher + one handler per route — `_route_model_reply`, `_route_file`,
   `_route_image`, `_route_audio_unavailable`, `_route_project_create`, `_route_research` — each a small single-responsibility async generator.
   Verbatim move, no logic change; the full suite stays green.
4. [x] Centralize SSE event shapes (a typed `events` helper) so the stream protocol is explicit and consistent.

### Phase C — Lock it down
5. [x] Integration tests for the dispatcher: each route → correct executor + events; fallback chain
   (sandbox miss → docgen → plain reply); error, cancellation, and resume paths. Covered: route dispatch,
   sandbox miss → docgen success, sandbox miss → docgen miss → model reply, detached generator errors,
   resume, and cancellation bookkeeping.
6. Audit every external `await` (DB / ai / sandbox) for graceful degradation (most already guarded).
7. CI gate: `compileall` + import smoke tests + full suite on every change.

### Phase D — Resilience polish
8. Bound all retry loops + add timeouts at every boundary (filegen already caps at 3; ledger is
   timeout-isolated) and confirm cancellation can't orphan a run.
9. `UserSafeError` with codes → consistent, actionable error events in the UI.

**Outcome:** a small readable dispatcher, every route independently tested, regressions caught by CI,
no inline DB I/O in the orchestrator. That is "production-ready, not fragile."

---

## v4 Build Status (living)

Tracks the enhanced v4 plan against the real codebase. Updated as features land.

Implemented:
- [x] Reasoning panel shows a clean public work trace (route, context, tool, validation, files, sources)
      while hidden model scratchpad / provider reasoning is stripped from the visible stream. The panel
      stays rolled-up after the answer instead of vanishing.
- [x] Code interpreter: the model writes and runs Python in the hardened sandbox (```orrery-run);
      stdout + produced files come back and drive the answer.
- [x] Universal web search: the model searches when it wants (```orrery-search) on ANY model/connection
      (keyless backend search via ddgs); also wired into Deep Research. Results are untrusted + redacted.
- [x] Deep Research: decompose -> gather (documents + web) -> one cited report; toggle now in the chatbox.
- [x] Deep Reasoning Mode selector (Quick/Standard/Deep/Max -> effort + file-repair budget).
- [x] File generation prefers the sandbox -> an actual downloadable file shown as a rich card (thumbnail
      + Type/EXT/size + Preview/Download, "Download all" for multiple). Deterministic docgen is the fallback.
- [x] Sandbox artifact generation now recognizes and validates HTML/web pages, audio, video/MP4/WebM,
      WebP, Markdown, text, JSON, archives, documents, slides, sheets, images, and WAV/MP3-style outputs;
      audio/video/html can be previewed directly from generated file cards.
- [x] Sandbox runs expose structured `input` / `workspace` / `out` directories and return a sanitized
      run manifest (run id, limits, status, output file names/sizes) without prompts, generated code,
      logs, or secrets.
- [x] Project workspaces: per-project files -> RAG, project-scoped chats, trusted project context.
- [x] stream_reply split into route handlers + dispatcher tests; route telemetry (sanitized).
- [x] Chat stream event shapes centralized in `backend.features.events`, preserving the current UI wire format.
- [x] Sources rendered inside the reasoning panel (no raw URL banner).
- [x] Local API session token; secrets only in keychain.

- [x] Context: chat searches ALL relevant sources together every turn - selected data collection,
      project files, this chat's own uploaded attachments (indexed for durable memory), and any
      connected ontologies. No more either/or; files/data are no longer forgotten.
- [x] Ontology tab: reusable knowledge bases built from the user's own files; a 'connected' ontology
      is automatically used as standing context in every chat (RAG-backed; hidden from the Data tab).
- [x] Reasoning persisted across reloads.

Next:
- [x] MCP server support: configured in the Skills tab; live stdio JSON-RPC client (Test connection
      caches tools) exposed to the chat tool loop via orrery-tool; output treated as untrusted;
      per-server opt-in; admin 'mcp' flag. TODO: http/SSE transport.
- [x] User-creatable skills: Skills tab to create/upload/edit/enable/delete your own skill playbooks;
      enabled ones are merged with the built-ins and injected per matching message.
- [x] Admin user + feature flags: an Admin tab; a token (OS keychain) gates global on/off of code
      interpreter, web search, Deep Research, ontology, file gen, media, automations, agents, MCP.
      Enforced in chat; the rail hides tabs for off features. (Single instance — see team decision below.)
- [x] **Team / multi-user (shared-Postgres model).** All clients point at one team Postgres; admin-managed
      resources are shared automatically. Built: a `team_users` table with access keys (sha256-hashed,
      shown once) + roles (admin|member); founding-admin bootstrap from the Admin tab; a lock screen for
      clients without a key; per-user ownership of chats/projects (private per person; shared skills/
      ontologies/MCP stay common); and an approval queue (member-authored skills/MCP are pending until an
      admin approves them team-wide). Each user keeps their own model keys in their own keychain.
      TODO: bootstrap is deliberate founding-admin setup (not first-connect); no team-teardown UI yet.
- [ ] Per-segment outer reasoning headlines (the multi-card 'what's going on' view).
- [ ] Optional keyed web-search provider (Brave/Tavily) for higher volume/precision.

Later phases (not started): Dashboards, Automations, Agents, Media Hub, Capability Contract schema,
Approval gates, JSONB metadata migration.
