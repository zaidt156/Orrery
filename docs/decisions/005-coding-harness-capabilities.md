# ADR-005: Grow Orrery's coding harness through explicit capabilities

## Status

Proposed - implementation requires user review of this decision and slice order.

## Date

2026-08-18

## Context

The user asked for a complete review of DeepSeek Harness and a bit-by-bit path to make Orrery a
better coding environment. The pinned source audit is
[`deepseek-harness-rc7-audit.md`](../research/deepseek-harness-rc7-audit.md).

DeepSeek Harness's strongest property is not Cordis or any individual coding tool. It is the
discipline connecting its append-only Session log, exact model input, guarded tool lifecycle,
replayable projections, workspace capabilities, output retention, and child-agent lineage.

Orrery already has a stronger fit for its product and threat model: one Python backend, PostgreSQL,
OS-keychain secrets, authenticated loopback HTTP/SSE, a central tool/grant/approval boundary,
offline Docker execution, durable Agent/Automation runs, and broader knowledge/data/dashboard
features. Porting Harness or running it beside Orrery would duplicate authority and weaken those
boundaries.

ADR-004 already adopted four composability ideas: deny-only hooks, replay/fork over durable Agent
steps, layered configuration, and narrow local plugin mounting. This decision covers the larger
coding-capability roadmap exposed by the full rc.7 audit.

## Decision

Borrow **capabilities and invariants**, not the DeepSeek Harness runtime.

Orrery will remain a Python/React modular monolith. Every new coding capability will enter through
the existing tool registry and inherit its non-pluggable scope, feature gate, grant, validation,
approval, ownership, and audit checks. PostgreSQL remains the durable authority, the OS keychain
remains the secret authority, and untrusted code remains inside the offline Docker boundary.

The implementation is split into independently useful, reviewable slices. A later slice cannot
land by bypassing an earlier invariant.

### Slice 1 - exact execution evidence

Define one immutable call context plus typed append-only lifecycle events shared by Chat, Agents,
and Automations. The context carries owner, product/run/session identity, turn/call/parent IDs, tool
key, validated safe arguments, and grant/config snapshot references. Per-stream monotonic sequence
numbers have a database uniqueness constraint. Events carry admission, body-started, phase,
cancellation/timeout, result, and terminal-outcome facts; changing lifecycle state never mutates the
call context.

Capture the canonical post-redaction provider request envelope actually supplied to the adapter:
provider/model/effort/default markers, system prompt, model messages, and tool catalog. Persist the
exact bounded result presentation the model saw plus loss metadata. Slice 1 does not claim to retain
complete expanded output; Slice 2 adds that. System-managed credentials remain stable references and
are resolved below the model-bound envelope; transport auth headers are excluded and audited only by
safe provenance/digest. Sensitive text a user intentionally sends is necessarily part of the
owner-private request record.

“Append-only” is a logical run invariant, not immortal storage. Slice 1 keeps exact payloads owner-
isolated inside the existing PostgreSQL trust domain and creates no new plaintext filesystem copy.
Retention/export/delete follows the parent conversation/run and removes the event payloads with it;
large expanded tool output waits for Slice 2's explicit protected-artifact policy. Existing
`Message`, `AgentRunStep`, and `WorkflowRunStep` APIs remain projections during migration.

Acceptance:

- an invariant reconstructs the canonical structured request and proves structural equality or a
  canonical-serialization digest match with the frozen adapter request (not HTTP wire bytes);
- tool calls and results are logged before becoming model-visible;
- call-admitted and body-started events precede side effects; recovery distinguishes never
  dispatched from started/unknown outcome, and unknown external effects are never presented as
  retry-safe;
- unknown tools, validation failures, denials, cancellations, timeouts, and exceptions have stable
  structured outcomes;
- deterministic repeated identical calls trigger a bounded model-visible loop warning before any
  new filesystem/process authority is introduced;
- retries and forks retain exact lineage;
- no new tool or filesystem authority is added in this slice.

### Slice 2 - full result retention with bounded presentation

Separate the validated, security-filtered canonical result from the text shown to the model/UI; raw
unsanitized provider/transport output is non-authoritative and discarded. Retain hard-capped expanded
results in owner/run-scoped Orrery artifacts and return a bounded head/tail preview with byte count,
digest, MIME type, loss facts, and opaque artifact ID. Enforce per-result, per-run, and per-owner
quotas before writing. Retrieval is an authorized tool/API call; the model never receives a host
path.

The exact presentation the model saw remains with the parent event. Expanded canonical artifacts
either live as long as the run/session or the product declares a bounded replay horizon and leaves a
digest/tombstone after garbage collection. Deletion is atomic with the owning record. Acceptance
includes owner isolation, quarantine/presentation redaction, retrieval caps, quotas, cleanup, and
honest replay behavior after retention ends.

### Slice 3 - explicit coding workspaces

Add a coding-root entity that a user explicitly attaches to a Project. Store canonical identity,
display name, ownership, permission (`read-only` or `workspace-write`), and revision. Do not treat a
Project's RAG files as filesystem authority, infer the current directory, or offer unrestricted
home/host access.

Creating/rebinding a root is local-host/admin-only through a trusted directory chooser; team members
may use only pre-approved roots. Re-resolve canonical filesystem identity on every use so a replaced
path/symlink cannot widen authority. The UI must show exactly which root and permission a coding
session is using. `danger-full-access` is not an Orrery preset.

### Slice 4 - read, glob, and grep

Add bounded project-scoped file reading, directory/glob discovery, and direct-argv ripgrep. Enforce
canonical containment, the exact root-scoped read grant, and symlink policy on every call. Results
enter the common event/output path.

### Slice 5 - observed-state editing

Add create/write and literal edit only after read/search is stable. Existing files require an
observed digest/version. Writes use private staging and atomic replacement, preserve mode and line
endings, fail on stale content or ambiguous matches, and produce a diff preview. Every mutation
requires an exact root-scoped write grant. Before sharing the tool across Chat/Agents/Automations,
define Chat's explicit local-write approval policy; current risk labels alone do not authorize it,
and selecting a root in the UI is not a grant.

### Slice 6 - workspace-mounted sandbox commands

Allow Python/shell/test/formatter commands to mount only the selected coding root into the existing
offline Docker sandbox, **read-only by default**. A writable command is a separate higher-risk grant:
it must run against an overlay, capture a complete bounded diff, and require the exact local-write
policy/approval before applying changes atomically through the guarded file service. Direct writable
checkout mounts must not bypass observed-version editing. Add explicit argv where possible,
independent timeout/abort/exit/signal facts, process-tree cancellation, and drain before completion.
Do not leak ambient host environment or secrets.

### Slice 7 - replay-safe metering and context reduction

Add exact request capture plus provenance-labelled provider usage when it matches that request, or a
clearly labelled deterministic token estimate otherwise. Then add model-free tool-result pruning and
transactional summary checkpoints. Raw events/results remain intact; only the model-visible
projection is compacted, with source provenance and balanced tool call/result cuts.

### Slice 8 - coding collaboration state

Add durable whole-list todo snapshots, a generic ask-user-question seam, and logged plan-review
state. A pending question/approval/review can take over the Chat composer. These are collaboration
features, never security controls.

### Slice 9 - durable jobs and optional terminal groundwork

Build owner/run-scoped background jobs on Orrery's durable worker/store with admission-before-side-
effect, bounded concurrency, output cursors, restart reconciliation, process-tree cancellation, and
SSE/polling UI. Do not autonomously wake a model in the first version.

A persistent terminal remains a later, optional container-only capability after job lifecycle and
cleanup are proven; it inherits the same read-only-root default and cannot bypass the overlay/
guarded-application rule.

### Slice 10 - read-only LSP

Expose definition, references, implementation, and hover only. Run pinned preinstalled servers in
the offline project container as non-root with resource caps, writable scratch only, and an always
read-only workspace mount regardless of the session's write permission. Disable workspace plugins
where configurable, provide no secrets/network, clean up descendants, bound protocol/document/result
sizes, and reject server edit, command, download, or out-of-root requests.

### Slice 11 - bounded one-shot subagents

Add one-shot child runs with durable parent/child lineage, fixed depth/sibling/concurrency/total
budgets, and an exact grant/tool/root/resource intersection with the parent. “No child approval
path” is fail-closed: a child action requiring approval is denied, never auto-approved or promoted to
the parent UI, and a parent's preapproval cannot widen the inherited ceiling. Record structured
terminal states and drain descendants on parent cancellation. Continuable children and external
adapters are later decisions.

### Slice 12 - optional orchestration and developer surfaces

Only after the prior slices are reliable, consider containerized Code Mode whose every binding
re-enters the registry, bounded Automation fan-out using Orrery's declarative DAG, session
search/export, and a Python-native local SDK/`orrery run --json` surface. The SDK must correlate
every prompt with its terminal outcome and support cancel/resume/fork/close and pending interactions.

## Invariants that override borrowed designs

- Hooks/plugins may deny, observe, or annotate; they never grant.
- A child may only reduce parent authority and budget.
- Model-visible means durably reconstructible.
- Canonical output and bounded presentation are different data.
- A locator is an authorized opaque ID, never a host path.
- Worker threads, path fences, and language servers are not isolation boundaries. Container/VM
  isolation counts only when its explicit hardening and enforcement are active and fail closed.
- Approval is bound to exact validated arguments and cannot be inferred from a preset.
- No hidden network, credential, workspace, telemetry, or self-modification authority.
- External effects require idempotency/claim semantics; a checkpoint does not imply exactly-once.

## Explicitly rejected

- Embedding Cordis, porting `dsh`, or adding a second TypeScript backend.
- Full component replaceability below Orrery's security floor.
- Host-side model-authored Code Mode or self-modifying extensions.
- Plaintext credential files or secret-bearing subprocess environments.
- Ambient current-directory/home access or a no-approval full-access preset.
- Harness's unauthenticated browser boundary, raw telemetry, stable anonymous identifier, and
  SSRF-incomplete fetcher.
- Replacing PostgreSQL/Procrastinate with JSONL, SQLite, or process-local jobs.
- Replacing Orrery Automations with session-local reminders or model-authored host JavaScript.
- E2B as the default sandbox, host PTYs, or arbitrary LSP JSON-RPC/downloads.

## Alternatives considered

### Port or embed DeepSeek Harness

Rejected. It duplicates the agent/tool/session authority, uses a TypeScript/Cordis runtime, is an
rc developer preview, and includes optional trust assumptions that contradict Orrery's security
contract.

### Add filesystem, terminal, LSP, and subagents immediately

Rejected. Without exact durable tool events and retained full results, these capabilities would be
hard to audit, replay, recover, compact, and safely compose. The dependency order is part of the
decision.

### Keep Orrery's current coding tools unchanged

Rejected. Offline Python/shell execution is safe and useful, but without an explicit workspace,
read/search/edit tools, retained output, semantic navigation, and bounded delegation it cannot act
as a serious repository coding harness.

## Consequences

- The first implementation slice improves correctness and replay without expanding authority.
- Coding power grows in small increments that each reuse the same enforcement path.
- Some attractive Harness features arrive later because durable evidence and safe ownership come
  first.
- Existing Chat/Agent/Automation records need projection/backfill compatibility while the common
  event vocabulary is introduced.
- Generated tool/event/settings catalogs and model-visible golden tests should become CI drift
  gates as each slice lands.
- This ADR remains Proposed until the user approves or revises the order; acceptance changes its
  status before Slice 1 code begins.

