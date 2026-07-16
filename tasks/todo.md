# TODO — Five Workstreams (from tasks/plan.md; reconciled 2026-07-16)

## Phase 1 — Scale foundations
- [x] Task 1: Smooth streaming in long chats (memoized rows, frame-coalesced deltas, plain-text in-flight)
- [x] Task 2: Paginated, indexed lists (conversations.updated_at index; limit/offset; sidebar load-more)
- [x] Task 3: Ingestion idempotent + off-thread (delete-then-insert per source; durable queue job + progress)
- [x] Task 4: team_mode per-REQUEST memo (contextvar in auth dependency; never a timed cache)
- [~] Task 5: Security re-review — PARTIAL (E1/E2 privacy boundary done; agent-engine posture, team authz
      tests, doc routing verify still owed). Now unblocked (Tasks 1-4 landed).
- [ ] CHECKPOINT 1: suite green; live long-chat + big-upload checks; decide thread virtualization

## Phase 2 — Real file previews
- [x] Task 6: LibreOffice status + guided install (fixed package ids, Docker/Ollama pattern)
- [x] Task 7: Office→PDF preview pipeline wired + cached; HTML fallback with installer hint
- [x] CHECKPOINT 2: generated deck previews as real slides on this machine

## Phase 3 — One-off small apps (V1 = client-side static bundles)
- [x] Task 8: filegen produces validated multi-file app bundles (zip + extracted preview dir) — Step 145
- [x] Task 9: serve bundles read-only (strict CSP, traversal-proof) + sandboxed iframe panel + zip download
- [ ] Task 10: app-intent routing polish + heavy-scenario tests
- [ ] CHECKPOINT 3: ask → build → interact → download in one chat

## Reported-issue fixes (2026-07-16, DEVLOG Step 145-146)
- [x] Thinking stream / "no file made": capability_agent no longer bypasses explicit file requests
- [x] Generated deliverables no longer branded "Orrery"; CV disclaimers/meta-narration forbidden
- [x] Task 8 security: defusedxml for untrusted SVG; malformed-SVG & path-collision no longer crash the turn
- [x] Opaque preview filenames -> real download names; Local Models refresh feedback; dashboard toolbar row
- [x] Dead dashboards: sqlglot dialect fallback + build-script collect (No module 'sqlglot.dialects.postgres')
- [x] Prefs reset on close: pywebview private_mode was incognito -> now persists localStorage
- [x] Winter/Summer readability: chat text, selected skills/MCP tab, Automations palette; appearance captions centered
- [ ] SVG "do it" -> PDF-with-SVG-source-as-text: routing/planner picks file over image (needs heavy-matrix verify)
- [ ] Dashboard "shows working but you can't see what it's doing": stream the build/revise steps
- [ ] Local models can't use tools/code: capability-boundary architecture (design first)
- [ ] Feature: dedicated dashboard-editing side tab
- [ ] Cleanup: remove dead code / unused files (e.g. router._deliver_docspec_legacy_unused) — do conservatively

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
