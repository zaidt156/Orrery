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

Define one immutable execution context and append-only event envelope shared by Chat, Agents, and
Automations. At minimum it carries owner, product/run/session identity, monotonic sequence, turn and
call IDs, parent call, tool key, validated safe arguments, grant/config snapshot references,
timestamps, phase, cancellation/timeout facts, canonical result metadata, and bounded presentation.

Capture exact provider/model/effort/default markers, system prompt, model messages, and tool catalog
used for each model request. Existing `Message`, `AgentRunStep`, and `WorkflowRunStep` APIs remain
projections during migration. Canonical replay payloads are never clipped; secret-bearing values are
stored only as redacted metadata or keychain references.

Acceptance:

- an invariant reconstructs a request from durable records and byte-compares it to what was sent;
- tool calls and results are logged before becoming model-visible;
- unknown tools, validation failures, denials, cancellations, timeouts, and exceptions have stable
  structured outcomes;
- retries and forks retain exact lineage;
- no new tool or filesystem authority is added in this slice.

### Slice 2 - full result retention with bounded presentation

Separate canonical output from the text shown to the model/UI. Retain complete oversized output in
an owner/run-scoped Orrery artifact and return a bounded head/tail preview with byte count, digest,
MIME type, loss/truncation facts, artifact ID, and expiry. Retrieval is an authorized tool/API call;
the model never receives a host path.

Acceptance includes owner isolation, expiry/garbage collection, secret redaction, retrieval caps,
and replay from the retained canonical result.

### Slice 3 - explicit coding workspaces

Add a coding-root entity that a user explicitly attaches to a Project. Store canonical identity,
display name, ownership, permission (`read-only` or `workspace-write`), and revision. Do not treat a
Project's RAG files as filesystem authority, infer the current directory, or offer unrestricted
home/host access.

The UI must show exactly which root and permission a coding session is using. `danger-full-access`
is not an Orrery preset.

### Slice 4 - read, glob, and grep

Add bounded project-scoped file reading, directory/glob discovery, and direct-argv ripgrep. Enforce
canonical containment and symlink policy on every call. Results enter the common event/output path.

### Slice 5 - observed-state editing

Add create/write and literal edit only after read/search is stable. Existing files require an
observed digest/version. Writes use private staging and atomic replacement, preserve mode and line
endings, fail on stale content or ambiguous matches, and produce a diff preview. Registry risk and
approval remain authoritative.

### Slice 6 - workspace-mounted sandbox commands

Allow Python/shell/test/formatter commands to mount only the selected coding root into the existing
offline Docker sandbox, read-only or workspace-write according to the exact grant. Add explicit
argv where possible, independent timeout/abort/exit/signal facts, process-tree cancellation, and
drain before completion. Do not leak ambient host environment or secrets.

### Slice 7 - repetition guard and replay-safe context reduction

Add canonical repeated-call detection, exact request/token accounting, model-free tool-result
pruning, and then transactional summary checkpoints. Raw events/results remain intact; only the
model-visible projection is compacted, with source provenance and balanced tool call/result cuts.

### Slice 8 - coding collaboration state

Add durable whole-list todo snapshots, a generic ask-user-question seam, and logged plan-review
state. A pending question/approval/review can take over the Chat composer. These are collaboration
features, never security controls.

### Slice 9 - durable jobs and optional terminal groundwork

Build owner/run-scoped background jobs on Orrery's durable worker/store with admission-before-side-
effect, bounded concurrency, output cursors, restart reconciliation, process-tree cancellation, and
SSE/polling UI. Do not autonomously wake a model in the first version.

A persistent terminal remains a later, optional container-only capability after job lifecycle and
cleanup are proven.

### Slice 10 - read-only LSP

Expose definition, references, implementation, and hover only. Run pinned preinstalled servers in
the offline project container. Bound protocol/document/result sizes and reject server edit, command,
download, network, or out-of-root requests.

### Slice 11 - bounded one-shot subagents

Add one-shot child runs with durable parent/child lineage, fixed depth/sibling/concurrency/total
budgets, a grant/tool intersection with the parent, no child approval path, structured terminal
states, and descendant drain on parent cancellation. Continuable children and external adapters are
later decisions.

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
- A worker thread, VM, path fence, or language server is not a security boundary.
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

