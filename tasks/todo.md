# Independent Interface and Color Themes

## Task 1: Appearance state and migration

**Acceptance criteria:**

- [ ] Interface and color values normalize independently.
- [ ] Legacy `orrery-theme` migrates without losing the selected palette.
- [ ] Both attributes are applied before React paints.

**Verification:** `node --test ui/src/**/*.test.js`

**Dependencies:** None

**Files:** `ui/src/lib/appearance.js`, `ui/src/lib/appearance.test.js`, `ui/src/main.jsx`

## Task 2: Token-axis separation

**Acceptance criteria:**

- [ ] Color selectors set colors only.
- [ ] Classic/Concept own all geometry, spacing, shadows, and background patterns.
- [ ] Status colors remain semantically stable.

**Verification:** UI build plus computed-style browser check

**Dependencies:** Task 1

**Files:** `ui/src/styles.css`, optional focused CSS modules under `ui/src/styles/`

## Task 3: Appearance controls

**Acceptance criteria:**

- [ ] Settings shows separate Interface and Color theme groups.
- [ ] Both update instantly, persist, and expose pressed state/accessibility labels.
- [ ] App reacts without reload.

**Verification:** appearance tests, build, keyboard browser check

**Dependencies:** Tasks 1-2

**Files:** `ui/src/App.jsx`, `ui/src/views/Settings.jsx`, appearance state/provider, CSS

## Task 4: Dual shells

**Acceptance criteria:**

- [ ] Classic restores compact icon navigation, hides Home, and defaults to Chat.
- [ ] Concept retains labeled navigation, top bar, Home, and connection status.
- [ ] Feature flags, team lock, updates, and navigation work in both.

**Verification:** build and browser navigation in both interfaces

**Dependencies:** Tasks 1-3

**Files:** `ui/src/App.jsx`, shared shell components, CSS

## Task 5: Scroll contract and shared primitives

**Acceptance criteria:**

- [ ] Shell/body never scroll.
- [ ] Reusable workspace/panel/scroll-region primitives are accessible and minimal.
- [ ] Desktop and compact fallbacks are defined.

**Verification:** browser scroll-owner inspection at four viewport sizes

**Dependencies:** Task 4

**Files:** shared components and structural CSS

## Task 6: Home

**Acceptance criteria:**

- [ ] Concept Home follows the reference hierarchy and uses only real data.
- [ ] Normal desktop size has no Home page scrollbar.
- [ ] Classic does not expose Home.

**Verification:** build, screenshot, endpoint/error-state check

**Dependencies:** Task 5

**Files:** `ui/src/views/Home.jsx`, shared primitives, CSS

## Task 7: Chat

**Acceptance criteria:**

- [ ] Concept Chat has bounded navigation, thread, context, and pinned composer regions.
- [ ] Existing streaming, attachments, reasoning, versions, and model controls remain functional.
- [ ] Narrow layout preserves access to secondary panes.

**Verification:** existing UI tests, build, live chat browser smoke test

**Dependencies:** Task 5

**Files:** `ui/src/views/Chat.jsx`, chat widgets if needed, CSS

## Task 8: Data

**Acceptance criteria:**

- [ ] Sources, datasets, collections, and table browsing are separate bounded panels.
- [ ] Metrics are derived from current loaded state.
- [ ] Existing add/remove/upload/refresh/browse actions remain functional.

**Verification:** build and browser checks for empty/populated/error states

**Dependencies:** Task 5

**Files:** `ui/src/views/Data.jsx`, shared primitives, CSS

## Task 9: Ontology

**Acceptance criteria:**

- [ ] Concept Ontology uses navigation, honest source graph/canvas, and detail panes.
- [ ] Current CRUD, connect, upload, search, and file actions remain functional.
- [ ] No fabricated relationships appear.

**Verification:** build and live CRUD/navigation browser checks

**Dependencies:** Task 5

**Files:** `ui/src/views/Ontology.jsx`, shared primitives, CSS

## Task 10: Dashboards

**Acceptance criteria:**

- [ ] Dashboard list, real widgets, and controls follow the concept hierarchy.
- [ ] Refresh/revise/import/SQL behaviors remain intact.
- [ ] Widget canvas owns its overflow.

**Verification:** existing dashboard tests, build, browser smoke test

**Dependencies:** Task 5

**Files:** `ui/src/views/Dashboards.jsx`, CSS, shared primitives as needed

## Task 11: Automations

**Acceptance criteria:**

- [ ] Workflow list, canvas, inspector, and run history are bounded and concept-styled.
- [ ] Node selection/edge rendering still works after layout changes.

**Verification:** build, resize test, keyboard selection, screenshot

**Dependencies:** Task 5

**Files:** `ui/src/views/Automations.jsx`, CSS

## Task 12: Agents

**Acceptance criteria:**

- [ ] Agent list, controls, summaries, integrations, and activity form one deliberate workspace.
- [ ] Static preview content is clearly identified as preview/demo state.

**Verification:** build, accessibility tree, screenshot

**Dependencies:** Task 5

**Files:** `ui/src/views/Agents.jsx`, CSS

## Task 13: Remaining workspaces

**Acceptance criteria:**

- [ ] Projects, Skills, Media, Local Models, Admin, and Settings use the Concept hierarchy.
- [ ] Their existing workflows remain reachable in both modes.

**Verification:** build and navigation/console sweep

**Dependencies:** Task 5

**Files:** implemented as separate 1-2-view increments, never more than five files per increment

## Task 14: Responsive and accessibility pass

**Acceptance criteria:**

- [ ] Layouts work at 320, 768, 1024, and 1440 widths.
- [ ] Keyboard focus, accessible names, reduced motion, and contrast are verified.
- [ ] No unintentional document scroll exists.

**Verification:** real-browser viewport/accessibility matrix

**Dependencies:** Tasks 6-13

## Task 15: Regression, cleanup, and review

**Acceptance criteria:**

- [ ] Ten interface/color combinations render cleanly.
- [ ] UI build/tests and full Python tests pass.
- [ ] The old `nice`/artifact regression remains covered; `Issues/` screenshots are removed.
- [ ] DEVLOG describes the finished state and next work accurately.
- [ ] Final review finds no blocking correctness, accessibility, security, or maintainability issue.

**Verification:** full Definition of Done gate

**Dependencies:** All prior tasks

## Task 16: LIFE.md service and revision tests

**Acceptance criteria:**

- [x] Runtime memory is created outside the install and survives subsequent bootstrap calls.
- [x] Agent-originated changes remain pending until an exact diff is approved.
- [x] Approved changes are atomic, revisioned, secret-screened, and rollbackable.

**Verification:** focused unit/integration tests plus file-failure simulations

**Dependencies:** None

**Files:** path helper, LIFE feature module, models/migration, focused tests

## Task 17: LIFE.md APIs and UI

**Acceptance criteria:**

- [x] User can read, edit, propose, approve, reject, inspect history, and roll back.
- [x] Solo/team ownership and authorization are enforced.
- [ ] Approved relevant memory can be loaded without allowing it to override system policy.

**Verification:** API tests, browser review flow, security test for unapproved memory

**Dependencies:** Task 16

## Task 18: Agent data contracts and CRUD

**Acceptance criteria:**

- [ ] Validated agent configs cover guidelines, models, resource/tool/connector grants, limits,
  approvals, and schedule.
- [ ] Runs, steps, approvals, credentials, and connector accounts have additive migrations.
- [ ] CRUD is paginated, owner-scoped, and uses one error shape.

**Verification:** schema, migration, ownership, invalid-input, and round-trip tests

**Dependencies:** Task 16

## Task 19: Real Agents builder UI

**Acceptance criteria:**

- [ ] Hard-coded agents and activity are removed.
- [ ] User can build an agent from real models, skills, projects, datasets, ontologies, tools, limits,
  schedules, and approval policies.
- [ ] Empty, loading, validation, and error states are accessible.

**Verification:** build and live browser create/edit/archive flow

**Dependencies:** Tasks 18 and interface foundation

## Task 20: Durable agent executor

**Acceptance criteria:**

- [ ] Manual run snapshots config, loads only granted resources, and executes only granted tools.
- [ ] Limits, stop, retries, approvals, resume, usage, and run-step audit work durably.
- [ ] Sandbox and prompt-injection boundaries have abuse-case regression tests.

**Verification:** unit, integration, induced-failure, and restart/resume tests

**Dependencies:** Task 18

## Task 21: Dynamic schedules

**Acceptance criteria:**

- [ ] Valid cron/timezone schedules dispatch due agents exactly once per period.
- [ ] Paused/disabled/budget-exhausted agents do not run.
- [ ] Late-run policy and queue backpressure are visible.

**Verification:** deterministic-clock scheduler and duplicate-worker tests

**Dependencies:** Task 20

## Task 22: Scoped per-agent API

**Acceptance criteria:**

- [ ] Credentials are shown once, hash-only at rest, scoped, expiring, and revocable.
- [ ] Invoke/read/cancel endpoints enforce agent match, idempotency, payload, rate, and concurrency
  limits.
- [ ] External publication exposes only the gateway and requires HTTPS.

**Verification:** contract and abuse-case tests, including replay and cross-agent denial

**Dependencies:** Task 20

## Task 23: Connector registry and Slack

**Acceptance criteria:**

- [ ] Connector secrets stay in keychain and grants are agent/account/channel specific.
- [ ] Slack Socket Mode acknowledges and deduplicates real envelopes before queueing work.
- [ ] Outbound messages require configured permission/approval and use `chat:write` only.

**Verification:** protocol fake tests plus opt-in live Slack smoke test when credentials exist

**Dependencies:** Tasks 20 and 22

## Task 24: Gmail

**Acceptance criteria:**

- [ ] Desktop OAuth uses PKCE/state/loopback and stores refresh tokens only in keychain.
- [ ] Read, draft, and send scopes are requested separately and enforced per agent.
- [ ] Synchronization is idempotent; sends follow the configured approval policy.

**Verification:** OAuth/token-refresh fakes, Gmail REST contract tests, opt-in live smoke test

**Dependencies:** Tasks 20 and 23 connector contract

## Task 25: Agent platform security and launch gate

**Acceptance criteria:**

- [ ] STRIDE abuse cases, secrets scan, dependency audit, API fuzz/size/rate tests, and connector
  prompt-injection tests pass.
- [ ] Structured local events answer trigger/action/approval/failure questions without storing
  sensitive content.
- [ ] ADRs, API docs, LIFE charter, DEVLOG, setup instructions, rollback path, and connector
  prerequisites are current.

**Verification:** full Definition of Done and fresh-context adversarial review

**Dependencies:** Tasks 16-24
