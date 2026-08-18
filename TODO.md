# Orrery TODO

Last reconciled with executable code: **18 August 2026**.

This file contains unfinished work only. Product direction and ordering live in [`PLAN.md`](PLAN.md),
implemented behavior lives in [`ARCHITECTURE.md`](ARCHITECTURE.md), and completed work lives in the
[`DEVLOG`](docs/history/DEVLOG.md). Remove an item when it is completed and recorded in the DEVLOG;
do not keep a second checklist of completed tasks here.

## P1 — bounded documents and deterministic verification

- [ ] Move DOCX/XLSX/PPTX ingestion and Office/PDF preview parsing into the offline bounded document
      worker; document and time-box any compatibility fallback that remains on the host.
- [ ] Extend faithful previews to ODT/ODS/ODP/RTF (today only the optional LibreOffice converter
      covers them; the Python renderers cover OOXML, CSV/TSV, and Markdown).
- [ ] Add real-container CI fixtures for embedded, scanned, mixed, encrypted, malformed, oversized,
      and multilingual documents.
- [ ] Split the backend suite further into named deterministic groups. The `db` group and per-test
      timeouts now exist; the remaining feature groups are still one undifferentiated run.
- [ ] Add a web-search provider interface with the current keyless backend as default plus
      user-configured official/self-hosted routes; preserve per-turn consent and query screening.

## P1 — finish the browser delivery

- [ ] Run the launch handshake end to end in a real browser: launch code in the URL, claim, cookie
      set, code stripped from the address bar, SSE reconnect. The tests cover the boundary, not the
      round trip.
- [ ] Decide whether `--windowed` still fits the macOS package: with no window, a user whose browser
      fails to open sees nothing at all, because the printed URL has nowhere to go.

## P1 — complete visible product gaps

- [ ] Build canvas editing for Automations: the screen now reads real workflows, the registered node
      catalog, and durable run steps, but a spec can only be changed through the API — there is no
      way to add, connect, configure, or position a node in the UI.
- [ ] Surface tool-approval requests from gated Automation nodes (headless runs currently fail them
      safely) so a user can decide.
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
- [ ] Review the generic HTML preview policy and tighten it with compatibility regression tests.
- [ ] Build the dedicated dashboard editing workspace.
- [ ] Profile very long Chat threads and add virtualization only if measurements justify it.
- [ ] Finish optional Concept-mode polish for Chat, Dashboards, Automations, Agents, and Projects;
      verify every light palette with screenshots and accessibility checks.
- [ ] Confirm GitHub's Dependabot list clears after it rescans `main`. Both dependency trees audit
      clean locally (`pip-audit`, `npm audit`) as of 18 August 2026; anything still listed after the
      rescan is either a transitive pin we do not control or needs a reachability judgement.
- [ ] Ensure the current versioned sandbox image is built/provisioned in release artifacts and CI.

## Decisions that require the user

- [ ] Approve or revise
      [`ADR-005`](docs/decisions/005-coding-harness-capabilities.md), including the dependency order
      from exact execution evidence through coding workspaces, LSP, and bounded subagents. Slice 1
      adds durable evidence only and does not grant new filesystem/process authority.
- [ ] Choose Slack/Gmail authentication: user-supplied credentials or a maintained OAuth application.
- [ ] Decide whether a container-only persistent terminal is worth its lifecycle and isolation cost
      after durable one-shot coding jobs have real usage evidence.
- [ ] Decide whether backend-capable generated apps belong in Orrery after the static-bundle path has
      real usage evidence.
