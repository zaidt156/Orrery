# ADR-003: Use scoped agent APIs and outbound-first connectors

## Status

Accepted

## Date

2026-07-10

## Context

Agents need to work on schedules, integrate with external websites, and operate through Slack and
Gmail without abandoning Orrery's localhost-only, local-first security model.

## Decision

- Add a versioned `/agent-api/v1` with one-agent, revocable, hash-only credentials and asynchronous
  run resources.
- Keep the Orrery server on loopback. External publication is explicit and exposes only the agent
  gateway through a user-configured HTTPS tunnel/reverse proxy.
- Use Slack Socket Mode so inbound Slack events arrive over an authenticated outbound WebSocket.
- Use Gmail's desktop OAuth PKCE loopback flow and narrow, user-selected scopes.
- Store every connector secret in the OS keychain and enforce per-agent connector/resource grants.

## Alternatives Considered

### Bind the whole Orrery API publicly

Rejected because it exposes administrative, file, session, and local workspace surfaces that external
integrations do not need.

### Put bearer tokens in browser JavaScript

Rejected because website visitors can extract them. Integrations call from their server backend.

### Use broad Gmail and Slack permissions by default

Rejected because least privilege and provider verification requirements demand feature-specific
scopes.

## Consequences

- External users need an HTTPS gateway/tunnel or reverse proxy.
- Connector setup requires provider app credentials and consent.
- Every action needs idempotency, rate/concurrency limits, and audit events.
- Slack/Gmail content is untrusted and cannot expand agent permissions.
