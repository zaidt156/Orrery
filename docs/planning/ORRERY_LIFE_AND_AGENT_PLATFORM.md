# Orrery LIFE Memory and Agent Platform

## Status

Approved product direction. Implementation is incremental and security-gated.

## Objective

Turn Orrery's static Agents preview into a real local-first agent platform. A user can create an
agent, give it instructions and selected Orrery resources, run it manually or on a schedule, invoke
it through a scoped API, and connect it to Slack or Gmail. All activity remains inspectable and
bounded. Orrery also gains an upgrade-safe `LIFE.md` that preserves user-approved long-term memory.

## User Outcomes

The user can:

- keep durable preferences, goals, decisions, and lessons across Orrery upgrades;
- review every proposed addition to long-term memory before it becomes active;
- create an agent with a goal, guidelines, model, skills, projects, datasets, ontologies, tools,
  connectors, budgets, loop limits, and approval rules;
- submit one-off tasks or enable a cron schedule;
- pause, resume, cancel, inspect, retry, and audit runs;
- create revocable credentials for a single agent and invoke that agent from another service;
- receive and respond through Slack using Socket Mode;
- read, triage, draft, and—when explicitly permitted—send Gmail messages;
- expose an agent endpoint externally through a user-configured HTTPS tunnel/reverse proxy while
  the Orrery application itself remains bound to loopback.

## Non-Negotiable Safety Contract

- Agent scope is an allowlist enforced by tools, never prose in a prompt.
- No agent gets all of Orrery merely because the UI says "everything"; the user selects each resource
  and capability.
- Deletes, external sends, sensitive writes, new network destinations, connector permission changes,
  and `LIFE.md` updates require an approval policy. Safe read-only actions may be pre-approved.
- Model output, retrieved files, email, Slack messages, connector payloads, web results, and API input
  are untrusted.
- Code executes only through Orrery's isolated Computer/sandbox boundary.
- Access, refresh, app, bot, and gateway tokens live only in the OS keychain; database rows contain
  metadata and hashes, never plaintext credentials.
- External agent APIs are off until a credential is created and remain loopback-only unless the user
  explicitly configures an HTTPS exposure path.
- Every run has hard limits: steps, wall time, token/cost budget, failures, payload size, and connector
  actions.

## LIFE.md Architecture

### Files

- Repository `LIFE.md`: non-private bootstrap charter and current product direction.
- Runtime `<user-data>/LIFE.md`: canonical user-owned memory, created once and never overwritten by
  upgrades.
- Runtime `<user-data>/life-history/<revision>.md`: immutable approved snapshots for rollback.

All writes use a temp file plus atomic replace. A content hash and monotonically increasing revision
prevent stale approvals or concurrent edits from overwriting newer memory.

### Memory proposal flow

1. A user or agent submits a proposed Markdown entry with a reason and provenance.
2. The boundary validates size, section, source identity, and secret patterns.
3. The proposal is stored as `pending`; it is not included in prompts.
4. The user reviews the exact diff and approves, edits, or rejects it.
5. Approval snapshots the old file, applies the accepted text atomically, and records its hash.
6. Rollback creates a new revision from a selected historical snapshot; history is never erased.

Direct editing is a user action and still produces a revision. Agent/API/connector callers can only
propose.

### Prompt use

Only the current approved runtime file is eligible for prompt context. It is bounded and sectioned;
Orrery includes only relevant memory or a compact approved summary rather than blindly injecting the
entire file. Memory is labeled as user-approved context, never as a replacement system instruction.

## Agent Domain Model

### Agent

Stable fields:

- `id`, `owner_id`, `name`, `description`, `goal`, `model`;
- `guidelines` (user-authored instructions);
- `status`: draft, active, paused, archived;
- `config_version` and a validated JSON configuration;
- resource allowlists: project, collection/dataset, ontology, skill, MCP server, connector;
- tool allowlist with operation-level grants (read, write, send, network, code);
- execution limits: max steps/run, runs/day, wall time, token/cost budget, consecutive errors;
- approval policy per action category;
- optional schedule and timezone;
- timestamps and owner.

The config is additive and versioned. Stable IDs and public API fields are never silently renamed.

### Agent run

- trigger: manual, schedule, API, Slack, Gmail, automation, or handoff;
- sanitized input and attachment/resource references;
- status: queued, running, waiting_approval, completed, failed, canceled, interrupted;
- immutable configuration snapshot;
- output, error summary, usage, timing, and correlation ID;
- parent/source identifiers for idempotency and connector acknowledgements.

### Agent run step

Every plan, tool request, tool result, approval, connector action, and final check is recorded with a
stable event type, sanitized bounded fields, duration, and status. Raw secrets and unrestricted
document/email bodies are not copied into logs.

### Approval

Approvals contain the exact bounded action payload or memory diff, its hash, risk category, expiry,
requester, run, and decision. Approval of one action cannot authorize a modified payload.

### API credential

A high-entropy credential is shown once. Only a SHA-256 hash, display prefix, scopes, rate limit,
expiry, last-used time, and revocation state are stored. Credentials belong to exactly one agent.

### Connector account

Database rows contain connector kind, display identity, granted scopes, status, and non-secret
settings. Tokens and client secrets are referenced by keychain key.

## Execution Model

1. Validate trigger input at the boundary.
2. Load the agent and immutable configuration snapshot.
3. Resolve only allowlisted resources and approved `LIFE.md` context.
4. Build a bounded plan using the configured model.
5. Execute allowlisted tools through the shared tool registry/Computer boundary.
6. Before a gated action, persist an approval request and suspend the run durably.
7. Resume after approval; revalidate scope and payload hash.
8. Self-check against the goal, then complete or continue within limits.
9. Persist output, usage, steps, and optional memory proposals.

Procrastinate remains the durable queue. User-defined schedules use one frequent dispatcher that
reads stored schedules and defers due runs with a per-agent/per-period idempotency key. This follows
Procrastinate's documented dynamic-scheduling pattern and avoids registering arbitrary decorators at
runtime: https://procrastinate.readthedocs.io/en/main/howto/advanced/cron.html

## Public Agent API Contract

Base path: `/agent-api/v1`

Authentication: `Authorization: Bearer <one-time-issued-agent-token>` over HTTPS. The loopback route
also accepts it so integrations can be tested locally. API tokens never use the desktop session
token.

Initial endpoints:

```text
GET    /agents/{agentId}                 read public status/capabilities
POST   /agents/{agentId}/runs            invoke a task
GET    /agents/{agentId}/runs/{runId}    read status/result
POST   /agents/{agentId}/runs/{runId}/cancel
GET    /agents/{agentId}/openapi.json    agent-specific contract
```

Invocation accepts a bounded JSON object with `input`, optional attachment references, metadata,
callback URL only when separately allowlisted, and an `Idempotency-Key`. It returns `202 Accepted`
with a run resource. Long tasks are never held open.

Controls:

- credential scope (`invoke`, `read`, `cancel`) and agent match;
- constant-time hash comparison;
- per-credential rate and concurrency limits;
- body, string, attachment, and timeout limits;
- idempotency storage to stop retries from duplicating work;
- generic structured errors with correlation IDs;
- no browser CORS by default (websites call from their backend, avoiding exposed bearer tokens);
- audit events for auth success/failure, invocation, rate limit, cancellation, and result access;
- no raw prompt, secret, or full connector payload in security logs.

FastAPI's `APIKeyHeader`/security dependency pattern informs the boundary, while Orrery performs the
actual credential lookup and authorization:
https://fastapi.tiangolo.com/reference/security/#fastapi.security.APIKeyHeader

### External exposure

Orrery continues to bind its main server to `127.0.0.1`. The user may explicitly publish only
`/agent-api/v1` through a trusted HTTPS reverse proxy or tunnel. Documentation requires TLS, a host
allowlist, request-size/time limits, and no exposure of `/api` or artifact preview routes. The UI
shows exposure state and a kill switch. Orrery does not silently create a third-party tunnel.

## Connector Architecture

Connectors implement one registry contract:

```text
connect / disconnect / health
receive events -> normalized ConnectorEvent
perform allowlisted action -> ConnectorResult
required scopes + risk classification
```

Each event carries a provider event ID used as an idempotency key. Connector content remains
untrusted context and is passed only to agents explicitly granted that connector/account/channel or
mailbox.

### Slack

- Use Socket Mode for inbound events, which Slack documents as avoiding a public HTTP Request URL:
  https://docs.slack.dev/apis/events-api/using-socket-mode/
- Store the app-level and bot/user tokens in the OS keychain.
- Acknowledge each `envelope_id` before queueing long agent work; deduplicate the event ID.
- Grant only selected workspaces/channels and events to an agent.
- Send through `chat.postMessage` with `chat:write`; outbound messages are approval-gated by default:
  https://docs.slack.dev/reference/methods/chat.postmessage
- Support OAuth v2/token rotation when app credentials are configured; rotated access and refresh
  tokens remain in the keychain:
  https://docs.slack.dev/authentication/using-token-rotation

### Gmail

- Use Google's desktop OAuth flow with PKCE and a random loopback redirect port:
  https://developers.google.com/identity/protocols/oauth2/native-app
- Store refresh/access tokens in the OS keychain and validate returned `state` and granted scopes.
- Request the narrowest selected scopes. Sending alone uses `gmail.send`; reading/triage requests a
  separate read scope. Full `mail.google.com` is never the default:
  https://developers.google.com/workspace/gmail/api/auth/scopes
- For installed/local Orrery, poll/synchronize within configured limits. Optional Gmail push uses
  user-configured Cloud Pub/Sub pull delivery; watches renew before their seven-day expiry:
  https://developers.google.com/workspace/gmail/api/guides/push
- Drafting is safe by default. Sending uses the Gmail `messages.send` contract and requires approval
  unless the agent has an explicit narrow send policy:
  https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send
- Enforce Google's user-data policy and never implement spam/bulk-mail behavior:
  https://developers.google.com/workspace/workspace-api-user-data-developer-policy

## Threat Model

| Boundary | Primary threats | Required controls |
|---|---|---|
| Agent API | token theft, replay, flooding, cross-agent access | TLS gateway, one-agent token, hash-only storage, idempotency, rate/concurrency limits |
| Agent planner/tools | prompt injection, excessive agency, data exfiltration | untrusted-data framing, allowlisted tools/resources, approvals, sandbox, budgets |
| LIFE.md | memory poisoning, secret persistence, stale overwrite | proposal approval, diff/hash binding, secret scan, atomic revisions, rollback |
| Slack | forged/replayed events, excessive channel access, token theft | pre-authenticated Socket Mode, envelope ack/dedupe, channel grants, keychain |
| Gmail | OAuth interception, overbroad scope, unintended send, PII leakage | PKCE/state, loopback redirect, narrow scopes, send approval, redaction, keychain |
| Schedules | duplicate/missed jobs, runaway cost | durable idempotency key, queue lock, catch-up policy, run/day and spend limits |
| Connectors | malicious third-party content | schema validation, size caps, content treated as data, no implicit tool authority |

## On-Call Questions and Observability

1. Why did this agent run, and which immutable config triggered it?
2. Which tool/connector action failed or is waiting for approval?
3. Was an external request rejected for auth, scope, replay, or rate limit?
4. Are schedules duplicating, falling behind, or exhausting a budget?

Signals are structured local events with correlation/run IDs. Metrics use bounded labels such as
trigger, status, connector kind, and action category—never user IDs, emails, prompts, or raw URLs.

## API and Data Compatibility

- `/agent-api/v1` is additive and versioned from its first release.
- Pydantic schemas define all request/response shapes.
- List endpoints are paginated.
- PATCH semantics update only supplied fields.
- Errors have one machine-readable shape.
- Existing `/api` session-token routes remain unchanged.

## Delivery Phases

1. `LIFE.md` service, proposals, approvals, revisions, rollback, and UI.
2. Agent models, CRUD/API contracts, resource/permission configuration, and real Agents UI.
3. Durable manual runs, bounded executor, run steps, approvals, stop/resume, and activity stream.
4. Dynamic schedules and queue idempotency.
5. Scoped per-agent credentials and `/agent-api/v1`.
6. Connector registry and Slack Socket Mode send/receive.
7. Gmail OAuth, read/draft/send, and synchronization.
8. External gateway documentation/configuration, responsive UI, adversarial security review, and
   full runtime verification.

Each phase is separately testable, buildable, and rollback-friendly.

## Success Criteria

1. Runtime `LIFE.md` survives reinstall/upgrade and cannot be modified by an agent without an
   approved exact diff.
2. Agents are persisted and configurable with real Orrery resources and enforce those selections at
   tool boundaries.
3. Manual and scheduled runs are durable, bounded, stoppable, resumable after approval, and audited.
4. Each agent can issue and revoke its own scoped API credentials; another agent's credential fails.
5. Retries with the same idempotency key create one run.
6. Slack can receive an allowed event and send an approved response using real Socket Mode.
7. Gmail can authorize with PKCE, read only within granted scopes, create a draft, and send only under
   the configured approval policy.
8. No connector or agent credential appears in the database, logs, API response, prompt, or
   `LIFE.md`.
9. External gateway tests cover invalid tokens, replay, over-limit input, rate limits, cross-agent
   access, and cancellation.
10. The Concept Agents page is backed by real API state; no hard-coded agent/run feed remains.
