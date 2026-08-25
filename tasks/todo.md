# Automation approval pause/resume — task list

**Blocked:** Task 3 needs the resume-strategy decision in `tasks/plan.md` (Open questions).
Tasks 1, 2, 4 and 5 do not.

- [ ] **1. `WorkflowApproval` table + migration.** Mirror `AgentApproval`: run id (cascade), owner,
      tool key, risk, `action_digest`, serialized action, status, `expires_at`, `decided_at`,
      `decided_by`. A status check constraint and an owner+status index, as the agent table has.
      *Done when:* migration runs clean on an existing database; a row survives a restart.
      *Scope:* S — 2 files + tests.

- [ ] **2. The engine parks the run instead of failing it.** When `run_tool` returns
      `approval_required`, write a `WorkflowApproval`, record the step as `awaiting_approval`, and
      leave the run `awaiting_approval` rather than `failed`. Ungated runs must be untouched.
      *Done when:* a gated node parks the run and creates exactly one approval row; the Step 176
      regression test still passes for genuinely refused (not gated) calls.
      *Scope:* M — 2 files + tests.

- [ ] **CHECKPOINT** — a gated node parks; nothing regresses for ordinary runs.

- [ ] **3. Resume.** Replay completed steps' outputs, skip their execution, continue from the parked
      node with the approval consumed single-use. Refuse to resume when any replayed output was
      clipped — `_record_step` stores `json.dumps(...)[:20_000]` for the debug view, so it cannot
      faithfully reconstruct a large output, and feeding a truncated value downstream is worse than
      declining. Needs the decision in plan.md first.
      *Done when:* a paused run resumes to completion; effectful nodes run exactly once; a run with a
      clipped output refuses to resume and says why.
      *Scope:* M — 2 files + tests.

- [ ] **CHECKPOINT** — resume is correct or it declines; it never replays truncated data.

- [ ] **4. API.** Authenticated, owner-scoped: list pending approvals for a run, decide one, and
      dispatch the resume. Claim the approval in a transaction before dispatching so two resumes
      cannot race.
      *Scope:* S/M — 2 files + tests.

- [ ] **5. Automations UI.** Surface a parked run and its pending decision, and let the user answer.
      `listToolApprovals` already exists in `ui/src/lib/api.js` with zero callers.
      *Scope:* M — 2 files + tests.

- [ ] **CHECKPOINT** — a gated workflow can be approved and finished from the screen it ran on.
