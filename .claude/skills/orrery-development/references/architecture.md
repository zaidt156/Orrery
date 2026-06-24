# Orrery Architecture

Read this before scaffolding a phase or building anything that spans more than one tab. It describes the stack, the project layout, how a request flows at runtime, and what each of the six tabs is and how they connect. For *why* the stack is what it is, and for safety constraints on each part, pair this with `roadmap.md` and `security.md`.

## The stack

All logic is Python; JavaScript only paints the screen; there is no second backend language.

| Concern | Tool | Notes |
|---|---|---|
| Desktop window | pywebview (prototype) → Tauri (release) | Pure-Python window to start; Tauri later for polished installers and auto-update. The shell runs the Python backend as a sidecar. |
| Backend / API | FastAPI + uvicorn | Local HTTP + SSE streaming. Binds to localhost only. |
| Model access | litellm + official account adapters | API-key providers use litellm; official subscription-backed routes can be added only when providers support them safely. |
| Database | PostgreSQL via SQLAlchemy + psycopg | Single source of truth: chats, documents, dashboard specs, workflows, run logs, agent memory, and the job queue. |
| Vector search (RAG) | pgvector | Real vector similarity inside Postgres; no separate vector database. |
| Hybrid retrieval | pgvector + Postgres full-text (`tsvector`) | Semantic + keyword matching for better recall; both in Postgres, no new infra. |
| Local embeddings (option) | sentence-transformers (BGE / nomic-embed) | Offline embedding so document text need never leave the machine. |
| Structured outputs | instructor / JSON-schema decoding | Schema-valid model output for agent tool calls and generated SQL. |
| SQL validation | sqlglot | Parse + read-only dry-run of generated SQL before it runs (Dashboards). |
| PII redaction | presidio | Strips personal data from content bound for cloud models (`security.md` §10). |
| Job queue + scheduler | Procrastinate | Postgres-native task queue: durable runs, automatic retries with backoff, cron-style periodic tasks. No Redis, no Celery. |
| Database-change triggers | Postgres LISTEN/NOTIFY | Workflows/agents can react to row changes natively (Phase 6). |
| Secrets / accounts | keyring | OS keychain. Raw keys and account tokens are never stored in Postgres or returned to the UI. See `security.md` §1. |
| Frontend | React + Vite, plain JavaScript | No TypeScript required. Built to static files that FastAPI serves. |
| Workflow canvas | React Flow (`@xyflow/react`) | The node editor for the Automations tab. |
| Charts | Apache ECharts | Dashboard widgets (stat, line, bar, table). |
| Media generation | provider adapters (+ optional local Stable Diffusion / ComfyUI) | Image/video on the user's own keys, mirroring the litellm approach; a local backend enables fully on-device generation. |
| Media storage | local media library (files) + Postgres (metadata) | Large binaries live on disk; prompt/model/params/seed/path/tags live in Postgres. Never store media blobs in the database. |
| Packaging | PyInstaller (+ Tauri bundling) | One executable per OS; the built UI is bundled. |

Install footprint to keep in mind: the whole app needs essentially **Python plus Postgres**. Keep it that way; new dependencies are a cost (`security.md` §8).

## Runtime data flow

```
launch: app.py
  ├─ ensure DB connection (first run: prompt for connection string, run migrations, enable pgvector)
  ├─ generate the session auth token
  ├─ start FastAPI on localhost (random free port)
  ├─ start the Procrastinate worker (asyncio task in the same process)
  └─ open the window pointing at the local server, passing the token

request path:
  Window (React)  ──HTTP/SSE, with session token──▶  FastAPI (Python)
                                                       ├─ model account/API adapters ─▶ user's model providers
                                                       ├─ SQLAlchemy ─▶ user's PostgreSQL (+ pgvector)
                                                       └─ enqueue/execute Procrastinate jobs
  Procrastinate worker  ──▶ runs automation DAGs and agent loops as durable jobs
```

One process on the desktop, but because the queue lives in Postgres, **runs are durable**: if the app closes mid-run, the job resumes or retries on next launch. The same design can later run headless on a server with no code change.

## Project structure

```
orrery/
├── app.py                    # desktop entry point
├── README.md                 # setup and project overview
├── backend/
│   ├── api.py                # local FastAPI boundary
│   ├── core/                 # config, database, models, migrations, queue
│   ├── providers/            # account routes, model routing, model catalog
│   ├── features/             # chat, data, RAG, usage, feedback
│   └── security/             # keychain, privacy redaction, network guards
├── tests/                    # mirrors backend domains
│   ├── core/
│   ├── providers/
│   ├── features/
│   └── security/
├── ui/                       # React + Vite (plain JS)
│   └── src/
│       ├── views/            # one file per main tab
│       ├── components/       # shared visual components
│       └── lib/              # API client and formatting helpers
├── docs/
│   ├── planning/             # roadmap and migration plans
│   ├── history/              # append-only DEVLOG
│   ├── research/             # provider and technical research
│   ├── security/             # security reviews and connection guidance
│   └── design/               # interface references
├── scripts/setup/            # environment and dependency setup helpers
└── assets/desktop/           # desktop icon assets
```

Keep new code in the package that owns its concern. Cross-cutting helpers (secrets, redaction, connection resolution) live in one place and are imported, not re-implemented.

## The six tabs in detail

### Chat
Conversations with the user's chosen model. Streaming responses over SSE. A model picker, editable system prompt, reasoning effort, and approximate context-window budget are stored per conversation. The context limit trims only the oldest model-bound turns; full visible history remains in Postgres. A "use my data" toggle runs RAG over the user's document collections (pgvector) and the reply shows which collection/snippets were used. A chart the model produces here can be **pinned to a dashboard** (see Dashboards).

### Data
Three areas: **connections** (add/test multiple databases, each with its own credentials and isolation — `security.md` §2), **document collections** for RAG (upload → chunk → embed → store in pgvector; a collection can also live-sync from a table, auto-embedding new rows), and a **table browser** that is strictly read-only (`security.md` §3). Row changes here are what database-change triggers watch (Phase 6).

### Dashboards
The defining pattern: **the AI is the designer, not the renderer.** The user describes a dashboard in plain words and picks which model builds it. That model inspects the connected schema, writes the SQL for each widget, and chooses chart types. Orrery saves the result as a **spec** (JSON in Postgres) recording, per widget, the title, chart type, the SQL, and which model authored it. Thereafter:
- Opening or refreshing a dashboard **re-runs the saved read-only SQL** against live data — no model call, no token cost. Reuse is free and cannot introduce new unseen SQL.
- A dashboard and each widget record their authoring model; a revision ("add a refunds widget") can use a different model than the original.
- Specs are **versioned** (snapshot on every revision) so a bad AI edit rolls back in one click.
- Composability: a chart from Chat can be pinned here; an automation can refresh or snapshot a dashboard on a schedule.

### Automations
**Fixed-recipe** visual workflows. A workflow is a DAG stored as JSON in Postgres (versioned on save). The canvas (React Flow) has a node palette, draggable nodes, edges, and a per-node config panel; values from earlier nodes flow forward via `{{node.output}}` templating. Triggers: schedule (cron), manual, webhook (local by default), and database-change (Phase 6). Execution runs as a Procrastinate job: topological sort, async node execution, every node's input/output/duration/errors logged to power the run-debug view; per-node failure policy is stop / continue / retry-with-backoff. Node categories: triggers, AI (LLM prompt, search docs), data (DB query, DB write, HTTP, file), logic (if/branch, loop, delay), code (sandboxed Python snippet — `security.md` §5), and tools (refresh dashboard, start agent, MCP tool in Phase 6). Adding a node type is one class in a registry (`conventions.md`).

### Agents
**Goal-driven** workers, the counterpart to Automations. An agent receives a goal in plain words and loops — plan → act → check its own work → improve — until the goal is met, a limit is hit, or the user stops it. Defined by four things: a **goal**, a **scope** (the only tables/tools it may touch, plus loop/spend/confidence limits — enforced at the tool layer per `security.md` §4), a **model** (user-picked, per agent), and a **run mode** (continuous / until done / on a timer / on a trigger). It keeps **learning notes** in its own memory table — each loop ends with a self-review and writes what it learned; the next loop reads those notes first, so it improves over time. Agents **collaborate** through a shared handoff queue: an automation can start an agent, an agent can fire an automation, and agents can hand work to each other or to the user via approval gates. Oversight is built in: a live activity feed of every action and learning, a daily budget meter, approval gates for low-confidence or sensitive writes, and an always-working stop. Iterations run as Procrastinate jobs, so a continuous agent survives restarts. The detailed execution model is deferred to Phase 5 (`roadmap.md`).

### Media Hub
A creative **playground** for image and video generation using the user's own media-model keys, with an **optional local backend** (Stable Diffusion / ComfyUI) for on-device generation. The user writes a prompt, picks a model, tunes parameters (aspect, seed, count, negative prompt), and can do image→image and image→video from a reference (including an asset pinned from Chat). Output handling follows the storage rule above: **files go to a local media library directory; only metadata** (prompt, model, parameters, seed, file path, tags) goes in Postgres. Generation is exposed as a **tool** in the shared registry, so Chat and Automations can produce media too. Content-safety rules are in `security.md` §11.

### Settings
Accounts & Keys shows API keys masked with a keychain-status badge, local model routes, and official account routes where providers support them (never the real secret or token — `security.md` §1), plus model providers, MCP servers (Phase 6), and defaults (model, temperature, theme, run-log retention).

## How the tabs interconnect (keep these wired the same way)

- A **chart from Chat** → pinned into a **Dashboard** widget.
- An **Automation** → can *refresh a Dashboard* or *start an Agent* as a node.
- An **Agent** → can *fire an Automation*, hand off to *another Agent*, or escalate to the *user* — all through the one shared handoff queue.
- A **Media Hub** asset → pinned into **Chat** (as a reference or to discuss) or used by an **Automation** (e.g. generate an image as a workflow step).
- **Chat as command surface** → Chat is given the **shared tool registry**, so a chat message can generate media, run an automation, start/query an agent, or build/refresh a dashboard. Same registry, same enforcement — not a side door.
- All of them read/write the **same Postgres** and call models through the **same model routing layer** with the **same keychain-stored accounts/keys**.

The shared pieces — the connection registry, the **tool registry (now also driving Chat's command surface)**, the handoff queue, the secrets module, the model layer, and the media library — exist once and are reused. Don't fork them per tab. In particular, media generation and every Chat-invoked action are registered tools, so they inherit scope, approval, and logging for free.
