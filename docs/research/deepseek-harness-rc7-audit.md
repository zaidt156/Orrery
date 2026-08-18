# DeepSeek Harness rc.7 audit for Orrery

This is the source audit behind [ADR-005](../decisions/005-coding-harness-capabilities.md). It is
evidence, not a second Orrery roadmap. Delivery order remains in [`PLAN.md`](../../PLAN.md), and
unfinished work remains in [`TODO.md`](../../TODO.md).

## Audit identity and honesty boundary

- Upstream: [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)
- Revision: [`99f6f02fecdb7dff40c3fbc9470f5907c29f74ca`](https://github.com/deepseek-ai/deepseek-harness/tree/99f6f02fecdb7dff40c3fbc9470f5907c29f74ca)
- Upstream tag at that revision: `dsh-v0.1.0-rc.7`
- Audit date: 18 August 2026
- License: MIT

Every tracked path was enumerated from the pinned checkout. The review then followed all governing
`AGENTS.md` files, English package contracts, bundle/profile composition, behavior-bearing source,
tests around the important invariants, generated persistence/tool/config catalogs, application
entry points, examples, scripts, native/Python adapters, and product UI packages.

This was a comprehensive repository audit, not a claim that 7,466 files were each read line by
line. Translations, generated catalogs, snapshots, fixtures, lockfiles, and archived design notes
were inventoried and used as corroboration; they were not miscounted as independent runtime
implementations. The `.agents` tree is mostly design history, while `packages`, `apps`, `native`,
and `python` contain the runtime.

## Repository inventory

The pinned revision contains **7,466 tracked files**.

| Area | Files | What it contains |
|---|---:|---|
| `packages/` | 3,755 | 49 capability groups, 219 package roots plus 7 fixture manifests, 1,439 files under `src/`, and 994 test-like paths |
| `.agents/` | 2,105 | 1,544 implemented notes, 428 archived notes, 75 proposals, and 33 rejected notes, plus indexes |
| `examples/` | 608 | Alternative compositions, fixtures, replay cases, and snapshots; examples are not shipped defaults |
| `docs/` | 327 | Architecture, lifecycle, tool, persistence, configuration, and defensive contracts |
| `apps/` | 273 | CLI and Web entry points; most Web files are tests, fixtures, or snapshots |
| `scripts/` | 163 | Build, catalog, release, test, and repository-quality automation |
| `vendor/` | 74 | Locally hardened Cordis loader, effect lifecycle, HMR, grouping, and timer code |
| `native/` | 51 | Platform launch/sandbox helpers |
| `python/` | 33 | Python SDK and packaged runtime adapter |
| `.github/` | 27 | CI, issue, and repository automation |
| `website/`, `assets/`, root files | 50 | Marketing site, assets, root manifests, policy, and build configuration |

There are 301 English `README.md` contracts. The generated catalogs independently describe 105
configured package entries, 52 model tool-schema sections, and 24 persisted event families.

### Package-group ledger

The source/test counts below provide a reproducible coverage map: Source counts TypeScript/
JavaScript files under `src/`; Tests counts filenames containing `.test.` or `.spec.`. “Disposition”
is the Orrery decision, not a claim that every package is enabled by Harness's default Web profile.

| Group | Packages | Source | Tests | Role | Orrery disposition |
|---|---:|---:|---:|---|---|
| `acp` | 1 | 4 | 8 | Editor automation protocol | Defer; an Orrery SDK should have stronger prompt correlation and cancellation |
| `api` | 2 | 10 | 3 | Gateway and remotes | Adapt typed contracts, keep Orrery HTTP/SSE authentication |
| `attachment` | 2 | 9 | 4 | Validated content-addressed attachments | Adopt immutable digests plus Orrery authorization and garbage collection |
| `boot` | 2 | 5 | 7 | App/profile boot | Borrow last-good transactional reload, not the Cordis loader |
| `bundle` | 3 | 8 | 6 | Base, headless, and Web composition | Use only to identify shipped defaults |
| `client` | 39 | 504 | 241 | Conversation, trajectory, workspace, tool, plan, goal, jobs, and settings UI | Adapt the strongest coding-console interactions incrementally |
| `code-runtime` | 2 | 10 | 7 | TypeScript worker-thread Code Mode | Reject host runtime; reconsider only inside Orrery's offline container |
| `compaction` | 4 | 18 | 12 | Summary checkpoints and tool-result pruning | Adopt after exact durable request/result events |
| `context` | 4 | 20 | 6 | Instructions, session references, time, tmux | Adapt sourced/bounded context; skip tmux-specific behavior |
| `core` | 8 | 44 | 58 | Agent, session, loop, prompt, tools, and scope | Primary source for event and tool-lifecycle contracts |
| `credentials` | 2 | 5 | 6 | Credential references and YAML provider | Keep references; reject plaintext YAML and retain OS keychain |
| `e2b` | 3 | 11 | 4 | Experimental remote sandbox | Defer; separate threat model required |
| `examples` | 3 | 10 | 3 | Protocol/spine demos | Reference only |
| `extensions` | 4 | 44 | 14 | Dynamic Cordis/self-modifying extensions | Reject model-authored host/browser code |
| `feedback` | 2 | 6 | 5 | Command and message feedback | Low priority; explicit consent required for any external submission |
| `fs` | 7 | 35 | 20 | Local FS service, sandbox fence, observation policy, read/search/edit tools | Adopt as explicit project-scoped capabilities with stronger containment |
| `goal` | 4 | 16 | 7 | Event-sourced objective and continuation rounds | Adapt only after durable events; do not replace Agent goals/schedules |
| `guard` | 2 | 4 | 2 | Timeouts and repeated-call reminder | Adopt structured deadlines and bounded repeat detection |
| `hooks` | 3 | 15 | 18 | Claude/Codex shell-hook compatibility | Keep Orrery's internal deny-only hooks; external shell hooks deferred |
| `host` | 8 | 65 | 33 | Web server, static UI, proxy, directory picker, inventory | Borrow safe picker ideas; retain Orrery's authenticated loopback boundary |
| `identity` | 1 | 2 | 2 | Stable anonymous identifier | Reject automatic correlation identifiers |
| `interaction` | 5 | 16 | 9 | Commands, permissions, questions, approvals | Adapt durable pending interaction and ask-user flow |
| `jobs` | 3 | 8 | 5 | Owner-scoped process-local jobs | Rebuild durably on Orrery's worker/store |
| `llm` | 5 | 46 | 34 | Provider interface, retries, DeepSeek adapter, token meter | Adapt exact request metering/retry events into existing provider layer |
| `lsp` | 3 | 17 | 12 | Definition, references, implementation, hover | Adopt read-only inside the offline project container |
| `mcp` | 1 | 5 | 4 | MCP client | Orrery already has approved stdio MCP; improve rather than replace |
| `plan` | 1 | 4 | 4 | Logged plan-review mode | Adopt as soft collaboration state, never as authorization |
| `preset` | 2 | 11 | 9 | Agent presets and persona | Build typed, immutable Orrery AgentConfig templates |
| `runtime-diagnostics` | 1 | 2 | 1 | Invariant checks | Adopt request reconstruction and lifecycle assertions |
| `sandbox` | 4 | 22 | 21 | Platform filesystem confinement | Retain stronger offline Docker boundary; report enforcement honestly |
| `schedule` | 1 | 8 | 7 | Session-local reminders | Do not replace Orrery's durable cron/worker scheduler |
| `sdk` | 3 | 13 | 6 | JSON-RPC client/protocol/server | Useful later, but fix correlation/cancel/resume gaps in Orrery's design |
| `session` | 13 | 45 | 27 | Persistence, projections, titles, stats, telemetry | Adapt append-only events/projections; keep PostgreSQL |
| `session-query` | 4 | 30 | 14 | Search, read, trace, and export | Adopt owner-scoped search/export after the event foundation |
| `settings` | 2 | 6 | 8 | Namespaced schema settings and file provider | Borrow revisions/provenance; keep fail-closed secret redaction/keychain |
| `shell` | 9 | 27 | 17 | One-shot and persistent Bash/PowerShell | Improve Docker one-shot commands first; terminal much later |
| `skill` | 4 | 8 | 5 | Layered skill catalog and loader | Improve Orrery with last-good/incomplete snapshots and progressive loading |
| `spill` | 3 | 9 | 3 | Head/tail preview plus full-output file | Adopt through authorized Orrery artifacts, never host paths |
| `storage` | 4 | 20 | 6 | JSON/SQLite typed storage | Keep PostgreSQL; borrow revision/CAS semantics |
| `subagent` | 11 | 46 | 28 | One-shot/continuable children and external adapters | Adopt bounded one-shot children after tool/event foundations |
| `subprocess` | 2 | 8 | 6 | Argv process execution and cancellation | Adapt structured outcomes and tree termination inside containers |
| `terminal` | 3 | 11 | 9 | Persistent PTY lifecycle | Optional, container-only, and late |
| `test-support` | 6 | 27 | 15 | Agent/replay/client/model fixtures | Borrow model-visible golden fixtures and replay scenarios |
| `todo` | 1 | 4 | 5 | Whole-list durable todo snapshots | Adopt after the shared event home exists |
| `typert` | 11 | 27 | 12 | Typed plugin/config protocol and loader | Borrow generated-contract discipline, not the runtime framework |
| `util` | 7 | 14 | 7 | Atomic write, timeout, paths, retention | Adapt individual hardened primitives |
| `web` | 6 | 24 | 11 | Search/fetch providers | Keep Orrery's SSRF/DNS-rebinding netguard; adapt provider-neutral results |
| `workflow` | 4 | 19 | 12 | JavaScript agent orchestration and Ralph loop | Keep Orrery's declarative DAG; add bounded fan-out later |
| `workspace` | 1 | 6 | 2 | Canonical filesystem workspaces and session grouping | Add an explicit coding root beside, not inside, Project knowledge scope |

## How the shipped product works

DeepSeek Harness is a plugin-composed coding-agent runtime. Cordis profiles and ordered patches
mount services and consumers. The default workspace is the invoking current directory. The base
bundle defines the host services and default agent-plane rows. Web then disables/re-homes many
prompt, tool, and delegation rows into the selected per-session preset before adding browser modules
and UI. `standard` is the Web default; `code`, `minimal`, and `cordis` are selectable alternatives.

The append-only Session log is intended to be the authority for model-visible behavior. A normal
turn is:

1. start the turn and durably claim queued input;
2. assemble and log the exact request header, contexts, messages, and tool schemas;
3. stream and record model chunks;
4. commit the assistant message and ordered tool calls;
5. pass each call through policy, approval, guards, wrappers, execution, result validation, and
   presentation;
6. persist immutable results before making them model-visible;
7. continue or close the step and turn with explicit stopping events.

The conversation/tool/plan/goal/todo/trajectory surface is largely projected from the Session log.
The client combines it with other domain and live projections for pending interactions, subagents,
jobs, workflows, workspaces, and settings. Pending questions, in particular, are live provider state
rather than their own durable request/answer stream. Workspace registration, ordering, grouping,
and archive state come from the separate storage domain. JSONL is the shipped session persistence;
SQLite alternatives exist. Orrery should copy the explicit-authority/projection discipline, not
either storage backend.

## Architectural seams and their file families

### Cordis lifecycle and configuration

`vendor/cordis/src/fiber.ts` and the vendored loader/include/HMR packages are not passive third-party
copies; Harness relies on local hardening. Plugin setup receives an effect owner before it can
register behavior. Partial setup rolls back, unloading rejects new effects, asynchronous cleanup is
awaited, child scopes unwind deterministically, and observer cleanup failures are contained.

`vendor/loader/src/config`, `vendor/include/src/index.ts`, and `packages/boot/app-boot` apply bundle,
profile, home, and CLI patches through the same stable-ID composition algorithm used by config dump.
Updates are serialized. Failed imports or refreshes retain/restore the last usable tree. A running
agent stays pinned to its mounted preset generation, and children bind to that generation rather
than silently remounting a changed name.

Portable lesson: capability setup/mutation/teardown should be transactional and quiescent. Do not
port Cordis or give mutable configuration control of Orrery's security floor.

### Session authority and crash repair

`packages/core/session/src` assigns monotonic sequence numbers and admits only lossless JSON values.
It rejects cycles, sparse arrays, exotic prototypes, functions, symbols, `-0`, and other values that
cannot round-trip. The model surface is an ordered projection containing only user messages,
assistant messages, and tool results; replacement events cite what they shadow. Tool-result
replacement may change only presented content, preserving the canonical fact.

Observers run after append commit and cannot veto history; re-entrant append is rejected. Resume
validates its seed. Crash repair distinguishes a tool that never started from one whose external
outcome is unknown. Forks require a balanced completed boundary. `deriveMessages()` rebuilds from
the surface rather than live process memory.

Portable lesson: Orrery needs typed durable evidence and explicit unknown-outcome repair, while
keeping PostgreSQL and its existing product tables.

### Agent and loop lifecycle

`packages/core/agent` and `packages/core/agent-loop` publish an agent only after setup and durability
work succeed; teardown cancels and drains its machine before removing scopes/session attachment.
Inbox changes are durable before memory changes. `followup` targets the next turn and wakes it,
`steer` targets the next model step and wakes it, while `inject` targets the next step without a
wake. Idle, maintenance, and running phases prevent scheduling work from racing a turn.

Each step records its start, claimed user input, exact request header/contexts, raw model chunks,
assistant completion anchor, tool calls/results, stopping reason, step end, and turn end. A runtime
invariant reconstructs the request from the log and compares it with the frozen request actually
sent. Ordered calls may overlap only in consecutive explicitly parallel-safe groups; exclusive calls
form barriers. Cancellation records synthetic results for calls skipped before dispatch and drains
calls that already started.

Portable lesson: this exact-request invariant is Orrery's first slice. The existing browser Activity
panel is useful visibility, but it observes ephemeral SSE and cannot establish the invariant.

### Model, prompt, and context layers

`packages/llm/*` resolves an exact adapter registration before I/O, rejects unsupported reasoning
effort before network access, captures provider defaults once, turns transport failures into stable
terminal chunks, and logs retries through a separate around-layer. Token accounting attaches
provider usage only when it matches the canonical request envelope; otherwise it uses a deterministic
estimate.

`packages/core/system-prompt` gives prompt sections explicit names/order/scope and fails unresolved
template variables. `packages/context/agent-instructions` loads applicable `AGENTS.md`/`CLAUDE.md`
files broad-to-specific under a 65,536-byte budget, deduplicates by content hash, preserves the most
specific instructions when capped, and refreshes only after successful filesystem activity.
Session references import at most three bounded, explicitly untrusted snapshots. Time context logs
the clock/time-zone provenance used for the step.

Portable lesson: snapshot what was actually sent, retain authority labels, and meter the complete
request. Orrery's current trusted/untrusted prompt separation remains the governing design.

### Compaction, goals, todo, plan, and interaction

`packages/compaction/*` serializes every compaction behind a durable start/end bracket. A successful
transaction writes summary metadata and one surface-replacement checkpoint. Balanced tool-call/
result pairs constrain cut positions; a recent tail is retained. The optional result pruner keeps
raw events while replacing only model-visible content with bounded head/marker/tail.

`packages/goal/*` maintains one revisioned objective with compare-and-set updates and explicit
active/paused/blocked/complete phases. Its continuation-round authority is separate from direct
human authority. This is not a cost/token/time budget and should not replace Orrery's Agent goal and
scheduler.

`packages/todo/tool-todo` records whole-list last-write-wins snapshots. Plan mode is logged soft
collaboration state, and leaving it requires review of the exact plan. Approvals have paired durable
asked/decided events and fail-closed one-shot decisions. User questions use a separate live provider
seam with no independent request/answer audit stream; the answer later appears as an ordinary tool
result. Slash commands are plugin-owned UI operations and their result text stays outside model
history.

Portable lesson: result pruning precedes summarization. Orrery should give todo/question/plan a
shared durable projection rather than copy the question seam's process-lifetime limitation; none of
it grants tool authority.

### Web product and coding-console UX

`apps/web` is a small Vite boot shell. `packages/client/runtime` is the React-free projection layer,
`packages/client/web-react` binds it to React, and the many `ui-*` packages fill product slots.
Unary operations use HTTP; two downlink WebSockets carry events. Reconnect starts a new generation.
Host/Origin/Fetch-Metadata checks are explicitly a reachability fence, not authentication, so this
transport must not replace Orrery's launch-code/session-cookie boundary.

The strongest user-facing pieces are:

- streaming conversation with separate thinking, grouped step/tool summaries, compaction/retry/
  max-token notices, queue/steer controls, context/token/cache/TTFT stats, and a produced-file rail;
- pending approval, user question, or plan review taking over the composer;
- extensible intent cards for terminal, read, diff, search, and web operations;
- a virtualized range-filterable event trajectory/inspector;
- canonical workspace/session grouping, archive, ordering, directory selection, search snippets,
  completed-turn fork, and descendant activity indicators;
- hierarchical subagent activity with duration/tokens, navigation, interrupt, and continue;
- Goal/Todo/Plan docks, model/reasoning selection, slash commands, images, feedback, skill and
  permission controls;
- observational jobs/workflow views and produced-file open/show-folder affordances.

Known gaps matter: sent user messages cannot be edited, some detail/paging paths are stubs,
approvals expose allow-once/reject rather than a full rule manager, jobs UI cannot cancel/show
output, workflow UI lacks script/error/log/control views, and no search result deep-links to its
matching event.

Portable lesson: adapt the interaction patterns over Orrery's authenticated HTTP/SSE and durable
events; do not transplant the client runtime wholesale.

### Persistence, workspace, settings, and protocols

The shipped session medium is per-session JSONL. Writes serialize/batch/flush and synthesize crash
closers with unknown outcomes, but there is no retention/delete policy and session listing is
unpaginated. Optional SQLite and query packages exist; shipped Web deliberately uses an in-memory
query index that never opens, so content FTS is not a default feature.

Non-session storage has JSON whole-file atomic rewrite and SQLite per-record providers. Both reject
schema version mismatch without migration and have limited multi-process conflict handling.
Workspace registration canonicalizes with `realpath`, durably orders workspaces/sessions, archives
without deleting logs/files, and uses pending-mutation markers for crash recovery.

Settings resolve schema defaults, composition base, then user section, with revision/CAS conflict
handling and serialized namespace writes. The YAML provider preserves comments and atomically
replaces owner-only files. Its documentation admits secret redaction is not fail-closed through all
schema unions/intersections/transforms and that defaults can leak; Orrery must keep keychain secrets
and stricter redaction.

ACP is a fresh-session committed-answer automation adapter, not the full Web experience. The SDK's
high-level `run()` waits until the whole agent is idle, so its last answer is interval-scoped rather
than causally assigned to one prompt. It lacks robust mid-turn cancel/session close/version
negotiation, and packaged runtimes omit Windows. Any Orrery SDK should use stable request IDs and a
prompt-correlated terminal outcome from day one.

### Test and release discipline

Harness uses strict TypeScript gates, per-file source coverage expectations, generated configuration/
tool/persistence catalogs, replay fixtures, browser snapshots, loader smoke tests, and built-entry
checks. The useful transfer is model-visible golden scenarios and generated-contract drift gates,
not blindly copying a 100-percent-per-file target into Orrery. External effects must be asserted at
the boundary rather than accepted from an agent's self-report.

## The most important reusable contract: tool execution

Harness separates the canonical structured tool value from the text rendered to the model and the
metadata replayed in the UI. Its full pipeline is:

1. persist the raw model tool call before policy or execution;
2. validate and canonicalize immutable arguments;
3. collapse execution mode and policy to the strictest result;
4. run pre-execution policy;
5. resolve an exact approval, with absence meaning deny;
6. apply monotonic guards;
7. enter timeout/retry/metrics wrappers;
8. execute the provider;
9. run post-execution policy;
10. validate and normalize the canonical result;
11. finalize bounded model/UI presentation;
12. notify contained observers and persist the result before another model request completes.

Calls retain IDs and order. Only consecutive calls explicitly marked parallel-safe can overlap;
exclusive calls are barriers. Cancellation before dispatch is distinguishable from cancellation
after a body started, and started bodies drain before lifecycle completion. Code Mode subcalls
re-enter the same registry instead of bypassing policy.

Orrery already has the more important security floor: scope allow-lists, feature gates, Agent grant
actions/resources, Pydantic validation, risk classification, digest-bound approval, deny-only hooks,
and sanitized errors in `backend/tools/registry.py`. It lacks the durable cross-product call context
plus lifecycle events, around/post phases, canonical-versus-presented result split, output
validation, exact cancellation/unknown-outcome facts, and contained observation.

## Coding capabilities worth adapting

### Project filesystem

Harness provides canonical path identities, bounded reads, direct-argv ripgrep, atomic writes,
mode/line-ending preservation, and observed-version editing. Its useful rule is “read before
replace”: an unseen path may be created, while an existing observed file may be replaced only at
the observed version. Literal replacement fails on stale content or ambiguous matches.

For Orrery this becomes an explicit coding-root capability attached to a Project. It must reject
path traversal and symlink escape, never infer the user's home or repository root, and never turn a
Project's document collection into ambient filesystem authority. Creation/rebinding is local-host/
admin-only through a trusted chooser; team members use only pre-approved roots. Every operation
re-resolves filesystem identity and requires the exact root/read-or-write grant. A selected root is
context, not authorization.

### Output retention

Harness can replace oversized plain text with a bounded head/tail preview and a locator for the
complete result. Its local locator lacks authorization, deletion, and garbage collection. Orrery
should instead define the canonical durable result as the validated, security-filtered value; raw
unsanitized transport/provider output is non-authoritative and discarded. A hard-capped expanded
result may be retained as an owner/run-scoped artifact with MIME type, byte count, digest, quota,
and an authorized retrieval tool. The exact bounded presentation the model saw stays with its event.
Expanded-result retention must either match the run/session lifetime or advertise a bounded replay
horizon and leave a digest/tombstone after garbage collection. Host paths must never be model-visible.

### Processes, jobs, and terminal

Good semantics include explicit argv, scrubbed environment, independent stdout/stderr loss flags,
timeout/abort/exit/signal facts, process-tree termination, admission before side effects, and drain
on disposal. Orrery should keep execution inside Docker and make background jobs durable rather
than process-local. Coding-root command mounts stay read-only by default. A writable formatter/test
needs a higher-risk grant and overlay/diff/approval flow whose changes are applied through guarded
atomic edits; a direct writable mount would bypass the editor invariant. A persistent terminal is
materially riskier and belongs after reliable one-shot commands and jobs; if built, it stays inside
a disposable container with exact owner/session scope.

### LSP

Harness exposes only definition, references, implementation, and hover. It bounds protocol sizes,
routes by extension, serializes per workspace, restarts poisoned servers, and refuses server edit or
command requests. Orrery should run pinned preinstalled language servers as non-root inside its
resource-capped offline project container, with writable scratch but an always-read-only workspace,
no workspace plugins where configurable, no secrets/downloads/network, descendant cleanup, no
`workspace/applyEdit`, no arbitrary JSON-RPC, and no paths outside the coding root.

### Subagents

Harness has foreground/background and continuable children, lineage, follow-ups, interrupts,
cancellation, depth limits, and several in-process/external drivers. Orrery's first version should
be smaller: one-shot children only, a strict parent-grant intersection, fixed no-approval behavior,
hard depth/sibling/concurrency/total budgets, durable lineage, and parent cancellation that drains
all descendants. No approval means fail closed: an approval-required child action is denied, never
auto-approved or promoted, and parent preapproval never widens the exact inherited root/tool/resource
ceiling. Partial output is evidence, never success.

### Collaboration state and compaction

Whole-list todo snapshots, generic user questions, logged plan review, exact request metering,
tool-result pruning, and summary checkpoints are useful. They all need a shared durable event home.
Compaction must preserve raw events and replace only the model-visible projection with provenance;
it cannot safely summarize today's clipped Agent step detail.

## Shipped default versus optional or experimental

Do not describe every package as a default feature:

- Web defaults each session to the `standard` preset with native tool presentation. `code` is a
  shipped opt-in Code Mode preset; `cordis` is a shipped opt-in conversational preset/plugin-authoring
  surface; `minimal` omits plan, goals, compaction, todo, ask-user, delegation, and web search.
  `DSH_TOOLS_MODE` is also a temporary process-wide override. Headless uses the base composition
  directly rather than the Web preset roster.
- The TypeScript Code Mode worker is explicitly not a security boundary.
- The shipped base enables best-effort plain-text spill at 50,000 UTF-8 bytes. It skips `read` and
  nested/mixed-content results; omission disables it in another composition, and its host-path
  locator has no Orrery-grade authorization, retention, or garbage collection.
- Schedule is an example composition, not in base/Web/headless. It is a live-session reminder, not
  a cron automation engine.
- The HTTP fetch provider/tool is not mounted. The DeepSeek search service/provider is mounted;
  model-facing web search comes through presets such as `standard`, `code`, and `cordis` (not
  `minimal`) and requires a usable DeepSeek credential/route.
- Session full-text query exists, but shipped Web opens its SQLite query index at `never` and keeps
  it in memory; the model session-query tool is not mounted.
- Telemetry is disabled by default, but when enabled can export raw Session records.
- E2B is an experimental proof of concept without robust workspace synchronization.
- Dynamic Cordis/self-modification tools exist only when mounted and are equivalent to granting
  model-authored code access to live host services.
- Codex and Claude Code adapters exist but are not part of the base shipped composition.
- ACP and the SDK are narrower automation surfaces; they do not reproduce the full Web lifecycle.
- The Python SDK has no Python-native/default Code Mode implementation, although its packaged Node
  executable closure includes the TypeScript Code Runtime packages for custom composition. Python
  runtime wheels cover Linux x64/arm64 and macOS arm64, not Windows; explicit Node/TypeScript launch
  is a separate path.
- Slash commands and message feedback are Web host/UI features, not shared headless/ACP defaults.

## What Orrery already has

Do not rebuild these:

- one Python modular monolith and a React client;
- authenticated loopback HTTP/SSE with launch-code-to-cookie claim;
- PostgreSQL application state and durable worker queue;
- OS-keychain secrets;
- shared tool registry with scope, grants, resources, validation, risk, approvals, and deny-only
  policy hooks;
- offline, resource-capped Docker Python/shell plus generated-file validation over isolated scratch/
  input/output mounts, with no selected checkout or coding-root access;
- branchable Chat message versions;
- immutable Agent versions, run config snapshots, step trace, budgets, cancellation, approvals,
  replay/fork, cron scheduling, deduplication, concurrency policy, and orphan recovery;
- declarative Automation DAGs, a registered node catalog, durable queued runs/steps, API, and live
  read/run UI;
- approved stdio MCP, Skills, Projects/RAG, Dashboards, and guarded network access;
- layered configuration and intentionally narrow local plugin mounting from ADR-004.

## Orrery gaps exposed by the comparison

1. Agent replay is shortened, not exact: `AgentRunStep.detail` is clipped, while system prompt,
   request messages, model defaults, and tool catalog are recomputed rather than captured as sent.
2. Chat's dynamic prompt/context/tool calls/results are not an authoritative durable input log, and
   detached Chat scheduling remains process-local.
3. Automations has durable run steps, but not the same call/result vocabulary as Chat or Agents.
4. Tool results are clipped before the model and the complete output has no authorized retrieval
   path.
5. Projects are knowledge containers, not explicitly authorized local checkout roots.
6. Orrery has no first-party read/glob/grep/versioned-edit tools over a coding workspace.
7. Sandbox Python/shell does not mount an explicitly selected user workspace.
8. There is no read-only LSP service, durable coding job control, or container terminal.
9. There is no reusable todo/plan/question projection for coding sessions.
10. There are no parent/child agent runs with inherited budget/grant ceilings.
11. There is no supported local SDK/JSON event mode for coding automation.

## Explicit non-adoptions

The following would make Orrery worse or violate its security contract:

- embedding Cordis or operating a second TypeScript backend;
- making authorization, approval, scope, validation, secrets, or audit replaceable plugins;
- a `danger-full-access` preset that disables approvals;
- ambient access to the invoking current directory, home directory, or host environment;
- plaintext `.credentials.yaml`, secret-bearing `.env`, or broad child-process environments;
- unauthenticated WebSocket/browser trust as a replacement for Orrery's session boundary;
- host worker-thread Code Mode, host PTYs, or model-authored self-modifying extensions;
- Harness's fetcher, which does not provide Orrery's SSRF/DNS-rebinding protection;
- raw telemetry or a stable anonymous identifier without explicit consent;
- E2B as a default sandbox;
- model-authored JavaScript workflows in the host process or Ralph-style self-asserted completion;
- JSONL/SQLite as a replacement for PostgreSQL durability;
- arbitrary language-server downloads or edit/command requests.

## Recommended dependency order

The safe order is:

`durable execution events + repeat guard -> retained results -> explicit coding root -> read/search
-> guarded edit -> read-only workspace sandbox commands -> metering/compaction -> questions/todo/plan
-> durable jobs -> LSP -> bounded subagents -> optional container Code Mode/terminal -> SDK and
session search/export`

The concrete slices and acceptance gates are in ADR-005 and the canonical plan. The first slice is
deliberately evidence-only: capture the exact tool lifecycle and request/result payloads without
adding any new filesystem or process authority.

## Security acceptance suite for later slices

At minimum, implementation must prove:

- path traversal and symlink escape are rejected;
- team members cannot attach/rebind host roots, and replaced filesystem identity is detected on use;
- two concurrent versioned edits have at most one winner;
- ambiguous literal replacement fails, and CRLF/mode are preserved;
- search arguments never pass through shell interpolation;
- previews state byte loss and point only to authorized artifact IDs;
- per-result/run/owner quotas reject before artifact writes and cleanup cannot silently break the
  declared replay horizon;
- admission failures create no process/job side effects;
- crash recovery distinguishes never-dispatched from body-started/unknown external outcome;
- timeout and cancellation kill descendants and wait for drain;
- coding commands cannot obtain a direct writable checkout mount; approved overlay changes re-enter
  root grants, diff review, observed versions, and atomic application;
- language servers cannot edit, execute commands, use network, or leave the workspace;
- a child cannot expand parent grants, budget, tool set, or request approval;
- parent cancellation drains descendants and partial child output is never reported as success;
- any Code Mode subcall re-enters scope, grant, approval, audit, and result bounds;
- keychain/provider/connection secrets are never injected into model-bound events or ambient process
  environments; sanitized canonical results and quarantined raw output follow explicit owner access,
  quota, retention, and presentation-redaction rules;
- artifact/session/export retrieval enforces owner and run authorization;
- model-visible requests and results can be reconstructed exactly from durable records.
