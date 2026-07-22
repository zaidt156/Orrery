# Orrery TODO

Last reconciled with executable code: **22 July 2026**.

This file contains unfinished work only. Product direction and ordering live in [`PLAN.md`](PLAN.md),
implemented behavior lives in [`ARCHITECTURE.md`](ARCHITECTURE.md), and completed work lives in the
[`DEVLOG`](docs/history/DEVLOG.md). Remove an item when it is completed and recorded in the DEVLOG;
do not keep a second checklist of completed tasks here.

## P1 — bounded documents and deterministic verification

- [ ] Move DOCX/XLSX/PPTX ingestion and Office/PDF preview parsing into the offline bounded document
      worker; document and time-box any compatibility fallback that remains on the host.
- [ ] Add real-container CI fixtures for embedded, scanned, mixed, encrypted, malformed, oversized,
      and multilingual documents.
- [ ] Split the backend suite into named deterministic groups with per-test timeouts and publish the
      slowest tests so a hang identifies its owner.
- [ ] Add a web-search provider interface with the current keyless backend as default plus
      user-configured official/self-hosted routes; preserve per-turn consent and query screening.

## P1 — complete visible product gaps

- [ ] Add authenticated Workflow CRUD/list/get/run routes with owner filtering and validation.
- [ ] Connect Automations UI state to the Workflow API; render the registered node catalog rather
      than hard-coded nodes and show durable run-step input/output/error data. Surface tool-approval
      requests from gated nodes (headless runs currently fail them safely) so a user can decide.
- [ ] Add a small management view for the remembered "always allow" tool approvals so grants can be
      reviewed and revoked without re-approving.
- [ ] Add an Automation schedule tick and support only trigger types the runtime actually implements.
- [ ] Build Media Hub generation adapters and a local media library; keep the screen disabled/honest
      until an end-to-end generation path exists.
- [ ] Add Chat commands for Agent/Automation/Dashboard actions only after their product APIs and the
      central approval gate exist.
- [ ] Replace the Chat tool-loop claim in public/user docs whenever the implemented command surface
      changes.

## P1 — Agent platform

- [ ] Implement mint/list/revoke for per-Agent API credentials and a rate-limited authenticated
      inbound run endpoint; log only the key prefix and trigger principal.
- [ ] Add bounded Agent learning notes and include recent notes in later runs with visible provenance.
- [ ] Enforce Agent `life_access`: none, read approved memory, or create a reviewable proposal.
- [ ] Decide Slack/Gmail connection style after threat-model review; then implement authenticated,
      deduplicated receivers and least-privilege connector grants.

## P2 — durability, UX, and release polish

- [ ] Make detached Chat runs durable across backend restarts or explicitly expose their
      process-lifetime limitation in the interface.
- [ ] Make strict privacy stronger than basic privacy, or rename the modes to match reality.
- [ ] Review generic HTML preview policy and Electron `sandbox: false`; tighten both with compatibility
      regression tests.
- [ ] Build the dedicated dashboard editing workspace.
- [ ] Profile very long Chat threads and add virtualization only if measurements justify it.
- [ ] Finish optional Concept-mode polish for Chat, Dashboards, Automations, Agents, and Projects;
      verify every light palette with screenshots and accessibility checks.
- [ ] Reconcile the 15 default-branch Dependabot alerts with current lockfiles and reachability.
- [ ] Ensure the current versioned sandbox image is built/provisioned in release artifacts and CI.
- [ ] Complete Linux packaging after Windows and macOS release checks remain green.

## Decisions that require the user

- [ ] Choose Slack/Gmail authentication: user-supplied credentials or a maintained OAuth application.
- [ ] Decide whether a persistent multi-step Computer broker is worth its lifecycle and isolation cost
      after P0 enforcement is complete.
- [ ] Decide whether backend-capable generated apps belong in Orrery after the static-bundle path has
      real usage evidence.
