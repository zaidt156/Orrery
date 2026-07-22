# Orrery plan

Last reconciled with executable code: **22 July 2026**.

This is the single roadmap for Orrery. It explains what should be built, why it is ordered this
way, and what “done” means. The current implementation is documented in
[`ARCHITECTURE.md`](ARCHITECTURE.md), the active checklist lives in [`TODO.md`](TODO.md), and
completed work is recorded in [`docs/history/DEVLOG.md`](docs/history/DEVLOG.md).

## Product outcome

Orrery is a local-first desktop AI workspace. A person brings their own model accounts or API keys
and their own data. Orrery connects Chat, Projects, Data, Ontology, Dashboards, Automations, Agents,
Media, Skills, and Settings without creating a hosted Orrery account or silently moving private data
off the machine.

The target product has four defining qualities:

1. **Private by default.** Secrets stay in the operating-system keychain. External calls happen only
   through a provider or tool the user enabled, with visible consent where data crosses a new
   boundary.
2. **Accurate and auditable.** Retrieved text and tool output are untrusted data. SQL is validated,
   read-only where promised, and visible. Agent/tool actions have durable traces.
3. **One coherent workspace.** Chat, dashboards, workflows, agents, and media reuse the same model,
   tool, scope, approval, storage, and file boundaries rather than growing parallel systems.
4. **Useful without a cloud control plane.** The desktop app, PostgreSQL, local files, and optional
   local sidecars are sufficient to run Orrery.

## Non-negotiable architecture decisions

- Python owns application logic; React renders the interface. A .NET rewrite is not planned.
- The application is a modular monolith. FastAPI and the durable worker run locally; risky/heavy work
  runs in bounded sidecars such as Docker, provider CLIs, LibreOffice, and Ollama.
- PostgreSQL is the durable application store and job queue. Large generated/media files live on
  disk; secrets live in the OS keychain.
- The local API binds to loopback and requires a fresh per-launch session token.
- Cloud-model calls pass through the privacy boundary. Web search is a separate third-party boundary
  and requires explicit consent for each Chat message.
- Tools are registered once. Scope, argument validation, risk classification, approval, and audit
  behavior belong below the model at the registry/execution boundary.
- Automations follow a saved recipe; Agents choose steps toward a goal. They may interoperate, but
  their semantics remain distinct.
- “Strict” security promises must be enforced in code. A prompt instruction is never an authorization
  control, network boundary, SQL boundary, or sandbox.

## Current baseline

The following product paths are live end to end: desktop startup, Chat, Projects, model routing,
Data, Ontology/RAG, Dashboards, file generation and previews, Skills, approved stdio MCP tools,
team/admin controls, LIFE proposal review, and bounded manual/scheduled Agent runs.

The following are present but incomplete:

- Automations has storage, an executor, nodes, and durable run records, but no registered product API,
  schedule tick, or live editor UI.
- Media Hub is a static screen. Chat can create media artifacts, but the library/generation product
  path is not connected.
- Agent API/Slack/Gmail trigger shapes exist, but no inbound receivers are registered. Agent LIFE
  permissions and learning notes are not consumed by the run loop.
- Chat can search, retrieve data, refresh dashboards, and run approved tools, but it cannot yet start
  agents/workflows or create dashboards as a universal command surface.

## Delivery order

The ordering is risk-first. A later workstream may begin only when it does not bypass the checkpoint
before it.

### Workstream 1 — Close production trust-boundary gaps

This is the current priority. Finish the shared enforcement layer before exposing more agent,
automation, connector, or MCP power.

1. Add a central approval gate for Chat and every non-Agent tool execution path that can write,
   contact an external system, use credentials, or has unknown MCP risk. The approval must bind to a
   digest of the exact validated arguments and expire safely.
2. Make team identity and feature authorization fail closed on database, migration, or configuration
   errors. Solo/admin bootstrap is valid only when an explicit first-run state proves no team exists.
3. Harden every outbound HTTP path against redirect SSRF and oversized responses: disable automatic
   redirects, validate every hop and resolved address, and stream into a hard byte cap.
4. Remove credentials from persisted/returned dataset source URLs. Store secrets in the keychain and
   expose only canonical redacted URLs and sanitized errors.

**Checkpoint:** abuse-case tests pass for approval replay/tampering, team database outages, redirect
chains to private hosts, DNS changes, oversized bodies, and credential-bearing URLs.

### Workstream 2 — Finish the untrusted-document and reliability boundary

1. Move Office ingestion and Office/PDF preview parsing into an offline, read-only, resource-bounded
   worker. Keep any host fallback explicit and temporary.
2. Split backend tests into deterministic timed groups so a slow or hung test is named immediately.
3. Promote real-container sandbox/OCR smoke checks to repeatable CI fixtures, including encrypted,
   malformed, oversized, mixed, and multilingual documents.
4. Introduce a small web-search provider interface. Keep the zero-configuration provider, then allow
   user-configured official/self-hosted providers without changing Chat’s consent contract.

**Checkpoint:** untrusted documents never require an ambient host parser for the supported path;
focused and full CI gates are deterministic.

### Workstream 3 — Connect the unfinished product surfaces

#### Automations

Build one vertical slice at a time: authenticated CRUD, manual run, durable run/debug view, editor
load/save, then scheduling. The live UI must advertise only registered nodes and implemented trigger
types. Writes and external actions use the central approval gate.

#### Media Hub

Add provider adapters and an optional local backend behind one generation interface, then a local
file library with PostgreSQL metadata. Validate uploaded references, retain provenance metadata where
supported, and expose generation through the shared tool registry.

#### Chat command surface

After the approval gate and product APIs exist, let Chat start/query Agents, run Automations, and
create/revise Dashboards through the same registered interfaces. Do not add feature-specific bypasses
inside Chat.

**Checkpoint:** each surface works from its own screen and from Chat with the same scope, approval,
privacy, and audit behavior.

### Workstream 4 — Complete the Agent platform

1. Implement scoped, hashed, revocable per-Agent API credentials and a rate-limited inbound run
   endpoint. The secret is shown once; internet exposure remains an explicit user deployment choice.
2. Add bounded learning notes: at most one short self-review per completed run, visible to the user
   and included in later runs under strict count/size limits.
3. Apply `life_access` during execution: `read` includes approved memory; `propose` may create a
   reviewable diff but never mutate LIFE directly.
4. Design Slack/Gmail connection and receiver flows before coding them. Credentials remain in the
   keychain, grants are least-privilege, inbound events are authenticated/deduplicated, and all
   external writes remain approval-gated.

**Checkpoint:** API, schedule, and eventual connector triggers create the same durable, scoped Agent
run; learning and LIFE behavior is inspectable and reversible.

### Workstream 5 — UX, durability, and release completion

- Make detached Chat generation durable across backend restarts or clearly label its current
  process-lifetime guarantee.
- Make strict privacy materially stronger than basic privacy, or rename the modes so the UI does not
  promise a distinction that code does not enforce.
- Review the generic HTML preview CSP and enable Electron renderer sandboxing when compatibility is
  proven.
- Add the dedicated dashboard editing workspace and finish optional Concept-mode per-view polish.
- Measure long-thread rendering before deciding on virtualization; optimize only with profiler data.
- Reconcile dependency alerts on the default branch, keep lockfiles/audits green, provision the
  current sandbox image in releases, and complete Linux packaging after Windows/macOS stability.

## Deferred decisions

- A persistent “Computer” broker that unifies file generation and multi-step code work remains a
  possible later abstraction. It must not land before central approval, isolation, lifecycle, and
  capability contracts are defined.
- Backend-capable generated apps are out of scope for the current static app-bundle path.
- Slack/Gmail credential style (user tokens versus a full OAuth application) requires an explicit
  product decision after the receiver threat model is reviewed.
- Stronger isolation such as WASM may supplement Docker later; it does not justify weakening the
  current sandbox.

## Definition of done

A task is complete only when:

- its observable behavior and failure modes match `ARCHITECTURE.md` and the acceptance criteria;
- security checks live at the actual boundary, with abuse-case regression tests;
- focused tests pass, the full backend suite passes, and the production UI build succeeds;
- runtime/manual verification is performed when tests cannot prove the behavior;
- documentation links remain valid, `TODO.md` is reconciled, and a plain-language DEVLOG entry is
  appended;
- the change is reviewable, contains no secrets/build output, and is committed and pushed.
