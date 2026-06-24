---
name: orrery-development
description: >
  The single source of truth for building Orrery, a local-first desktop AI workspace
  (bring-your-own model accounts/API keys + bring-your-own database) with six tabs: Chat, Data,
  Dashboards, Automations, Agents, and Settings. Use this skill whenever the work
  touches Orrery in any way — writing or reviewing Orrery code, adding a feature, a
  workflow node, a dashboard widget type, or an agent capability; making stack,
  schema, or security decisions; updating the plan or the DEVLOG; or scaffolding any
  phase. Trigger it even when the user just says "let's work on the app," "continue
  Orrery," "add a node/agent/widget," or names a phase, without restating the whole
  context. It encodes the architecture, the security rules, the coding conventions,
  and the step-by-step discipline so every session builds Orrery the same secure,
  organized, accurate way.
---

# Building Orrery

Orrery is a **local-first desktop AI workspace**. The user brings their own model accounts/API keys and their own database; Orrery is the framework that ties them together. Nothing leaves the user's machine except calls to the model providers the user themselves configured.

This skill is the project's constitution. Read it at the start of any Orrery session, then read the reference file matching the task. **Consistency across sessions is the whole point** — when in doubt, match what is already documented here rather than inventing a new approach.

## The five principles (these override convenience, always)

1. **Security is not a feature, it is the floor.** Orrery handles three dangerous things: the user's secret model accounts/API keys, direct access to their database, and autonomous agents acting on their data. A shortcut that weakens any of these is never worth it. Before writing code that touches secrets, SQL, agent scope, the code-execution node, or the network boundary, read `references/security.md` and follow it exactly. If a request would violate it, say so and propose the safe version.

2. **Local-first and private by default.** The backend binds to localhost only. User data lives in the user's database, never in Orrery's own telemetry, never in logs, never sent anywhere. The only outbound traffic is to the model providers the user configured. Do not add analytics, crash reporting, or "phone home" behavior.

3. **Accuracy over assumption.** This is a data tool; wrong numbers silently erode trust. Queries are parameterized and validated. AI-generated SQL is shown to the user, not hidden. Anything the AI cannot ground in the schema or the data, it declines rather than guesses. Prefer explicit failure over a plausible-looking wrong answer.

4. **One language where it counts: Python.** All logic — API, providers, RAG, automation engine, agent loop — is Python. JavaScript only paints the screen. No Rust, no second backend language. Keep the dependency surface small; every new dependency is a security and maintenance cost (see the dependency rules in `references/security.md`).

5. **Document every step in plain words.** After any change to the codebase or the design, append a DEVLOG entry (see "The DEVLOG discipline" below). The DEVLOG is written so a non-expert can follow what happened and why. This is not optional bookkeeping — it is how the project stays coherent across many sessions.

## The architecture in one breath

Tauri-or-pywebview window → React (plain JS) frontend → local FastAPI backend (Python) → the user's model APIs/account routes (via litellm and official provider adapters), the user's PostgreSQL (via SQLAlchemy + pgvector), and a Procrastinate worker that runs automations and agents as durable jobs in Postgres. One process on the desktop; Postgres is the single store for chats, documents, dashboards, workflows, and agent memory.

Full detail — the stack table, the project tree, the data flow, and what each of the six tabs does — is in `references/architecture.md`. Read it before scaffolding or before adding anything that spans tabs.

## The six tabs (what each is, so they never blur together)

- **Chat** — conversations with the user's chosen model; streaming; optional RAG over the user's document collections.
- **Data** — connect databases, build document collections for RAG, browse tables read-only.
- **Dashboards** — the user describes a dashboard and picks a model; the model writes the SQL and chooses charts; Orrery saves it as a spec and refreshes it by re-running the saved queries (no AI cost to reuse). The AI is the designer, not the renderer.
- **Automations** — fixed-recipe visual workflows (DAGs) on a canvas; triggered by schedule, webhook, manual run, or database change.
- **Agents** — goal-driven workers that loop (plan → act → self-check → improve) within a strict scope until done, stopped, or a limit is hit; they keep learning notes and can hand off to each other, to automations, or to the user.
- **Media Hub** — a playground for image and video generation on the user's own media-model keys (or a local model); prompts and settings saved to the database, files to a local media library, any asset reusable elsewhere.
- **Settings** — Accounts & Keys (in the OS keychain), model providers, MCP servers, defaults.

The dividing line that must stay sharp: **an automation follows steps the user designed; an agent decides its own steps toward a goal.** If a feature request blurs them, clarify which one it belongs in.

**Chat is also a universal command surface.** Chat, Automations, and Agents share one tool registry; exposing it to the chat model lets the user invoke any feature — generate media, run an automation, start/query an agent, build a dashboard, search data — from the chat box. This is glue, not a bypass: every action invoked from Chat passes through the same approval gates, scope checks, and read-only/PII defaults as everywhere else (`security.md`).

## Build phases (current map)

0. Skeleton — `app.py` connects to Postgres, runs migrations, starts API + worker, opens the window.
1. Chat — streaming via model routing, history in Postgres, model picker, keychain accounts/keys.
2. Data — connection manager, RAG with pgvector, "use my data" in chat.
3. Dashboards — spec builder, chart widgets, refresh, revise, versioning.
4. Automations — engine, ~8–10 nodes, canvas, triggers, run debug view.
5. Agents — loop, scope enforcement, learning notes, activity feed, handoff queue.
6. Power — database-change & webhook triggers, MCP tools, packaging.

Build phases in order. Do not pull a later phase's complexity into an earlier one; the phases exist to keep each layer solid before the next leans on it. The detailed agent execution model is deliberately deferred to Phase 5. The roadmap with rationale is in `references/roadmap.md`.

## How to work on Orrery (the loop every session follows)

1. **Orient.** Read this SKILL.md. Identify which phase and which tab the task belongs to. Read the matching reference file (`architecture.md`, `security.md`, or `conventions.md`).
2. **Check security early.** If the task touches secrets, SQL, agent scope, code execution, or the network boundary, re-read the relevant part of `references/security.md` before writing code, not after.
3. **Build the smallest correct thing.** Match existing patterns (file layout, naming, how a node/widget/agent is registered — all in `references/conventions.md`). Keep new dependencies to a minimum and justify any addition.
4. **Verify.** Confirm queries are parameterized, secrets are not logged or returned to the UI, scope limits are enforced at the tool layer, and the change does the accurate thing on real-shaped data. Write or update a test where the conventions call for one.
5. **Document.** Append a DEVLOG entry in plain words: what changed, why, what's next.

## The DEVLOG discipline

Every step gets one entry, appended to `docs/history/DEVLOG.md`, newest at the bottom. An entry states, in plain language a non-expert can follow: **what we did, why we did it, and what comes next.** Keep implementation jargon out of the narrative (the user asked for plain words); name a library only when the choice itself is the point. The "Next up" line at the end is always kept current so the next session knows where to resume. This mirrors how the existing DEVLOG (Steps 1–9) is written — match that voice and structure.

## Reference files — read the one that fits the task

- **`references/architecture.md`** — the stack, the project structure, the runtime data flow, and a fuller description of each of the six tabs and how they interconnect (pinning a chart to a dashboard, an automation starting an agent, etc.). Read before scaffolding or before any cross-tab feature.
- **`references/security.md`** — the security standard in full: secrets handling, SQL safety and read-only enforcement, agent scope sandboxing, code-node isolation, prompt-injection defense for RAG and agents, the localhost/auth boundary, webhook exposure, dependency hygiene, and audit logging. Read before touching any of those areas. This is the most important reference; when it conflicts with anything, it wins.
- **`references/conventions.md`** — Python style and project conventions, the registry patterns for adding a workflow node / dashboard widget type / agent capability, error handling, configuration, and the testing approach. Read before adding any new unit of functionality.
- **`references/roadmap.md`** — the phases in detail with the reasoning behind the ordering and the deferred decisions. Read when planning a phase or deciding whether something belongs now or later.
