# Orrery Task Routing Architecture

## Goal

Users should not have to know whether a request needs chat, SVG generation, document generation,
sandboxed code, project memory, or future voice tooling. Orrery should classify the task, load the
right skills, choose the safest execution path, and show a clear work trace.

## Design Lessons

The useful pattern from agent systems like OpenClaw-style task ledgers and Hermes-style skill use is:

1. Every user turn goes through one planner.
2. The planner selects capabilities, not raw permissions.
3. Skills are loaded automatically from the task type.
4. Sandboxes are used for artifact creation, not for unrestricted host access.
5. Work is observable through task/status events.
6. Successful behavior becomes reusable project context instead of being repeated by the user.

## Capability Layers

### 1. Planner

`backend/features/taskrouter.py` is the first-pass planner. It returns a `TaskPlan` with:

- `route`: `chat`, `file`, `image`, `audio`, or `project`
- `label` and `detail`: safe user-facing work trace
- `skills`: skill playbooks to apply
- `output_mode`: chat, file, artifact, or audio
- `sandbox_preferred` / `sandbox_required`: sandbox policy
- `unavailable_reason`: clear status for planned but not enabled capabilities

The planner does not execute anything and does not grant access. It only selects a route.

### 2. Skills

Skills live in `skills/*.md` and are injected into prompts by `backend/features/skills.py`.
Current coverage:

- core reasoning
- coding
- documents
- spreadsheets
- presentations
- code-rendered images
- audio and voice artifacts
- sandboxed artifact creation
- project workspaces

This lets Orrery improve task behavior without adding a one-off command for every phrasing.

### 3. Execution

Routes map to existing safe executors:

- `chat`: normal provider routing through `backend/providers/ai.py`
- `image`: sanitized SVG generation through `backend/features/code_images.py`
- `file`: deterministic `docgen` first, sandboxed `filegen` when visuals, computation, audio, or complex artifacts are needed
- `audio`: explicit audio files route through file generation; live voice/TTS/STT remains unavailable until providers are configured
- `project`: project workspaces group chats and provide trusted standing instructions

### 4. Sandbox Boundary

The model can create files only by writing Python that runs in the Docker sandbox. The sandbox keeps:

- no network
- no host filesystem access beyond the mounted temp work directory
- read-only container root
- non-root user
- CPU, memory, PID, timeout, output-file, and output-size caps
- backend validation before the user receives files

This gives models tool power without giving them Orrery host access.

### 5. Work Trace

The chat stream emits `reasoning_event` steps such as planning, generation path, sandbox execution,
and validation. These are safe operational summaries, not raw chain-of-thought.

## Implemented In This Pass

- Added backend task planner.
- Wired normal chat through the planner before route selection.
- Made standalone image requests generate sanitized SVG artifacts without requiring `/image`.
- Expanded file generation to recognize WAV/MP3/audio-file requests.
- Added WAV and MP3 validation.
- Added image/audio/sandbox/project skill playbooks.
- Added project workspaces with database storage, API endpoints, a UI tab, chat assignment, and trusted project context in prompts.

## Next Architecture Work

1. Project artifacts: link generated files, collections, and future automations to projects.
2. Voice settings: provider registry for TTS, STT, microphone input, playback, and voice safety policy.
3. Skill memory: record which skill stack worked for each completed task and reuse it in project context.
4. Media adapters: image/video providers behind the same capability planner.
5. Planner telemetry: task-route counts, fallback counts, sandbox failure reasons, and file quality failures.
