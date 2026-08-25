# Orrery Work — task list

- [x] **1. Workspace roots and path confinement.** A `WorkspaceRoot` table (owner-scoped, one
      attached folder, cascade-safe) and `resolve_in_root()`: resolve the real path, reject anything
      that leaves the root. Symlinks and junctions resolved *before* the check, `..` traversal,
      absolute paths outside the root, and Windows device paths all refused.
      *Done when:* abuse tests pass for symlink escape, junction escape, `..`, absolute outside,
      device path, and a case-differing path on Windows — all written before any tool uses it.
      *Scope:* M — 3 files + tests.

- [x] **CHECKPOINT** — confinement is attacked and holds before a single tool can call it.

- [x] **2. Read tools.** `work_read`, `work_glob`, `work_grep`, registered in the tool registry,
      every path through `resolve_in_root`, bounded output.
      *Done when:* each reads only inside the root and refuses outside it; output is capped.
      *Scope:* M — 2 files + tests.

- [ ] **3. Run a command in the root.** `work_run`: host execution, cwd pinned to the root, timeout,
      bounded output, cancellable, approval-gated.
      *Done when:* a command runs and returns output; cwd is the root; a timeout kills it; cancel is
      honoured at the tool boundary.
      *Scope:* M — 2 files + tests.

- [ ] **CHECKPOINT** — the model can understand a folder and run things in it, and still cannot
      touch a byte outside it.

- [ ] **4. Writes, with a log.** `work_write`, `work_edit` (observed-version), `work_delete`, and a
      `WorkspaceWrite` table recording root, path, action and digests.
      *Done when:* an edit against a stale digest is refused; every mutation appears in the log with
      before/after digests.
      *Scope:* M — 3 files + tests.

- [ ] **CHECKPOINT** — writes land, and there is a record of every one.

- [ ] **5. Plan mode.** In Orrery Work the model returns a plan first; no tool runs until it is
      accepted.
      *Scope:* M.

- [ ] **6. The Orrery Work screen.** Attach a folder, see the plan, watch the steps, see what
      changed, stop it.
      *Scope:* L.
