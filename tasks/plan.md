# Implementation Plan: The Five Workstreams (DEVLOG Step 137)

Date: 2026-07-11 · Source: user direction + `docs/planning/ARCHITECTURE_GRIND.md` +
`docs/planning/AGENT_COMPUTER_ARCHITECTURE.md` · Supersedes the completed interface-themes plan
(shipped as DEVLOG Step 132).

## Overview

Five workstreams, in the user's priority order: (1) harden the architecture so Orrery stays fast
and correct with large amounts of files/data while context handling stays intact, (2) make file
previews look like the real file (PPTX today renders as text), (3) handle "build me a small app
for one-time use" end to end, (4) continue the Concept/futuristic look toward the concept art,
and (5) grow Agents (external API keys, learning notes, Slack/Gmail design). Work is sliced
vertically: each task lands a complete, testable path and leaves the suite green.

## Where the ranked bottleneck list stands (ARCHITECTURE_GRIND)

| # | Bottleneck | Status |
|---|-----------|--------|
| 1 | Full history reload per turn | **FIXED** (Step 133: skeleton rows + hydrated tail) |
| 2 | Frontend streaming re-renders O(n²) | **OPEN → Task 1** |
| 3 | Blocking docker check per turn | **FIXED** (Step 117: cached, off-loop) |
| 4 | team_mode uncached COUNT per turn | **OPEN → Task 4** (needs per-request memo, not TTL) |
| 5 | Query re-embedded per collection | **FIXED** (Step 117) |
| 6 | Sandbox-first for plain docs | **VERIFY** in Task 5 (routing changed twice since) |
| 7 | No pagination/indexes on lists | **OPEN → Task 2** |
| 8 | Duplicate chunks on re-upload | **OPEN → Task 3** (counts N+1 already fixed) |

## Progress reconciliation (July 15, 2026)

- **Task 1: IMPLEMENTED / automated verification complete.** Stable message-row identity,
  animation-frame delta coalescing, and plain-text in-flight rendering are covered by the 100-row
  UI regression test; all UI tests and the production build pass. Manual React Profiler capture
  remains a Checkpoint 1 runtime check.
- **Task 3: IMPLEMENTED / stress verification pending.** Re-upload deduplication, queued ingestion,
  progress polling, and offline fallback tests pass. Re-run the 300-file stress harness at
  Checkpoint 1 before marking the task fully complete.
- **Tasks 6-7: COMPLETE.** LibreOffice status/guided install and faithful Office-to-PDF previews
  shipped in DEVLOG Step 141 with backend/UI tests.
- **Task 8: COMPLETE** (as of Step 145; the earlier "COMPLETE" here was premature). Static app
  intent, sandbox prompting, self-containment validation, deterministic ZIP persistence, private
  extracted preview directories, atomic cleanup, and dedicated router/tool/storage tests landed in
  Step 144 — but a follow-up review found three real defects that AC#2's "plain error" contract had
  not actually met, all fixed in Step 145: untrusted model-written SVG was parsed with raw
  ElementTree (billion-laughs exposure; now defusedxml, which the repo already standardised on),
  and both a malformed SVG (ParseError subclasses SyntaxError, not ValueError) and a file/folder
  name collision (FileExistsError is an OSError) escaped their guards and crashed the turn.
  Caveats worth carrying into Task 9: "self-containment validation" is a heuristic quality gate, not
  a boundary — `window['fet'+'ch'](...)` passes it — so Task 9's CSP is the load-bearing control;
  "private preview directories" means "no route serves them yet", not filesystem-private; and the
  ZIP is byte-deterministic within a platform but not across operating systems (ZipInfo sets
  create_system from sys.platform). Task 9 is the next small-app slice.

## Architecture Decisions

- **Previews:** use the LibreOffice→PDF path that already exists in `filepreview.py` and make it
  reachable — guided host install via the proven fixed-WinGet/brew pattern (like Docker/Ollama),
  NOT bundling LibreOffice into the sandbox image (hundreds of MB, slower builds). HTML preview
  stays as the fallback.
- **Small apps V1 = client-side static bundles.** filegen produces a multi-file bundle (html/js/
  css/assets); Orrery serves it read-only from an isolated route with a strict CSP and previews
  it in a sandboxed iframe, plus a zip download. Apps needing their own backend/processes are
  Phase 2 of the Agent Computer plan — not V1.
- **Pagination must not change context semantics.** The model-bound window is already handled by
  `_hydrate_history` (tail=200) + token trimming; list pagination touches only UI-facing queries.
- **External agent API keys authenticate the caller, not the transport.** Orrery stays
  localhost-bound; exposing it to the internet is the user's deliberate reverse-proxy/tunnel
  choice, documented with the feature (security.md §7 unchanged).

## Task List

### Phase 1 — Scale foundations (backend + the one frontend lever)

#### Task 1: Smooth streaming in long chats (frontend lever #2)
**Description:** Memoize message rows so a streamed token re-renders only the in-flight message;
coalesce deltas to one render per animation frame; render the in-flight body as plain text until
`done` (then markdown once). Completed messages already memoize their markdown.
**Acceptance criteria:**
- [ ] Streaming into a 100+ message chat re-renders only the active row (React DevTools profiler)
- [ ] Final rendered reply identical to today's
**Verification:** `node --test` UI tests; `npm run build`; manual: stream into a long chat.
**Dependencies:** none. **Files:** `ui/src/views/Chat.jsx`, `ui/src/components/Markdown.jsx`. **Scope:** M

#### Task 2: Paginated, indexed lists
**Description:** Index `conversations.updated_at` (additive migration); `list_conversations`
gains `limit/offset` (default 50) with sidebar load-more; same for any unbounded project chat
list. Thread virtualization explicitly deferred (Checkpoint 1 decision).
**Acceptance criteria:**
- [ ] 1,000-conversation workspace opens the sidebar without a full-table scan
- [ ] Older chats load on scroll; no other behavior changes
**Verification:** new API pagination test; suite green; manual scroll check.
**Dependencies:** none. **Files:** `backend/core/models.py`, `backend/core/migrations.py`,
`backend/features/chat/conversations.py`, `backend/api/routes_conversations.py`,
`ui/src/views/Chat.jsx`. **Scope:** M

#### Task 3: Large-collection ingestion — idempotent and off the request thread
**Description:** Re-uploading a source deletes its old chunks first (no duplicates); document
ingestion (chunk+embed) for collections/ontologies runs as a durable queue job with progress the
UI can poll, so a 300-file drop never freezes the app.
**Acceptance criteria:**
- [ ] Re-uploading the same file leaves exactly one chunk set
- [ ] A large multi-file upload returns immediately; progress visible; chat keeps working
- [ ] `scripts/stress_ontology_rag.py` still passes end to end
**Verification:** new tests (dedupe, job execution); stress script against local Postgres.
**Dependencies:** none. **Files:** `backend/features/rag.py`, `backend/core/queue.py`,
`backend/api/routes_collections.py`, `ui/src/views/Ontology.jsx` / `Data.jsx`. **Scope:** M

#### Task 4: team_mode per-request memo (the safe version)
**Description:** Memoize `team.current_owner_id()` / `team_mode()` in a request-scoped
contextvar (set in the auth dependency) — never a timed cache; the Step 117 deferral was about
fail-open risk right after enabling team mode.
**Acceptance criteria:**
- [ ] One team-mode lookup per request regardless of call count
- [ ] Locked-client and fresh-enable behavior unchanged (existing authz tests pass)
**Verification:** team/security tests green; call-count test with a spy session.
**Dependencies:** none. **Files:** `backend/features/team.py`, `backend/api/deps.py`. **Scope:** S

#### Task 5: Security re-review of the grown surface
**Description:** Focused review + fixes: (a) the Step-49 "E" decisions (RAG redaction vs
privacy_mode; trusted-context redaction at the provider boundary; connected ontologies being
workspace-global in team mode); (b) the new agent run engine (prompt-injection posture of tool
results, approval-bypass attempts, budget integrity); (c) automated team-mode authorization
tests (Step 108 follow-up); (d) verify docgen-vs-sandbox routing for plain docs (#6). Anything
needing a user decision gets asked, not assumed.
**Acceptance criteria:**
- [ ] Each E-decision resolved (fix or explicit recorded decision)
- [ ] New authz tests: locked client, cross-owner agents/runs/approvals, member vs admin routes
**Verification:** suite green with new tests; DEVLOG security note.
**Dependencies:** Tasks 1–4 landed (review the final shape). **Files:** review-driven. **Scope:** M

### Checkpoint 1 — Scale foundations
- [ ] Full suite green, UI builds; long-chat streaming and big-collection upload verified live
- [ ] DEVLOG updated; decide: thread virtualization now or later?

### Phase 2 — Real file previews

#### Task 6: LibreOffice status + guided install
**Description:** Settings (or the preview panel's empty state) shows whether faithful Office
previews are available; one consented click installs LibreOffice via fixed package ids
(`TheDocumentFoundation.LibreOffice` / the brew cask), mirroring the Docker/Ollama installer
pattern; probe re-checks. No user-supplied package names, ever.
**Acceptance criteria:**
- [ ] Status reflects reality with/without LibreOffice installed
- [ ] Install flow completes and status flips without an app restart
**Verification:** probe unit tests; manual install on this machine.
**Dependencies:** none. **Files:** `backend/features/filepreview.py`,
`backend/api/routes_files.py` (or system), `ui/src/views/Settings.jsx`. **Scope:** M

#### Task 7: Faithful preview pipeline (PPTX/DOCX/XLSX → PDF)
**Description:** With LibreOffice present, `/preview` converts Office files to PDF (the path
already exists in `filepreview.py`) and the panel renders that PDF; conversions cached next to
the artifact; the HTML rendering stays as the fallback. Kills the "deck previews as text" issue.
**Acceptance criteria:**
- [ ] A generated PPTX previews as real slides (layout, images); DOCX/XLSX likewise
- [ ] Without LibreOffice: today's fallback + a hint pointing at Task 6's installer
**Verification:** tests with soffice mocked (both branches); manual: generate a deck → preview.
**Dependencies:** Task 6. **Files:** `backend/features/filepreview.py`,
`backend/api/routes_files.py`, preview panel. **Scope:** S–M

### Checkpoint 2 — Previews
- [ ] Deck generated in chat previews as slides on this machine; suite green; DEVLOG updated

### Phase 3 — One-off small apps

#### Task 8: Multi-file app bundles from filegen
**Description:** Teach the router/filegen an "app" deliverable: the sandbox produces a bundle
directory (`index.html` + js/css/assets); validation checks self-containment (extend the
existing single-file HTML validator to bundles); stored as a zip artifact plus an extracted
preview directory in the generated-files store.
**Acceptance criteria:**
- [x] "Build me a small expense-splitter app" yields a bundle artifact (zip + preview dir)
- [x] Bundles with external references are rejected with a plain error
**Verification:** filegen bundle-validation tests; routing test for app intent.
**Dependencies:** none (parallel to Phase 2). **Files:** `backend/features/filegen.py`,
`backend/features/files.py`, `backend/features/taskrouter.py`. **Scope:** M

#### Task 9: Serve + preview app bundles safely
**Description:** `GET /api/apps/{artifact_id}/{path}` serves bundle files read-only with a
strict CSP (self-only), traversal-proof path resolution, correct MIME types; the chat file card
gains "Open app" → sandboxed iframe panel + "Download zip". Session-token gated like every API
route. This is the security-sensitive slice.
**Acceptance criteria:**
- [ ] The bundle runs interactively in the panel; requests cannot escape the bundle dir
      (traversal tests) or reach the network (CSP)
- [ ] The zip download reproduces the working app
**Verification:** traversal + CSP header tests; manual: use a generated app in the panel.
**Dependencies:** Task 8. **Files:** new `backend/api/routes_apps.py` (or routes_files),
file card/panel UI. **Scope:** M

#### Task 10: End-to-end app route polish
**Description:** Wire intent ("quick tool", "one-time app", "small app") through the planner
with tests; the reasoning trace narrates the build; revise/regenerate works in-conversation.
**Acceptance criteria:**
- [ ] The heavy-scenarios matrix gains app-intent cases and passes
**Verification:** `tests/features/test_heavy_scenarios.py` extended; suite green.
**Dependencies:** Tasks 8–9. **Files:** `backend/features/taskrouter.py`, tests. **Scope:** S

### Checkpoint 3 — Small apps
- [ ] Ask → build → interact → download in one chat; security tests in place; DEVLOG updated

### Phase 4 — Concept continuation (parallel-safe with Phases 2–3)

#### Task 11: Chat view concept composition
**Description:** Bring Chat toward the reference sheet: in-panel header, clean message rows,
composer pill styling, context-pane alignment. Concept mode only; zero behavior change.
**Acceptance criteria:**
- [ ] Chat reads like the concept sheet in Concept mode; Classic untouched
**Verification:** UI build; screenshots in both modes.
**Dependencies:** none. **Files:** `ui/src/views/Chat.jsx`, `styles.css`, `appearance.css`. **Scope:** M

#### Task 12: Per-view concept polish sweep
**Description:** Dashboards, Automations, Agents, Projects: card/panel depth, headings, icon
chips, spacing per the concept sheets; audit Winter/Summer light palettes under Concept.
**Acceptance criteria:**
- [ ] No view reads as a "plain sibling"; light palettes clean in Concept
**Verification:** UI build; per-view screenshot pass; user visual approval.
**Dependencies:** Task 11 (shared patterns). **Files:** `ui/src` views + css. **Scope:** M

### Checkpoint 4 — Concept
- [ ] User approves the look; DEVLOG updated

### Phase 5 — Agents increments

#### Task 13: Scoped external API keys per agent
**Description:** Mint/revoke per-agent keys (storage exists: `AgentApiCredential` — hashed,
prefix, scopes, expiry). A key-authenticated `POST /public/agent-runs` endpoint (rate-limited,
`trigger_type="api"`, principal = key prefix), separate from the session token; key value shown
once at mint. Docs state plainly: Orrery is localhost-bound — internet exposure is the user's
deliberate tunnel/proxy choice.
**Acceptance criteria:**
- [ ] Mint/list/revoke in the agent UI; a revoked key stops working immediately
- [ ] Key-triggered runs appear in the ledger with the API trigger + principal
**Verification:** API tests (auth, revocation, scoping); manual curl run.
**Dependencies:** run engine (done). **Files:** new `backend/features/agent_keys.py`,
`routes_agents.py`, `Agents.jsx`. **Scope:** M

#### Task 14: Agent learning notes
**Description:** The Step-9 vision: each run ends with a short self-review saved to the agent's
own notes; the next run's prompt includes recent notes (bounded count/size). Visible in the UI.
**Acceptance criteria:**
- [ ] A completed run writes ≤1 note; the next run's transcript includes recent notes
**Verification:** engine tests extended; manual two-run check.
**Dependencies:** run engine (done). **Files:** `agent_runs.py`, `models.py` (additive notes
table), `Agents.jsx`. **Scope:** M

#### Task 15: Slack/Gmail triggers — design first
**Description:** One-page design before any code: polling vs events, credential storage
(keychain), per-connector grants (spec exists in `ConnectorGrantSpec`), exact user setup flow.
**Needs a user decision on the connection method — do not build until chosen.**
**Acceptance criteria:**
- [ ] Design in `docs/planning/` with the decision points listed
**Verification:** user sign-off.
**Dependencies:** Task 13. **Scope:** S (design only)

### Checkpoint 5 — Agents
- [ ] External key runs verified; learning notes live; Slack/Gmail decision made; DEVLOG updated

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Pagination breaks context semantics | High | Only list queries change; `_prepare_turn` untouched; versioning e2e test guards |
| App serving becomes an attack surface | High | Session-token gate + strict CSP + traversal tests land BEFORE the UI exposes it; bundles validated self-contained |
| LibreOffice absent/huge on user machines | Med | Guided install is optional; HTML fallback always works; never bundled into the sandbox image |
| Streaming refactor changes chat feel | Med | Plain-text in-flight render must end in an identical final render; verify live before shipping |
| Ingestion-as-job races live retrieval | Med | Chunks visible only after per-source commit; stress script is the gate |
| Slack/Gmail OAuth complexity | Med | Design-first; no code until the user picks the method |

## Parallelization

- Phase 4 (Concept) is independent — safe alongside Phases 2–3.
- Tasks 1–4 are mutually independent; Task 5 reviews their final shape.
- Phases 2 and 3 are independent until the preview panel touches the same UI files.

## Open Questions (need the user)

1. Thread virtualization (very long chats still render fully): do it at Checkpoint 1, or defer?
2. Small apps V1 = client-side static bundles only (backend-ful apps arrive with the Agent
   Computer) — confirm this scope.
3. Slack/Gmail: user-supplied tokens (simple, works today) vs a full OAuth app (smoother,
   heavyweight) — pick at Task 15.
4. LibreOffice guided host-install as the preview route (vs bundling into the sandbox) — confirm.
