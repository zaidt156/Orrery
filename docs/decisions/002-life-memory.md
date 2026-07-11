# ADR-002: Make LIFE.md user-owned, approval-gated memory

## Status

Accepted

## Date

2026-07-10

## Context

The user wants Orrery and its agents to remember important preferences, goals, decisions, and history
across application versions. Automatically writable long-term memory is vulnerable to model errors,
prompt injection, secret persistence, and silent preference drift.

## Decision

Ship a non-private root `LIFE.md` as the memory charter and create a private runtime copy in the
user-data directory. Agents and integrations may propose changes but cannot apply them. The user
reviews an exact diff; approved changes create atomic, immutable revisions with rollback.

## Alternatives Considered

### Store memory only in the database

Rejected because the requested durable artifact is a readable Markdown file and users may change
databases. Database rows still track proposals and approvals.

### Let agents edit the file automatically

Rejected because persistent prompt injection or a mistaken inference would silently become trusted
future context.

### Commit personal memory to the repository

Rejected because it risks source-control disclosure and packaging overwrites.

## Consequences

- File and database revisions must remain consistent under failure.
- Secret scanning is defense in depth, not permission to store sensitive values.
- Prompt construction must retrieve bounded approved memory rather than inject the entire file.
