# TODO — Five Workstreams (from tasks/plan.md, 2026-07-11)

## Phase 1 — Scale foundations
- [ ] Task 1: Smooth streaming in long chats (memoized rows, frame-coalesced deltas, plain-text in-flight)
- [ ] Task 2: Paginated, indexed lists (conversations.updated_at index; limit/offset; sidebar load-more)
- [ ] Task 3: Ingestion idempotent + off-thread (delete-then-insert per source; durable queue job + progress)
- [ ] Task 4: team_mode per-REQUEST memo (contextvar in auth dependency; never a timed cache)
- [ ] Task 5: Security re-review (E-decisions, agent engine posture, team authz tests, doc routing verify)
- [ ] CHECKPOINT 1: suite green; live long-chat + big-upload checks; decide thread virtualization

## Phase 2 — Real file previews
- [ ] Task 6: LibreOffice status + guided install (fixed package ids, Docker/Ollama pattern)
- [ ] Task 7: Office→PDF preview pipeline wired + cached; HTML fallback with installer hint
- [ ] CHECKPOINT 2: generated deck previews as real slides on this machine

## Phase 3 — One-off small apps (V1 = client-side static bundles)
- [ ] Task 8: filegen produces validated multi-file app bundles (zip + extracted preview dir)
- [ ] Task 9: serve bundles read-only (strict CSP, traversal-proof) + sandboxed iframe panel + zip download
- [ ] Task 10: app-intent routing polish + heavy-scenario tests
- [ ] CHECKPOINT 3: ask → build → interact → download in one chat

## Phase 4 — Concept continuation (parallel-safe with Phases 2–3)
- [ ] Task 11: Chat view concept composition (Concept mode only)
- [ ] Task 12: per-view polish sweep (Dashboards/Automations/Agents/Projects) + light-palette audit
- [ ] CHECKPOINT 4: user approves the look

## Phase 5 — Agents increments
- [ ] Task 13: scoped external API keys (mint/revoke UI, key-auth /public/agent-runs, docs)
- [ ] Task 14: agent learning notes (post-run self-review → bounded notes in next run's prompt)
- [ ] Task 15: Slack/Gmail DESIGN doc (user decision on connection method before any code)
- [ ] CHECKPOINT 5: key runs verified; notes live; Slack/Gmail decided

## Open questions for the user (blockers marked per task)
- [ ] Thread virtualization now or later? (Checkpoint 1)
- [ ] Confirm small-apps V1 scope: client-side static bundles only
- [ ] Slack/Gmail: user-supplied tokens vs full OAuth (Task 15)
- [ ] Confirm LibreOffice guided host-install route (Task 6)
