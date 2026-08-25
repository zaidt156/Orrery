# Plan — durable approval pause and resume for Automations

**Status:** planned, not implemented. **Blocked on one product decision** (see Open questions).
**Scope:** `backend/core/models.py`, `backend/automation/engine.py`, `backend/features/workflows.py`,
`backend/api/routes_workflows.py`, `ui/src/views/Automations.jsx`.

## Why

Step 176 fixed the dangerous half of this: a gated Automation node used to be recorded as a
*successful* step, and the run finished `done` while the refusal travelled downstream as data. It
now fails the run visibly and records the refusal on the step.

What it did not fix is that the run is simply over. `run_tool` raised an approval request, nobody can
see it, and it expires undecided after ten minutes. The user's only recourse is to start the workflow
again from the beginning — and it will stop in the same place, because nothing was ever approved.

## The pattern already exists

Agents solved this. `AgentApproval` is a durable table — run id, owner, tool key, risk, an
`action_digest`, the serialized action, status, `expires_at`, `decided_at`, `decided_by` — and an
agent run suspends, records the pending decision, and resumes from its own durable step log once the
user answers. Automations should mirror that rather than invent a second mechanism. Chat's
`approvals._STORE` is explicitly in-memory and process-lifetime, which is fine for a chat turn
someone is watching and wrong for a headless workflow.

## The problem that decides the design

A resumed workflow must not re-run the nodes that already succeeded — they may have sent an email or
written to a database. So resume has to replay their outputs from `workflow_run_steps`.

**Those stored outputs are lossy.** `_record_step` writes `_clip(output_obj)`, which is
`json.dumps(...)[:20_000]`. The column exists for the run-debug view, and 20,000 characters is
generous for a human reading it and arbitrary for a machine resuming from it. A node that returned a
long database result or a fetched document would come back **silently truncated**, and the
downstream `{{node.key}}` substitution would use the truncated value without any indication.

Resuming from a display artifact is the trap here. Three ways out, and this is the decision that
gates the work:

1. **Store a separate, unclipped resume payload.** A new column or table holding the exact output,
   subject to its own size ceiling, deleted with the run. Correct, and costs storage for data that is
   usually only read on resume.
2. **Re-run pure nodes, replay only effectful ones.** Nodes would have to declare purity. `delay`,
   `if_branch`, `llm_prompt` and `search_docs` are safe to re-run; `http_request`, `db_query`,
   `run_python`, `run_shell`, `mcp_tool` are not. More machinery, and a wrong purity label is a
   silent duplicate side effect.
3. **Refuse to resume when any completed output was clipped.** Cheapest and honest: record whether
   clipping happened, and if it did, tell the user the run cannot be resumed and must be restarted.
   Most runs would resume fine; the ones that cannot would say so instead of quietly corrupting.

My recommendation is **3 for the first slice, 1 later if it proves annoying**. It is the only option
that cannot silently produce wrong data, it is small, and it converts an unknown into a visible
limitation. Option 2 is the one to avoid: purity labels that are wrong fail silently and in the worst
possible direction.

## Dependency graph

```
WorkflowApproval table + migration                              [Task 1]
      │
      ├── engine: pause instead of fail, record the request     [Task 2]
      │        │
      │        └── resume: replay completed steps, continue     [Task 3]
      │
      ├── API: list pending, decide, resume                     [Task 4]
      │
      └── Automations UI: show and answer                       [Task 5]
```

## Task list

### Phase 1: durable state
- Task 1: `WorkflowApproval`, mirroring `AgentApproval`, with a migration
- Task 2: the engine records a pending approval and leaves the run `awaiting_approval`

### Checkpoint
- A gated node parks the run; the row exists; nothing regresses for ungated runs

### Phase 2: resume
- Task 3: resume replays completed steps and continues, refusing when any output was clipped

### Checkpoint
- A paused run resumes to completion without re-running effectful nodes

### Phase 3: reach it
- Task 4: authenticated list/decide/resume routes, owner-scoped
- Task 5: the Automations screen shows a pending decision and can answer it

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Resume replays truncated node output as if it were complete | **High** | The decision above; option 3 refuses rather than corrupts |
| A paused run holds a worker slot | Medium | Resume is a fresh queued job; the paused run holds nothing |
| An approval outlives the workflow it belongs to | Medium | `ondelete="CASCADE"` on the run, and an expiry sweep like the agent one |
| Resume re-runs an effectful node after a restart | **High** | Only steps recorded `done` are replayed; a node interrupted mid-flight is not |
| Two resumes race | Medium | Claim the approval in a transaction before dispatching, as `decide_approval` does |

## Open questions

- **Which resume strategy?** The three options above. My recommendation is 3.
- **How long should a workflow approval live?** Agents use `expires_at`. A headless workflow may be
  triggered while nobody is watching, so ten minutes is clearly too short; a day is plausible.
- **Should a scheduled run request approval at all,** or should gated nodes be refused outright on
  scheduled triggers and permitted only on manual ones? Asking someone to approve an action at 3am
  is a different product than asking them while they watch it run.
