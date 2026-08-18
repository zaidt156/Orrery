# ADR-004: Adopt harness composability without giving up the trust boundary

## Status

Accepted

## Date

2026-08-18

## Context

DeepSeek Harness (`dsh`), built on the Cordis framework, organises an agent runtime around
"everything is a plugin": plugins contribute services, typed events, and reversible effects to a
shared context, so the model adapter, tool registry, session log, and even the agent loop are
replaceable from configuration. Four of its properties are worth having in Orrery:

1. **Hook seams.** Waterfall extension points (`tools/pre-execute`, `agent/pre-step`) let policy
   attach without editing the loop.
2. **Session log as source of truth.** "Model-visible means logged": every model request is
   reconstructible from an append-only log, which is what makes fork, resume, and replay possible.
3. **Configuration layering.** Ordered layers (bundles, profile, home, CLI) with a command that
   dumps the resolved tree.
4. **Plugin architecture.** Capabilities mounted from configuration, with registrations that unwind
   when a plugin unloads.

Orrery is closer to some of these than it looks. `agent_runs._transcript()` already rebuilds the
model-bound conversation from durable `AgentRunStep` rows, which is (2) in embryo. `backend/tools`
already has a registry with decorator registration and per-tool risk metadata. What Orrery does not
have is a seam: `run_tool()` performs its scope, feature-gate, grant, validation, and approval
checks as a fixed inline sequence, and `agent_runs.execute_run()` is a single long loop.

The tension is that Orrery's security model is the opposite of "everything is replaceable". Its
non-negotiable rule is that authorization, scope, validation, approval, and audit run in code below
the model, at the actual execution boundary (`references/security.md` §4). A framework where any
component can be swapped from configuration is, read literally, a framework where the approval gate
can be swapped out from configuration.

## Decision

Adopt all four, in dependency order, with one rule that overrides the borrowed design:

**Hooks and plugins may deny, observe, or annotate. They may never grant.**

Concretely:

- A registered hook can veto an execution or add context to it. A hook that returns "allow" does not
  make an otherwise-denied call proceed; the built-in guards in `run_tool()` keep running and keep
  the final say. Removing every hook must leave behavior at least as strict, never looser.
- The approval gate, scope allow-list, grant checks, and argument validation are not pluggable
  services. They are the floor that plugins run on top of.
- Plugins are local code the user installs deliberately. Nothing fetches or mounts a plugin from a
  remote source, and a plugin never widens a grant it was given.

Order of work, each step usable on its own:

1. **Hook seams** first, because they are what the later steps attach to.
2. **Session log operations** (fork, resume, replay) second, building on the derive-from-log
   invariant that already exists for agent runs.
3. **Configuration layering** third; it is self-contained and is what plugin mounting will read.
4. **Plugin mounting** last, since it needs both a seam to register into and a config layer to be
   declared in.

## Alternatives Considered

### Adopt Cordis-style full replaceability

Rejected. Making the agent loop and tool registry swappable from configuration would put the
enforcement points under the same configuration surface as ordinary features, and a
misconfiguration would then be a security failure rather than a broken feature.

### Port `dsh` itself, or run it alongside Orrery

Rejected. It is a TypeScript monorepo and a declared developer preview with expected
compatibility-breaking changes. Orrery's rule is that Python owns application logic and that a
second backend language is not added without a reason this does not meet.

### Skip the hook seam and keep editing the loop directly

Rejected, but it is the status quo and it works. The reason to move is that every new policy today
means another inline branch in `run_tool()` and `execute_run()`, and those are exactly the
functions where a mistake is a security bug.

## Consequences

- New policy attaches at a seam instead of as another branch in the two most security-sensitive
  functions in the codebase.
- The deny-only rule means Orrery's hooks are strictly less expressive than Cordis waterfalls. That
  is deliberate: it keeps "fail closed" true by construction rather than by review.
- Fork/resume/replay become possible for agent runs because the transcript is already derived from
  the durable log rather than from memory.
