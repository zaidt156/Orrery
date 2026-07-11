# Implementation Plan: Independent Interface and Color Themes

## Overview

Replace the coupled theme implementation with two independent axes, restore a genuine Classic shell, and complete the reference-driven Concept interface across all Orrery workspaces. Work proceeds from state and tokens to shell, then page families, then responsive/runtime verification.

## Architecture Decisions

- Store `interface` and `colorTheme` separately and apply both before first paint.
- Migrate the old `orrery-theme` preference without changing the user's chosen palette.
- Keep one application/data implementation; interface modes change composition and structural CSS, not backend logic.
- Treat scroll ownership as an explicit layout contract based on fixed viewport grids.
- Use the supplied concept art for hierarchy while rendering only real Orrery state and actions.

## Dependency Graph

```text
appearance state + migration
    -> independent token axes
        -> dual-mode shell + navigation
            -> shared Concept primitives
                -> Home/Chat
                -> Data/Ontology
                -> Dashboards/Automations/Agents
                -> remaining views + Settings
                    -> responsive/accessibility pass
                        -> browser matrix + full regression gate
```

## Phase 1: Appearance Foundation

- [x] Task 1: Add tested appearance state, legacy migration, and pre-paint application.
- [x] Task 2: Split structural interface tokens from color palette tokens.
- [x] Task 3: Add independent Interface and Color theme controls in Settings.

### Checkpoint: Foundation

- [x] Axis-independence tests pass.
- [ ] Changing a color theme does not alter computed structural properties.
- [x] UI builds with no startup flash.

## Phase 2: Shells and Scroll Contract

- [x] Task 4: Restore the Classic compact shell and Classic routing defaults.
- [ ] Task 5: Formalize the Concept shell and shared workspace primitives.
- [ ] Task 6: Enforce viewport lock and named inner scroll regions.

### Checkpoint: Shells

- [x] Classic has no Home tab and starts in Chat.
- [x] Concept has Home, labeled rail, and fixed top bar.
- [ ] Browser body/app do not scroll in either mode.

## Phase 3: Primary Workspaces

- [ ] Task 7: Recompose Home to fit the desktop workspace.
- [ ] Task 8: Complete the Concept Chat composition and independent pane scrolling.
- [ ] Task 9: Recompose Data into bounded source, collection, and table panels.
- [ ] Task 10: Recompose Ontology into navigation, knowledge canvas, and detail panes.

### Checkpoint: Primary Workspaces

- [ ] Home, Chat, Data, and Ontology match the supplied hierarchy with real data.
- [ ] All existing actions still work.
- [ ] Each page has only its intended scroll owners.

## Phase 4: Builder Workspaces

- [ ] Task 11: Recompose Dashboards around list, widget canvas, and insight controls.
- [ ] Task 12: Recompose Automations around workflow list, canvas, inspector, and runs.
- [ ] Task 13: Recompose Agents around agent list, controls, summaries, and activity.

### Checkpoint: Builders

- [ ] Builder canvases remain usable without full-page scrolling.
- [ ] Static/demo content is clearly labeled and never presented as live state.

## Phase 5: Remaining Destinations

- [ ] Task 14: Apply the Concept system to Projects and Skills.
- [ ] Task 15: Apply the Concept system to Media and Local Models.
- [ ] Task 16: Apply the Concept system to Admin and the remaining Settings sections.

### Checkpoint: Coverage

- [ ] Every enabled main-navigation destination has an intentional Classic and Concept presentation.
- [ ] No page is merely an old layout with a decorative hero pasted above it.

## Phase 6: Quality and Handoff

- [ ] Task 17: Responsive, keyboard, reduced-motion, and contrast pass.
- [ ] Task 18: Run the 10-combination interface/color browser matrix and full regression suite.
- [ ] Task 19: Verify the screenshot-reported chat regression, remove `Issues/` screenshots, and append the DEVLOG entry.
- [ ] Task 20: Perform final multi-axis code review and simplification pass.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Duplicating two complete applications | High maintenance cost | Share data/actions; branch only shell/composition and scoped CSS |
| Palette selectors still leak geometry | Theme switching moves UI | Unit/browser computed-style invariance checks |
| Full-page scroll returns through a missing `min-height: 0` | Broken desktop feel | Explicit scroll-owner classes and browser inspection per page |
| Concept artwork contains fictional features/data | Misleading UI | Map references only to existing endpoints/actions; honest empty/demo states |
| Large CSS cascade becomes fragile | Regressions across themes | Separate palette and interface scopes; land page families incrementally |
| Existing backend work is overwritten | Lost unrelated changes | Never stage or edit the current chat-performance files |

## Open Questions

None blocking. The user confirmed exactly two interface modes: Classic and Concept.

## Track B: LIFE Memory and Real Agents

This track is specified in `docs/planning/ORRERY_LIFE_AND_AGENT_PLATFORM.md`. It is sequenced so the
Concept Agents workspace consumes real state rather than hard-coded preview rows.

### Phase B1: Durable memory and approvals

- [x] Add the runtime LIFE file service, atomic revisions, proposal/approval records, and rollback.
- [x] Add authenticated desktop APIs and a user-facing review/editor surface.
- [ ] Add relevant approved memory to agent/chat context without treating it as a system override.

### Phase B2: Agent contracts and persistence

- [ ] Add versioned agent configuration, resource grants, limits, runs, steps, approvals, credentials,
  and connector-account models/migrations.
- [ ] Add paginated CRUD schemas/routes with team ownership and stable error semantics.
- [ ] Replace the hard-coded Agents view with real list/builder/detail data.

### Phase B3: Execution and schedules

- [ ] Build the bounded plan/act/check executor on the shared tool registry and sandbox boundary.
- [ ] Add durable approval suspension/resume, stop, retries, run ledger, usage, and activity events.
- [ ] Add dynamic cron dispatch with per-agent/per-period idempotency and queue locks.

### Phase B4: Integration API

- [ ] Issue/revoke one-agent credentials with hash-only storage and `invoke/read/cancel` scopes.
- [ ] Add `/agent-api/v1` asynchronous run resources, idempotency, payload/rate/concurrency limits,
  agent-specific OpenAPI, and audit events.
- [ ] Add explicit external-gateway configuration/docs that expose only `/agent-api/v1` over HTTPS.

### Phase B5: Slack and Gmail

- [ ] Add the connector registry and normalized event/action contracts.
- [ ] Add Slack Socket Mode receive/ack/dedupe and approved `chat.postMessage` actions.
- [ ] Add Gmail desktop OAuth PKCE, narrow scopes, synchronization, drafts, and approved sends.
- [ ] Add per-agent connector/account/channel/mailbox grants and connector health controls.

### Checkpoint: Agent platform complete

- [ ] LIFE changes cannot bypass review.
- [ ] Agent resource/tool scope is enforced below the model.
- [ ] Manual, scheduled, API, Slack, and Gmail runs are durable and idempotent.
- [ ] All credentials remain in the OS keychain or hash-only database fields.
- [ ] The real Agents UI and external API pass security, runtime, and regression tests.
