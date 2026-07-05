# Orrery Agent Computer — Architecture

> Status: **design, not yet built.** This is the plan we agreed to write *before* implementing, so
> the implementation is architected rather than patched. It supersedes the ad‑hoc sandbox/Crabbox
> wiring and unifies it with the capability router in `TASK_ROUTING_ARCHITECTURE.md`.

## 1. What we are actually trying to build

One sentence from the user: **"I need a Computer that agents and the model can use to perform
whatever task they want on a sandbox environment — that is why I added Crabbox."**

So the goal is not "a file generator" or "a shell tool." The goal is a **Computer**: a persistent,
isolated place with a filesystem, a shell, an interpreter, and (optionally) real OS/network access,
that the model can drive across multiple steps to accomplish an open‑ended task and hand back real
artifacts. Everything else — file generation, data crunching, image rendering, running a repo,
installing a tool — becomes *a thing you do on the Computer*, not a separate hand‑built route.

## 2. Why the current design feels "patched, not architected"

The reported bugs are all symptoms of the same root causes. Naming them so the design fixes causes,
not symptoms:

| Symptom (from the screenshots) | Root cause |
| --- | --- |
| "what do you see" + a screenshot generated `session_context_report.pdf` | **Routing is text‑only and greedy.** `taskrouter.plan()` ignored attachments; a vague prompt inherited the *previous* message's "…generate a PDF…" and hijacked the turn into file generation. *(Fixed now — see §7.)* |
| PDF/Word buttons appear under a usage‑limit **error** | **The UI infers file buttons from prompt words** (`requestedFileFormats`), independent of whether a file was actually produced. *(Guarded now — see §7.)* |
| Success shows only "Requested file: PDF Word" buttons, not a rich file card | **Two divergent file paths.** The deterministic doc path (`docgen`) yields an on‑demand *export button*; the sandbox path (`filegen`) yields a real *file card*. Same user intent, two different UIs. |
| "Writing artifact code → Repairing 2/3 → Running sandbox → Repairing 3/3" for an image question | **Canned, pre‑scripted steps.** The file route emits a fixed ladder of trace steps regardless of the task; it looks like a state machine because it *is* one, bolted in front of the model. |
| Streaming raw thoughts still leak under "Reasoning" | Thinking is stripped in some paths and not others because each route builds its own trace. |
| Uploaded files pulled into context when irrelevant | RAG over "this chat's attachments" runs on turns that don't need it; relevance filtering is a heuristic, not a decision the planner owns. |
| Attachments can't be clicked/previewed | The preview contract exists for *generated* artifacts but not for *uploaded* ones. |

The through‑line: **capabilities are decided in scattered places by regex and prompt‑word matching,
each place invents its own execution and its own UI, and there is no single durable execution
context.** The Computer + one router fixes the class of bug, not each instance.

## 3. The Computer abstraction

A single Python interface. Everything that runs code, touches a filesystem, or needs a shell goes
through it. Backends are pluggable; the default is local and safe, and Crabbox is *one* backend, not
a special case.

```python
# backend/compute/base.py  (new)
class Computer(Protocol):
    id: str                      # session/computer id, stable across a task
    kind: str                    # "local-docker" | "crabbox" | ...
    async def open(self) -> None                              # provision / attach
    async def exec(self, argv: list[str] | None = None, *,   # run a command
                   shell: str | None = None,
                   timeout: int = 120,
                   stdin: str | None = None) -> ExecResult    # streamed variant below
    async def exec_stream(self, ...) -> AsyncIterator[ExecEvent]  # live stdout/stderr/exit
    async def read_file(self, path: str) -> bytes            # pull an artifact out
    async def write_file(self, path: str, data: bytes) -> None  # push an input in
    async def list_dir(self, path: str) -> list[FileStat]
    async def snapshot(self) -> ComputerState                # for resume/audit
    async def close(self) -> None                            # tear down / release lease
```

`ExecResult` / `ExecEvent` carry `exit_code`, `stdout`, `stderr`, `timed_out`, and **already
redacted** text (secrets never cross this boundary in the clear). The interface is deliberately small:
give the model a filesystem, a way to run things, and a way to move bytes in and out.

### 3.1 Backends

**`LocalDockerComputer` (default, always available).**
A *persistent* container **per task/session**, not per call. This is the key change from today's
`sandbox.py`, which spins an ephemeral, one‑file, no‑state container for every single call and
therefore *cannot* be a computer — you can't `pip install` in step 1 and use it in step 2.

- Base image with Python + common doc/render toolchains (the same set `filegen` needs today).
- Non‑root user, read‑only root FS except a per‑session writable `/work`, dropped capabilities,
  memory/CPU/pids caps, **no network by default** (opt‑in per task, see §5).
- Lifecycle tied to the chat/agent run; idle‑reaped; `snapshot()` lets a resumed run reattach.
- `write_file`/`read_file` map to `docker cp` (or a mounted per‑session volume); `exec` to
  `docker exec`. One container, many steps.

**`CrabboxComputer` (optional, BYO, opt‑in).**
When the local Docker box genuinely can't do the job — a real macOS/Windows host, installing system
packages, cross‑platform builds — the *same* interface is backed by the user's Crabbox executor. The
existing `backend/features/crabbox.py` becomes the transport for this backend rather than a
free‑standing tool. Orrery still **never bundles Crabbox and never stores Crabbox secrets**; it holds
only non‑secret prefs (provider/profile/target/windows‑mode) as it does today.

**Why an interface instead of "just call Crabbox":** the model shouldn't have to know *where* it is
running. It asks for a computer with a capability profile (`needs_network`, `needs_os="macos"`,
`persistent=True`); the **broker** picks the cheapest backend that satisfies it (local first, Crabbox
only when required). This is what makes it "a computer the agent can use for whatever it wants"
without hard‑coding Crabbox everywhere.

### 3.2 The broker

```python
# backend/compute/broker.py  (new)
async def acquire(profile: ComputeProfile, *, feature_flags, approval) -> Computer
```

- Chooses `LocalDockerComputer` unless the profile demands something only Crabbox provides.
- Enforces gates **before** provisioning: `crabbox` feature flag, network opt‑in, and the
  **approval gate for any write/network‑enabled computer** (see §5 — this is the gap in today's
  `crabbox_run`, which is `writes=True` with no gate).
- Returns a handle the tool layer and the agent loop share, so one task = one computer = one audit
  trail.

## 4. Unified routing: the planner owns the decision, tools do the work

Today two systems fight: the regex `taskrouter` (default) and the `capability_agent` planner
(flag‑off). The screenshots are all from the regex path. The target end‑state:

1. **One planner decides per turn.** `taskrouter.plan()` stays as a *cheap first guess* and a
   fast‑path for the obvious (pure chat, a bare "draw me an SVG"), but it must be **attachment‑aware
   and non‑greedy**: a turn that carries its own image/file is about *that content*; it never
   inherits a prior turn's file intent. (Implemented in §7.)
2. **Capabilities are tools, not routes.** "Generate a file", "run this repo", "query the DB",
   "render an image" are entries in the shared registry (`backend/tools/`) described by
   `capabilities.WHEN_TO_USE`. The model picks one via the `orrery-tool` block; the backend executes
   it through `run_tool` with the same allow‑list, validation, and sanitized errors. No route
   hard‑codes "this is a file request."
3. **File generation is a computer task.** `file_generate` becomes: acquire a `LocalDockerComputer`,
   write the generator program, run it, `read_file` the artifact, register it. The deterministic
   `docgen` fast‑path stays **as an optimization inside the tool** (no sandbox needed for a plain
   docx/pdf from structured content) — but it returns the **same artifact + same file card** as the
   sandbox path. One intent, one UI. (Fixes the "buttons vs card" split.)
4. **Trace is emitted by the tool actually running, not a pre‑scripted ladder.** Steps describe what
   *happened* ("installed pandas", "rendered 3 pages"), not a fixed 1/3‑2/3‑3/3 repair script. Repair
   attempts are shown only if they occur. Raw model thinking is stripped once, at the single trace
   seam, so it can't leak per‑route.

Net effect: adding a capability = registering a tool + a `WHEN_TO_USE` line. It does not mean adding
a route, a regex, a trace ladder, and a UI branch.

## 5. Security model (this is the floor — `security.md` wins on any conflict)

- **Secrets only in the OS keychain**, never in files/logs/repo. The Computer boundary redacts
  stdout/stderr/errors before they cross into traces, streams, or persistence.
- **Model‑written code runs only on a Computer**, never in the Orrery process. Default backend is
  no‑network, non‑root, capability‑dropped, resource‑capped, ephemeral‑by‑task.
- **Approval gate for `writes=True` and for any network/OS‑enabled computer.** The broker will not
  provision a Crabbox or network‑enabled computer, and `run_tool` will not run a `writes=True` tool,
  without passing an approval object. *This closes the current gap where `crabbox_run` is
  `writes=True` with no gate anywhere* (`security.md` §4).
- **Crabbox is per‑server opt‑in, never bundled, secrets never stored by Orrery.** Unchanged.
- **All Computer output is UNTRUSTED.** RAG passages, web results, MCP results, and Computer
  stdout are data, never instructions. The prompt contract already says this; the Computer boundary
  tags its output as untrusted so downstream can't be tricked into treating a build log as a command.
- **Network is opt‑in per task**, requested in the `ComputeProfile`, gated by flag + approval, and
  surfaced in the trace ("this task was allowed network access").
- **Audit:** one computer per task = one auditable transcript of every `exec`, file in, file out.

## 6. Phased migration (incremental, non‑breaking)

Each phase ships independently; nothing below Phase 0 changes user‑visible behavior except the bug
fixes already landed.

- **Phase 0 — stop the bleeding (DONE, §7).** Attachment‑aware routing; no phantom file buttons on
  failure. Pure bug fixes, no new abstraction.
- **Phase 1 — `Computer` interface + `LocalDockerComputer`.** Wrap today's `sandbox.py` behind the
  interface as a *persistent per‑session* container. Add the broker with local‑only backend. No tool
  changes yet; just the substrate.
- **Phase 2 — `file_generate` runs on the Computer**, keeping `docgen` as the no‑sandbox fast‑path,
  returning one unified artifact + file card. Kills the buttons‑vs‑card split.
- **Phase 3 — approval gate in the broker + `run_tool`.** `writes=True` and network/OS computers
  require approval. Wire the existing UI approval prompt.
- **Phase 4 — `CrabboxComputer` as a broker backend.** `crabbox_run` becomes "acquire a Crabbox
  computer and exec," gated by flag + approval. Retire the stand‑alone raw‑subprocess path; fix the
  Windows console‑flash by using the async process helper (`proc.run`), not `subprocess.run`.
- **Phase 5 — retire regex routes.** Once the planner + tools cover file/image/audio, make the
  capability planner the default and delete the scattered route hijacks. `taskrouter` shrinks to a
  cheap hint + fast‑path.

## 7. What is already fixed in this pass (Phase 0)

Concrete, landed, tested changes (no new abstraction — these are the acute bugs):

1. **Vision turns never generate a file.** `backend/features/chat/router.py`:
   - Vague‑query inheritance is skipped when the turn has its **own** attachments (an attachment is
     the subject; it must not pick up "…make a PDF…" from an earlier message).
   - A turn carrying an **image** attachment is forced to the chat/vision route — it can never route
     to `file` or `image` generation. Regression test:
     `tests/features/test_chat.py::test_image_attachment_turn_never_routes_to_file` (even the text
     "generate a PDF report of this" with an image attached stays in chat).
2. **No phantom file buttons on failure.** `ui/src/views/chatHelpers.jsx` adds `isFileFailureNote()`;
   `ui/src/views/Chat.jsx` suppresses the on‑demand export buttons when the reply is a "could not
   create a file / no approved artifact" note (e.g. after a provider usage‑limit error).
3. **Reasoning is honest, and raw thoughts are confirmed suppressed.** Audit of every stream path
   (`chat/generation.py`, `filegen.py`, `code_interpreter.py`, `providers/ai.py`) confirms all provider
   reasoning channels — separate reasoning tokens, inline `<think>`, Anthropic `thinking_blocks`, and
   the Claude/ChatGPT CLI `ReasoningChunk` — are wrapped as `ReasoningDelta` and counted‑only by
   `ThinkStream` (`emit_raw` is never set). What looked like "streaming thoughts" was the work trace.
   The mis‑routed image case made it worse (real repair retries on an impossible file); the routing fix
   removes it. `filegen.py` no longer prints "Attempt 1/N" on the first pass, so a normal file build
   reads as what happened, not a canned ladder.

Still symptomatic, deferred to the phases above (documented so they aren't lost):
buttons‑vs‑card unification (Phase 2), the *whole* trace becoming tool‑emitted rather than route‑scripted
(Phase 5 single trace seam), irrelevant‑attachment RAG (planner owns context in Phase 5), and
uploaded‑attachment preview (artifact preview contract extended to uploads).

## 8. Open questions for the user

- **Container base image size vs. capability.** A fat image (LaTeX, pandoc, headless browser) makes
  the local Computer able to do more without Crabbox, at the cost of disk/pull time. Preference?
- **Persistence horizon.** Should a task's Computer survive app restart (snapshot/reattach), or is
  per‑session (dies with the run) enough for now? Per‑session is simpler and safer.
- **Network default.** Keep no‑network as the hard default with per‑task opt‑in (recommended), or
  allow an allow‑listed set of hosts (e.g. package registries) by default?
