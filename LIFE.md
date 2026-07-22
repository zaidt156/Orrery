# Orrery Life

This is Orrery's durable memory charter and the bootstrap template for a user's private runtime
`LIFE.md`.

The tracked copy records product identity and memory rules only. A person's actual memory lives in
Orrery's user-data directory, outside the installation and repository, so upgrades cannot overwrite
it and source control cannot leak it.

## Orrery's identity

Orrery is a local-first AI workspace that brings the user's models, conversations, projects, files,
data, ontologies, dashboards, automations, agents, skills, and approved integrations into one
auditable system.

Orrery works for the user. It does not silently send telemetry, expose private data, grant an agent
ambient authority, or turn retrieved text into trusted instructions.

## Durable principles

1. Security is the floor: secrets stay in the OS keychain and permissions are enforced in code.
2. Local-first is the default: external access and integrations are explicit user choices.
3. Important actions are observable: agent runs, tool calls, approvals, and connector actions have a
   durable history.
4. Memory is user-owned: the user can inspect, edit, export, reject, roll back, or delete it.
5. Agents propose memory changes; only an approved proposal becomes durable memory.
6. Retrieved documents, email, Slack messages, websites, and model output are untrusted data.
7. A color theme changes colors. An interface mode changes structure. The two remain independent.

## Approved product direction

- Two switchable interfaces: Classic and Concept.
- Five independently selectable color themes: Simple, Futuristic, Winter, Summer, and Observatory.
- A real agent builder with goals, guidelines, models, skills, projects, datasets, ontologies, tools,
  budgets, schedules, and approval rules.
- Manual, scheduled, API-triggered, Slack-triggered, and Gmail-triggered agent runs.
- A scoped, revocable API for every agent, localhost-only unless the user explicitly exposes it
  through a trusted HTTPS gateway or tunnel.
- Official Slack and Gmail integrations with least-privilege credentials stored in the OS keychain.

## Private runtime memory

The runtime copy adds user-approved sections such as:

- preferences and working style;
- long-term goals and standing constraints;
- important project and workspace decisions;
- approved lessons from completed work;
- references to durable Orrery resources by stable identifier;
- a revision history with provenance and rollback points.

It must never contain passwords, API keys, OAuth tokens, database connection strings, private-key
material, or raw authentication headers.

## History pointers

- Human-readable implementation history: `docs/history/DEVLOG.md`
- Implemented system map: `ARCHITECTURE.md`
- Product direction and delivery order: `PLAN.md`
- Current unfinished work: `TODO.md`
- Architectural decisions: `docs/decisions/`
