# Plan — Orrery Work

**Status:** in progress. **Decisions:** [`ADR-007`](../docs/decisions/007-orrery-work-host-execution.md)
— host execution, direct writes, the attached folder as the boundary.

## What it is

A mode in Orrery where you attach a folder and the model can read it, search it, run commands in it,
and create and change files in it. It plans the task first and shows you the plan before it acts.

## The order, and why

Path confinement is security-critical and everything else depends on it, so it is built and attacked
first, alone, before a single tool can call it. Then the read tools, which cannot damage anything.
Then commands. Then writes, which are the only irreversible part and arrive last with their log
already in place. Plan mode wraps the lot once there is something to plan against.

```
workspace roots + path confinement            [1]  ← attacked before anything uses it
      │
      ├── read tools: read / glob / grep      [2]
      │        │
      │        └── run a command in the root  [3]
      │                  │
      │                  └── write / edit / delete + write log   [4]
      │
      └── plan mode, then the Orrery Work UI  [5, 6]
```

## Architecture

**One seam for every path.** A single `resolve_in_root(root, candidate)` that returns a real path or
raises. Every tool goes through it. No tool does its own path arithmetic — that is how a second,
weaker check gets written later and becomes the hole.

**Tools, not a shell.** Each capability is a registered tool (`work_read`, `work_glob`,
`work_grep`, `work_run`, `work_write`, `work_edit`) so scope, the ADR-004 deny hook, the approval
gate and ADR-005 evidence apply without Orrery Work inventing a second execution path.

**Edits are observed-version.** `work_edit` takes the digest of the content it read. If the file
changed underneath, the edit is refused rather than clobbering. Cheap, and it removes the whole
class of "the model overwrote something it never saw".

**The write log is a table**, not a text file: root, path, action, digest before and after, run id.
It is what answers "what did it change" without asking the model.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Path confinement is bypassed | **Critical** | One seam, resolved-realpath checks, abuse tests written before the tools exist |
| A command escapes the folder's contents (network, package install) | **High** | Stated plainly in ADR-007; not solvable by path confinement. Approval on first command per root |
| A wrong edit lands on disk unreviewed | High | Write log with digests; recommend version control at the point the folder is attached |
| A long command hangs the turn | Medium | Timeout and a cancel that is honoured at the tool boundary |
| Symlink/junction escape on Windows | High | Resolve before checking, reject links whose target leaves the root; Windows-specific tests |

## Answered

**Should a root persist across restarts?** Yes, owner-scoped. Attaching a folder is a deliberate
act, and making the user redo it every launch is how people end up attaching something broader than
they mean, just to stop being asked. Several roots are remembered; exactly one is active per owner,
so "the attached folder" always has a single answer.

**Which folders may be attached at all?** Not the whole disk, not a home directory, not a system
path. This is not convenience validation: attach `C:\` and confinement still holds perfectly —
every path resolves inside the root, every check passes — and the guarantee is emptied rather than
weakened. `workspace.check_attachable` runs once, when the folder is chosen.

**Should `work_run` require approval every time, once per root, or once per distinct command?**
Once per root. Blanket is too broad to be honest — approving `ls` would pre-approve `rm -rf`. Per
command is too narrow to live with, since a build is dozens of them and a user who is asked thirty
times stops reading. The folder is the unit the user actually reasoned about when they attached it.
This is why `work_run` *requires* a root id instead of accepting "whatever is current": a remembered
approval must not survive the user switching folders.

## Open questions

- (none open)
