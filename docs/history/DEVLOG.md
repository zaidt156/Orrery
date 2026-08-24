# Orrery — Development Log

A plain-words record of every step we take building Orrery. Newest entries at the bottom. Each entry says **what we did, why, and what comes next.**

---

## Step 1 — The idea (June 13, 2026)

We confirmed the concept is feasible: a desktop app like Claude/ChatGPT/Perplexity, but the user brings their **own API keys** and their **own database** (Postgres). The app provides the framework that ties them together. Similar apps exist (LibreChat, Jan, AnythingLLM), which proves the pattern works — we're building our own take on it.

## Step 2 — Name and language (June 13, 2026)

Named the app **Orrery**. Decided Python is the main language, with small amounts of JavaScript only where the screen needs it, and Rust only if ever truly necessary.

## Step 3 — First plan, including Automations (June 13, 2026)

Wrote the first development plan. Key addition: a standalone **Automations tab** where users build n8n-style visual workflows — for example, "every morning, query my database, have the AI summarize the results, and send it to Slack." The first plan used Tauri (Rust) + React + FastAPI.

## Step 4 — Simplified the stack (June 13, 2026)

The first stack felt too heavy, so we simplified it around Python:

- **Removed:** Tauri (Rust), React, TypeScript, npm, all build tools, separate vector database.
- **Kept / chose instead:**
  - `pywebview` for the desktop window (pure Python),
  - FastAPI for the backend,
  - `litellm` so one library talks to every AI provider,
  - SQLAlchemy with SQLite as the zero-setup default — the user's **Postgres** plugs in later by changing one connection string,
  - plain HTML/JS for the screen, with Drawflow.js (one script tag) for the n8n-style canvas,
  - APScheduler for scheduled automations, keyring for safe API key storage, PyInstaller for packaging.
- **Result:** the entire app installs with one `pip install` line and starts with `python app.py`. One language to debug.

Also created this DEVLOG.md — from now on, every step we complete gets written here in plain words.

## Step 5 — Postgres-first, stronger automation stack (June 13, 2026)

Decision: **PostgreSQL is now required and is the single source of truth** — chats, documents, workflows, run logs, and even the job queue all live in it. With Postgres committed, we upgraded the parts that were downgraded for simplicity:

- **RAG:** back to **pgvector** (real vector search inside Postgres) instead of numpy.
- **Automation engine:** adopted **Procrastinate**, a Postgres-native task queue for Python. It gives us durable workflow runs (a run survives the app being closed), automatic retries with backoff, and cron-style scheduling — all without Redis or Celery. It replaced APScheduler.
- **Database triggers:** workflows can now react to new/changed rows in the user's tables using Postgres's built-in LISTEN/NOTIFY.
- **Canvas:** upgraded from Drawflow to **React Flow**, the industry-standard node-editor library, inside one small React + Vite app (plain JavaScript, no TypeScript). All logic still lives in Python — React only paints the screen.

Why this is "better but still simple": the only services Orrery needs are Python and Postgres. No message brokers, no extra databases, no Rust. The plan file was updated to v3.

## Step 6 — Interface mockup (June 13, 2026)

Built a clickable HTML mockup (`orrery_mockup.html`) showing every planned feature, so we can validate the interface before writing the real app. What it contains:

- **Chat tab:** conversation list, streaming reply (with blinking cursor), model picker, "Use my data" toggle, a RAG citation chip showing which collection was searched, markdown table + SQL code block, composer.
- **Data tab:** Postgres connection cards (with pgvector and queue badges), document collections for RAG (including a "live sync" collection that auto-embeds new table rows), and a read-only table browser.
- **Automations tab:** workflow list with status and success rate, the node canvas (palette, six connected nodes, click any node to see its config panel with `{{variable}}` templating and retry policy), and a run-history drawer — click a run to expand per-node steps, including a failed run that recovered via automatic retries.
- **Settings tab:** masked API keys with "in keychain" badges, MCP server toggles, defaults (model, temperature, theme, log retention).

Design identity: **Orrery → a star map.** A workflow graph literally looks like a constellation, so the canvas is styled as one — deep indigo night sky, faint starfield, glowing "star" ports on nodes, warm amber for AI nodes and ice blue for triggers (stellar temperatures). Type: Bricolage Grotesque for headings, IBM Plex Sans/Mono for UI and data. The logo is a small constellation.

This mockup is design reference only — the real app will rebuild these screens in React, but the layout, colors, and copy carry over.

## Step 7 — Copy polish, design approved (June 13, 2026)

The mockup design was approved with wording changes, now applied:

- **Title bar:** just "Orrery" — tagline removed.
- **"Postgres" no longer appears anywhere in the interface.** The rail indicator now reads DATABASE, connection cards show plain host addresses, and technical terms (pgvector, LISTEN/NOTIFY, queue names) were replaced with plain words: "vector search," "live trigger," "workflow queue," "built-in scheduler."
- **Chat hint** is now: *"saved as you go — in your database, nowhere else"* — which doubles as the privacy promise.
- Run history now reads "stored in your database — runs survive app restarts."

Important distinction: this is interface copy only. Under the hood the stack is unchanged (PostgreSQL, pgvector, Procrastinate) — the app just never makes the user read implementation names. **The design is now locked.**

## Step 8 — Added Dashboards (June 13, 2026)

New feature added to the plan and mockup: **Dashboards** — a fifth tab where the user describes a dashboard in plain words and picks **which AI model builds it**. How it works:

- The chosen model looks at the connected database schema, writes the SQL for each widget, and picks the chart types (big number, line, bar, table).
- Orrery saves the result as a reusable **spec** in the database. From then on, opening or refreshing the dashboard simply re-runs the saved queries on live data — **no AI call and no token cost to reuse it.** The model is the designer, not the renderer.
- Every dashboard and every widget records which model made it, and revisions ("add a refunds widget") can use a different model than the original. Specs are versioned, so a bad AI edit rolls back in one click.
- Dashboards connect to the rest of Orrery: charts from Chat can be pinned to a dashboard, and automations get a "Refresh dashboard" node.

The mockup now shows the Dashboards tab: a "Sales overview" built by claude-sonnet-4-6 with five widgets (each showing the SQL behind it), a "Latest orders" widget added by gpt-4o to demonstrate model mixing, and a revise bar at the bottom. Charting library for the real app: Apache ECharts. Dashboards slot in as **Phase 3** (~1 week), pushing Automations to Phase 4 and Power features to Phase 5.

## Step 9 — Added Agents (June 13, 2026)

Sixth and final tab added: **Agents** — continuous workers that get a goal instead of a recipe. The difference from Automations in one line: an automation follows fixed steps you designed; an agent figures out its own steps and loops — plan, act, check its own work, improve — until the goal is met, a limit is hit, or you stop it.

Every agent is defined by four things:
- **Goal** in plain words ("keep every new ticket triaged; ask me when unsure").
- **Scope** — the only area it may touch: named tables (read/write split), allowed tools, and hard limits (loops per day, spend per day, confidence bar). Enforced at the tool layer, so the agent literally cannot act outside its area.
- **Model** — each agent runs on whichever model you pick, just like dashboards.
- **Run mode** — continuous until stopped, until done, on a timer, or on a trigger.

"Improving again and again" works through **learning notes**: each loop ends with a self-review, and the agent saves what it learned to its own memory table — the next loop reads those notes first, so mistakes become rules over time. Agents collaborate the same way workflows connect: an automation can start an agent, an agent can fire an automation, and agents hand work to each other (or to you, via approval gates) through a shared handoff queue — solo, alongside, or in collaboration.

Oversight built in from day one: a live activity feed of every action and learning, a daily budget meter, approval gates for low-confidence writes, and a stop button that always works. The mockup shows a running "Ticket triager" with its goal/scope/budget cards, collaboration pills, and a live feed — including an amber "Learned:" note and a ticket waiting for human approval. Agents are **Phase 5** (~2 weeks); the detailed execution model gets designed when we reach it, as agreed.

## Step 10 — Created the Orrery project skill (June 13, 2026)

To build Orrery in an organized, secure, consistent way across many sessions, we packaged the project's principles into a reusable **skill** — a self-contained set of instructions that gets loaded whenever someone works on Orrery, so every session follows the same rules instead of re-deciding them.

The skill (`orrery-development`) is built around five non-negotiable principles: security is the floor (not a feature), local-first and private by default, accuracy over assumption, Python for all logic, and document every step in plain words. Its main file stays short and points to four deeper references read as needed:

- **security.md** — the most important one. Because Orrery handles three dangerous things at once (the user's secret API keys, direct database access, and autonomous agents), this spells out exactly how to handle secrets, write safe parameterized SQL, enforce read-only access where it belongs, sandbox agents at the tool layer so their limits can't be talked around, isolate the code-running node, defend against malicious instructions hidden in retrieved documents or data, lock the app to localhost, vet dependencies, and keep an audit trail — ending in a pre-ship checklist.
- **architecture.md** — the stack, the project folder layout, how a request flows at runtime, and what each of the six tabs does and how they connect.
- **conventions.md** — how code is written and, crucially, the one repeatable pattern for adding a new workflow node, dashboard widget, or agent capability, plus error handling and what must be tested.
- **roadmap.md** — the six build phases, why they're in that order, the decisions we deliberately deferred, and the competitive context.

We validated the skill and packaged it into an installable file. From now on it travels with the project as its rulebook.

## Step 11 — Settled the project name: Orrery (June 13, 2026)

Locked in **Orrery** as the name and propagated it consistently across every artifact — the mockup's title bar, logo label, and the assistant's name in chat; the plan; this log; and the project skill (its folder, its `name`, every reference file, the example database name, and the project-root paths in the structure diagrams). An orrery is a clockwork model of the solar system, where the planets turn in relation to one another around a common centre — which is exactly how Orrery's parts behave: Chat, Dashboards, Automations, and Agents all moving in concert around the one thing at the centre, the user's database. It also makes the star-map design we already built feel native rather than decorative. The files are now `ORRERY_PLAN.md`, `orrery_mockup.html`, and `orrery-development.skill`; the skill was re-validated after the change.

## Step 12 — Added an AI quality & safety layer (June 13, 2026)

Folded five AI technologies into the plan and skill, each chosen to reinforce Orrery's two non-negotiables — privacy/local-first and accuracy — rather than to chase features. None of them adds a server, and four of the five live in phases already on the roadmap. They are:

- **Local embeddings** — an option to compute document embeddings on the machine itself (no document text sent to a cloud service), so RAG can run fully private. Added to Phase 2.
- **Hybrid search** — combine the existing vector search with the database's built-in keyword search for materially better retrieval, with no new infrastructure. Added to Phase 2.
- **Structured outputs** — force the model to return schema-checked, valid output. This is the biggest single reliability lever for agent tool calls and for generated SQL, so it threads through Dashboards, Automations, and Agents (Phases 3–5).
- **SQL validation** — every query the AI writes for a dashboard is parsed and dry-run in read-only mode before it is saved or shown, and the model self-corrects on error. Accuracy for Phase 3.
- **PII redaction** — scan rows and documents and strip personal data before any content is sent to a cloud model. Because Orrery connects to a real database, this matters a lot; it got its own section in the security rulebook (now §10), an entry in the pre-ship checklist, and is applied as a default on the outbound path to cloud providers (local models can be exempted explicitly).

Updated four files: the plan (a new "AI quality & safety layer" table plus the build-phases timings), and the skill's roadmap, security, and architecture references so future sessions build these in by default. The skill was re-validated and repackaged.

## Step 13 — Added Media Hub + made Chat a universal command surface (June 13, 2026)

Two additions, both consistent with how Orrery already works.

**Media Hub (a seventh tab):** a playground for image and video generation on the user's own media-model keys, with an optional fully-local backend (Stable Diffusion / ComfyUI) so generation can happen entirely on-device — reinforcing the privacy story. The user writes a prompt, picks a model, tunes parameters (aspect, seed, count, negative prompt), and can turn a reference image into a new image or a short video. A key design choice: generated **files live in a local media library on disk, and only their details** (prompt, model, settings, file path, tags) go in the database — large media never gets stored as database blobs. Any asset can be pinned into Chat or used as a step in an Automation. It slots in as Phase 6.

**Chat as a universal command surface:** the user can now reach any feature straight from the chat box — type `/` or just ask to generate media, run an automation, start or query an agent, build or refresh a dashboard, or search their data. This was natural to add because Chat, Automations, and Agents already share one tool registry; Chat simply gets access to that same registry. The important rule, written into the security file: this is glue, not a bypass. Every action triggered from Chat goes through the exact same protections as everywhere else — approval gates for sensitive or destructive actions, scope limits, read-only defaults, and personal-data redaction. "The user asked in chat" never skips a check. It slots in as Phase 7 (after the features it invokes exist, and after Agents so the approval/scope machinery is proven). Power moves to Phase 8.

Updated the mockup (the seventh tab with a create panel and a reusable media gallery, plus a command row in the chat composer showing `/image`, `/video`, `/run automation`, `/agent`, `/dashboard`), the plan, and all the skill references — including a new security section (§11) covering generative-media hard lines (never any sexual content involving minors; no non-consensual or deepfake imagery of real people), provenance metadata as good practice, and the command-surface "no bypass" rule. The skill was re-validated and repackaged.

## Step 14 — Set up the real project workspace (June 14, 2026)

Turned the pile of planning documents into an actual buildable project. What we did and why:

- **Gave Orrery its own home.** The files had been sitting in a generic "New folder"; we made the Orrery folder a proper, self-contained project (its own version history, separate from everything else on the machine) and moved every document into the place it belongs — the plan, this log, and the design mockup at the top level; the architecture, security, roadmap, and conventions guides packaged as the project's built-in rulebook so they load automatically whenever someone works on Orrery.
- **Wrote the one missing rulebook page.** The rulebook referred to a "conventions" page (how code is written, and the single repeatable way to add a new workflow node, dashboard widget, or agent ability) that had never actually been written. We wrote it, matching the others.
- **Prepared the workbench.** Added the list of building blocks the app needs, a one-command local database setup (Postgres with vector search built in, via Docker — chosen over a manual install because the vector piece is otherwise fiddly on Windows), an example settings file, a readable setup guide, and the project's ignore rules.
- **Guarded against a known trap.** This project lives inside OneDrive, which has a habit of corrupting the large "downloaded building blocks" folders by syncing them mid-write. We added small scripts that keep those folders safely outside OneDrive, the same fix that worked on an earlier project.

We also confirmed the machine is ready: Python, Node, and Git are installed; Docker is the remaining piece to install for the database.

**New working rule (from the user):** document *each* step here as it happens, not only at the end. This log is now updated continuously as we build.

## Step 15 — Wrote the Phase 0 skeleton code (June 14, 2026)

Wrote the first working version of the app's spine — the smallest thing that proves every part connects, with no real features yet. In plain words:

- **The launcher (`app.py`).** Running one command does the whole start-up dance: find the database (checking the secure keychain first, then the local settings file, and asking you once if neither has it), prepare the database on first run (turn on vector search and create the tables the built-in task scheduler needs), start the local web server and the background worker together, and open the desktop window pointed at them. The window and the backend only talk to each other privately on this machine, and they share a fresh one-time password each launch so nothing else on the computer can sneak in.
- **The backend pieces**, each kept to one job: settings, secure key storage (with a helper that hides passwords before anything is ever printed to a log), the database connection, the first-run preparation, the task scheduler, and the web server — which for now answers a single "are you healthy?" question (used to show the connection light) and serves the screen.
- **The screen (a small React app).** A star-map styled shell with the seven tabs down the side (Chat, Data, Dashboards, Automations, Agents, Media Hub, Settings) and a live "Database connected" indicator. Each tab is a placeholder that names the phase its real version arrives in. This is the visible proof that screen → backend → database all talk.

None of this is run yet — that needs the database and the installed building blocks, which is the next step. We wrote it carefully against the security rules (secrets only in the keychain and never logged, the backend locked to this machine and password-protected, only the database setup is allowed to change the database) so the habits are right from the very first file.

## Step 16 — Built the workbench and verified the code (June 14, 2026)

Installed everything the app needs and checked the code as far as possible without the database yet.

- **Installed the building blocks**, kept safely outside OneDrive: the Python environment and its libraries, and the screen's libraries (with the folder automatically moved out of OneDrive and linked back, the way that protects against the syncing problem). We also wrote down the *exact* versions that got installed, so this set-up can be reproduced precisely later.
- **Built the screen** into the small bundle of files the app serves, and switched the default so a single command (`python app.py`) shows the finished screen — the live-reload mode is still there for when we're actively changing the look.
- **Checked the code runs** and caught two genuine bugs early, both specific to running on Windows:
  - The background worker must not try to grab the operating system's stop-signals — only the program's main part is allowed to do that, so left unfixed it would have crashed the worker on start-up.
  - Windows' default way of handling many-things-at-once is incompatible with how we talk to the database; we switched to the compatible mode at start-up. Without this the app couldn't have reached the database *at all* on this machine, even with everything else perfect. We confirmed the fix: a connection attempt now fails only because the database isn't running yet, not because of the incompatibility.
  We also confirmed the screen is served correctly and the login-token check works (requests without the one-time token are refused), and that passwords are masked before anything is logged.
- **Installed Docker** (the tool that runs the local database). It downloaded and installed, but it needs a one-time **restart of the computer and a first launch** before it works — that's the only thing left before we can run the whole app.

Everything else is ready and waiting. The moment Docker is running, one command starts the database and a second opens the app window.

## Step 17 — Phase 0 is done: the app runs (June 14, 2026)

The skeleton is alive. We started the local database and ran the app, and the whole spine worked end to end on the first real run.

- **The database is up.** Docker started cleanly (no restart was needed — the Windows virtualization layer it relies on was already in place). One snag along the way: Docker's command-line tools weren't yet on the system's search path in our working session, so the first attempt couldn't fetch the database image; pointing it at Docker's own folder fixed it. The database came up healthy: PostgreSQL 17.10 with vector search switched on.
- **One command, the whole app.** Running the launcher did everything we designed: found the database (with the password safely hidden in the log), prepared it on first run (vector search on, task-scheduler tables created), started the local web server and the background worker, and opened the desktop window.
- **Proven, not assumed.** The window opened, loaded the seven-tab screen, and the screen successfully asked the backend "are you healthy?" and got a yes — which only works if the screen, the private one-time password, the local server, and the database are all wired correctly. We confirmed the window stays open and the app keeps running.

**Phase 0 is complete** — the definition we set ("one command opens a window served by the local backend, talking to the database") is met. Everything from here builds on a spine we know works.

## Step 18 — Built the real screen to match the design (June 15, 2026)

Replaced the plain placeholder shell with the full interface, rebuilt faithfully from the approved design mockup — the star-map look and all seven tabs (Chat, Data, Dashboards, Automations, Agents, Media Hub, Settings) with the same layout, colours, and wording.

- **Faithful, not approximate.** Every tab was recreated to match the mockup: the chat thread with its data-citation chip and code block, the data connections and table browser, the dashboard widgets and charts, the automation canvas with its glowing nodes and the animated "constellation" lines between them, the agent goal/scope/budget cards and live activity feed, the media create-panel and gallery, and the settings rows.
- **Fonts now travel with the app.** Instead of fetching the typefaces from Google (which would break offline and quietly "phone home"), we bundled them into the app itself — keeping the local-first promise. This was the only new building block added, and it earns its place for that reason.
- **Design now, wiring later — on purpose.** This is the visible shell; the real behind-the-scenes behaviour of each tab still arrives in its own phase. The one thing actually live is the small database light, which reflects the real connection.
- **Proved it on screen.** Confirmed the interface renders correctly. (A wrinkle worth noting for the future: ordinary screen-capture photographs the app's window frame but not its web content, because of how that content is drawn; we verified instead by loading the very same screen in a separate browser and by the app's own signals — the fonts loading and the live connection check firing, which only happen if the screen actually rendered.)
- Small extra: the address can name a tab (used for that verification), a harmless convenience.

## Step 19 — Phase 1: Chat actually works (June 15, 2026)

The Chat screen is no longer a mock — it's connected to real models and the database.

- **Hold a real conversation.** Add your provider key in Settings, pick a model, type a message, and the reply streams in word by word. Every message is saved in your database, and your past chats reappear in the list (titled automatically from your first line).
- **One menu, every provider.** A single library talks to Anthropic, OpenAI, Google, or a local model — switching is just picking from the model menu. We turned that library's usage-reporting off so nothing phones home (local-first).
- **Keys handled to the security floor.** Your key lives only in the operating system's keychain. The screen only ever sees a masked preview (e.g. `sk-ant-••••3kF9`) and a "in keychain" tick — never the real value, which is never written to a file, a log, a prompt, or the reply. The key is read only at the instant of the call and handed straight to the provider. If a provider rejects a request, we show a plain message and never echo anything that looks like a key.
- **New storage.** Two tables were added to your database for chats and their messages; like all schema, they're created on first run, with nothing else allowed to change the structure behind your back.
- **Proved it.** Created chats and confirmed they persist and reappear; confirmed that with no key you get a clear "add your key in Settings" message instead of an error; confirmed saving a key returns only a masked preview. (Streaming a real answer needs your own key — the pipe is built and waiting for it.)

## Step 20 — The model list is now live and key-gated (June 15, 2026)

Two fixes the user asked for, plus a real-provider test.

- **You only see models you can actually use.** The model picker no longer shows a hard-coded list. When you add a provider's key, Orrery asks that provider what models your key can use and shows exactly those — including models newer than this assistant's own knowledge. Add an OpenAI key → OpenAI's current models appear; add Anthropic → Claude's appear; run a local model → it appears. A provider with no key simply doesn't show up. (Verified: with only an OpenAI key attached, the picker listed 32 current OpenAI chat models and nothing else.)
- **Settings tidy-up + clearer guidance.** The "Save" button now sits neatly beside the key box, and if a chat is pointed at a model whose provider has no key, a plain amber note explains it and the picker steers you to one that works.
- **Tested against a real provider.** Using a real OpenAI key, we confirmed the whole chat path is correct — it authenticates, sends the request, and handles the response and errors properly. The test also revealed that this particular account has no remaining credit, so getting actual replies needs billing enabled on the account (or just use a different provider, or a local model). The integration itself is sound.

## Step 21 — Shorter model menu + standard chat controls (June 15, 2026)

Two rounds of polish the user asked for.

- **A tidy, current model menu.** Instead of listing every model a key can touch (the OpenAI key alone exposed 32), the picker now shows about **four current ones per provider** — the latest flagship, a fast one, a "pro", and a dedicated **reasoning** model — chosen live from what your key unlocks. (For the test OpenAI key that landed on gpt‑5.5, a reasoning model, a fast mini, and the pro.) Claude shows its current Opus/Sonnet/Haiku/Fable; local models show whatever you have.
- **The controls people expect from a chat tool.** You can now **Stop** a reply mid‑stream — and Orrery keeps whatever was written so far — **Regenerate** the last answer, **Delete** a chat (with a confirm), and **Copy** any reply. All verified against the live backend.

## Step 22 — File & image attachments in Chat (June 15, 2026)

The first of the agreed Chat upgrades.

- **Attach images and text files.** The paperclip in the composer now opens a file picker; attached items show as chips before you send and as thumbnails (images) or chips (files) on your message. Images are sent to the model to look at; text files are read in alongside your question. Verified end to end — an image attachment is accepted and the message is saved with a small "📎 filename" note so your history shows what was attached.
- **Scope for now:** images and text files. **PDF reading is the next addition** (it needs either a provider's native document support or a small parser, per the agreed native-plus-neutral approach).
- Also removed the placeholder sentence in the empty chat, as requested.

## Step 23 — PDF reading (June 15, 2026)

Attach a PDF and the model reads it. Orrery pulls the text out of the PDF **on your machine** and passes it to whichever model you're using — so it works the same on a cloud model or a local one (the neutral path of the agreed native‑plus‑neutral plan). Verified on a real PDF (≈4,700 characters extracted). A scanned/image‑only PDF (no text layer) says so plainly instead of failing.

- **New building block:** a small, widely‑used pure‑Python PDF reader (`pypdf`) — noted here per the dependency rule; it keeps PDF parsing local (nothing sent to a separate service) and earns its place for that.
- **Also this round:** clearer provider error messages — an out‑of‑credit account now reads *"You're out of API credit for this provider…"* instead of a raw library dump; and the empty‑chat **star pattern** was restored (only the text sentence was removed).

## Step 24 — Security review + an automated safety net (June 15, 2026)

Before opening the most dangerous part of the app (Phase 2 connects to your real database), we did a deep pass on safety and added tests — the user flagged this as essential.

- **Security review (against the project's pre-ship checklist).** The dangerous areas are sound today: your keys live only in the operating system's keychain and the app only ever shows a masked preview, never the real value; error messages are scrubbed so they can never echo a key back; the app listens only on this machine and every request carries the one-time session password; and there is no place yet where untrusted text could turn into a database command. The genuinely risky capabilities — querying your real database, autonomous agents, running code — aren't built yet, so there's nothing unsafe wired in. We wrote down the rules that **must** hold the moment Phase 2 adds real database access: every query uses bound parameters (never built by gluing text together), read-only is enforced at the connection itself (not by trusting the query text), every query has a time limit and a row cap, and personal data is screened before anything is sent to a cloud model.
- **Automated safety net.** Added 21 tests that guard the security-critical behavior so a future change can't quietly break it: keys never leave the backend, error text never contains a key, connection-string passwords are masked, the model list only shows what your key unlocks, and attachments are handled safely. They run in ~2 seconds with `pytest`.
- **Pinned versions.** Recorded the exact version of every building block (`requirements.lock.txt`) so the app rebuilds identically and a surprise upstream change can't silently alter behavior.

## Step 25 — Tidied the code; trimmed the model menu (June 15, 2026)

- **Comments cleaned up (user request):** removed the long, verbose comment blocks and module headers across the code, while **keeping the short one-line explanation comments** that say a useful "why" (e.g. "masked, never the raw key", "off the main thread → no signal handlers"). The DEVLOG remains the project's plain-words record, so nothing was lost. Updated the project's own conventions to match, and confirmed the 21 tests still pass and the screen still builds.
- **Model menu trimmed (earlier user request, now standard):** each provider shows ~4 current/latest models rather than the full list, and the set always includes a reasoning model (OpenAI's o-series, the Claude tiers, a Gemini thinking variant). A model still appears only when its key is attached.

## Step 26 — Phase 2 (part 1): connect a database, browse it read-only (June 15, 2026)

The Data tab is real. You can connect one or more of your own databases by pasting a connection string; Orrery tests it, saves it, and lets you browse any table's rows. This is the most dangerous part of the whole app, so it was built to the security rules from the first line — and each rule was verified, not assumed:

- **Read-only, enforced by the database itself.** Orrery runs every query inside a read-only transaction, so any attempt to write — insert, update, delete, or create a table — is refused by Postgres, not by Orrery trying to guess intent from the text. Confirmed live: all three write attempts were blocked.
- **Time-limited and capped.** Every query has a time limit and a maximum number of rows returned, so a huge or slow table can't hang or flood the app.
- **Table names are allow-listed.** A table name is checked against the database's real list and quoted safely before use, so a crafted name can't become an injection. An unknown table returns "not found".
- **The password never leaves the keychain.** The connection string (which holds your database password) is stored only in the OS keychain; the app keeps just a redacted label (host/database) and never sends the password back to the screen. Confirmed: the password does not appear anywhere in the app's responses.

Added tests for the safety helpers (safe quoting, password redaction, value handling); the suite is now **25 green**.

## Step 27 — Accounts & Keys and Claude plan route (June 16, 2026)

Added the account/subscription layer the user asked for, without weakening the existing API-key path.

- **Settings now says Accounts & Keys.** OpenAI, Anthropic, and Google API keys still work the same way as before: they are saved in the operating system keychain and the screen only sees a masked preview. Ollama is still local and needs no key.
- **Claude plan access is the first official subscription-backed route.** Orrery can now check whether Claude Code is installed, signed in with a supported Claude plan, and ready for the official credit path. If it is, the user can connect it locally and Chat shows **Claude plan · default** as a model option.
- **No unsafe subscription shortcuts.** Orrery does not store OAuth/session tokens, browser cookies, or web-session data, and it does not scrape private web UIs. The Claude plan route runs through the official Claude Code path with tools disabled and no session persistence. ChatGPT Pro and Gemini subscription rows are shown as unavailable with clear explanations, because those subscriptions do not pay for third-party model API calls.
- **Routing is explicit.** Existing `openai/...`, `anthropic/...`, `gemini/...`, and `ollama/...` model IDs still go through the existing provider path. The new `claude_plan/default` model goes through its own adapter. Text and locally extracted PDF/text attachments are allowed; image attachments ask the user to pick an API-key vision model instead.
- **Tests were added for the dangerous parts.** Provider status cannot leak secrets, unsupported subscription routes stay unavailable, the Claude plan model only appears after readiness is verified, and chat routing sends the new model ID through the Claude plan adapter.

## Step 28 — Phase 2 (part 2): "use my data" with on-device embeddings (June 16, 2026)

Orrery can now answer from your own documents, and the document text stays on your machine.

- **Collections in the Data tab.** Create a collection, drop in text or PDF files; Orrery splits each into overlapping chunks and turns them into embeddings **on your machine** (a small local model — no PyTorch, nothing uploaded). Each collection shows its chunk count.
- **Hybrid retrieval.** A question is matched two ways at once — by meaning (vector search) and by keywords (the database's full-text search) — and the two rankings are fused, which finds the right passage more reliably than either alone.
- **"Use my data" in Chat.** Toggle it on, pick a collection, and your question is answered from those documents, with the sources named in the reply (e.g. it cited `[facts.txt]`). Verified end to end: it returned the correct fact and the source.
- **Personal data screened before the cloud.** When the answer uses a cloud model, the retrieved snippets are run through a personal-data scrubber first (emails, phone numbers, card/SSN-like numbers, IPs are masked). For a local model nothing is sent out, so nothing is masked. Confirmed: a document with an email and an IP still answered the (non-personal) question correctly, with the personal bits redacted on the outbound path.
- **New building block, justified:** a lightweight on-device embedding library (ONNX-based, no PyTorch) — it keeps embeddings local, which is the whole point. Tests were added for the chunker and the redactor; the suite is now **39 green**.

Also confirmed this round: the new **Claude plan (account) route works for real** — a "use my data" question answered through the connected Claude plan, citing its source. And a boot hang was traced to a leftover app process from repeated restarts (not a code bug); a clean single instance starts normally.

## Step 29 — Chat quality: formatted replies, model switching everywhere, effort control (June 16, 2026)

Chat now reads and behaves like the tools people are used to.

- **Replies are properly formatted.** Answers render as rich text: headings, lists, tables, links, and — most importantly — **code in real code blocks** with a language label, syntax colours, and a one-click **Copy** button. Inline `code` is styled too. Verified live: asking for a Python function returned a `python` code block that rendered with highlighting and a working Copy button.
- **Switch model on any route, any time.** The model menu lists every route you actually have — API keys *and* the Claude plan account — and you can change the model mid-chat; the choice is saved to that conversation. The Claude plan route now offers four picks (default, Opus, Sonnet, Haiku) instead of one, so the subscription path is no longer locked to a single model.
- **Effort setting.** A per-chat control lets you ask for more or less thinking — *auto, low, medium, high, extra high*. It's saved with the conversation and passed to models that support a reasoning-effort dial; models that don't simply ignore it (the unsupported setting is dropped, never sent as an error). Verified: effort persists across reload (`high` set, `high` read back).
- **Why this was safe to add.** Formatting is done by a well-known Markdown renderer on the screen only; nothing about how replies are generated or stored changed. The whole suite stays **39 green** (one test's stub was updated to match the richer Claude-plan call signature), and the screen still builds.

## Step 30 — Speed pass: faster startup, model loading, and status checks (June 16, 2026)

The app was feeling slow, so this round focused on latency without removing features or loosening security.

- **Model loading no longer waits on unnecessary account checks.** The model picker skips Claude Code probing unless the Claude plan was already connected locally. Settings still does the full readiness check, because that screen needs to tell the user whether the plan can be connected.
- **Provider discovery runs in parallel.** If OpenAI, Anthropic, Google, and Ollama are all configured, Orrery now asks them at the same time instead of waiting for one provider before starting the next. API keys are still read only from the keychain, and model results are still key-gated.
- **Blocking Claude Code checks moved off the API loop.** Settings and Claude-plan connect/disconnect checks now run in a worker thread, so a slow local Claude Code status command does not stall other local API calls.
- **Health checks are cached briefly.** The database light still updates, but repeated `/api/health` calls no longer run a fresh database query every time when a recent answer already exists. Startup still forces a real database check.
- **Chat opens faster.** Conversations load first; model discovery and document collection loading happen alongside it. That means the user can see the current chat while slower provider/model work finishes.
- **The frontend bundle was split by tab.** The main app bundle dropped from about 535 kB to about 153 kB, and each tab now loads its own code when needed. This keeps the same tabs and behavior, but avoids paying for every screen at launch.

Verified after the speed pass: **40 backend tests green**, and the screen still builds.

## Step 31 — Clean restart and safer startup logs (June 16, 2026)

Restarted Orrery so the user could test the speed pass and the existing features in the running desktop app.

- **A stuck earlier app process was stopped and restarted.** The fresh run connected to Postgres, confirmed the app tables and job-queue schema, started the local API, started the worker, and opened the Orrery window.
- **One security issue was caught during restart.** The temporary startup log captured the window URL, which includes the per-session local token. That token should never be written to a file, so Uvicorn access logging is now disabled. The app still logs important startup events, but it no longer logs request URLs containing the session token.
- **Verified after the fix.** The backend test suite stayed green (**40 passed**), Orrery started cleanly, and the new startup logs show `API ready` and `Opening Orrery window` without the session token.
- **Only expected warning seen:** Ollama model discovery failed because no local Ollama server answered on `localhost:11434`. That does not break OpenAI/Claude/Google/API-key routes or the rest of the app; it only means local Ollama models will appear when Ollama is running.

## Step 32 - Better chat actions and code formatting (June 16, 2026)

Chat now has the extra prompt controls the user asked for, and the formatter is more forgiving when a model forgets Markdown fences.

- **Prompt actions on user messages.** Every user prompt now has **Copy prompt**, **Edit**, **Resubmit**, and **Rewrite**. Edit moves the prompt back into the composer; Resubmit sends the same prompt again; Rewrite asks the current model to return a cleaner version of the prompt.
- **Assistant actions are clearer.** Replies now say **Copy reply**, and the latest reply still supports **Regenerate**. There is also a **Resubmit prompt** action on the latest reply, so the user can quickly rerun the prompt that produced it.
- **A proper multiline composer.** The chat box is now a textarea: **Enter** sends, **Shift+Enter** creates a new line, and file attachments still work the same way.
- **Stronger code formatting.** The backend now tells models to answer in GitHub-flavored Markdown and to fence code, commands, SQL, JSON, logs, config, and file contents with language tags. The UI also repairs common unfenced code output before rendering, so missed code blocks still become labeled, copyable blocks for many languages instead of plain text.
- **Prompt formatting too.** User prompts now render with Markdown as well, so pasted code/config in the user's own message is easier to read and copy without changing what is sent to the model.

## Step 30 — Faster chat, many more models, and full conversation memory (June 22, 2026)

A big round of chat improvements, driven by three things the user asked for: speed, more model choices, and the chat remembering everything.

- **Speed: the Claude-plan route now streams.** Before, an account (OAuth) reply was produced in full behind the scenes and then appeared all at once — so it felt slow. Now the words stream in as they're written, the same as the API-key models. (There's still a short start-up pause whenever an account route is used, because it goes through the official Claude Code program, which has to launch each time; the API-key routes don't have that pause and stay the fastest.) The sign-in check that used to run on every screen is now remembered for a short while, so the app stops re-checking constantly.
- **Many more models, your choice.** Added **Mistral (EU)** and **DeepSeek** as built-in API-key providers, and — the big one — a universal **"Add a custom model"** option that works with *any* OpenAI-compatible service: Qwen, Kimi (Moonshot), GLM (Zhipu), OpenRouter, Together, Groq, or a local server. One-click presets fill in the address for the popular ones; you just paste your key and the model name. Every key still lives only in your system keychain, never in a file.
- **You pick which models show up.** Settings now has a **Models** section listing everything you could turn on, each with an on/off switch; the chat model menu shows **only the ones you've turned on**. Turning on a provider (adding its key, connecting Claude plan, or adding a custom model) switches its models on automatically, and you can fine-tune from there. Existing Claude-plan users keep their menu — the app seeds it once on upgrade.
- **The chat now remembers the whole conversation, including files.** Earlier, a question would only "see" earlier messages — but an attached file's contents were forgotten after the turn you sent it on. Now the full text of attached text/PDF files is kept with the conversation, so you can ask about a document many messages later and it still knows. (Replies and code were already remembered; this closes the file gap. Images are noted by name in later turns; re-reading an image across turns will come with the image-model work.)
- **Small fix:** user message bubbles were clipping their text at the top after the recent formatting change; corrected so the message and its action buttons show fully.
- **Why this was safe:** no new dependencies (the model library already speaks all these services); keys stay in the keychain and are never shown or logged; the new "remembered context" is the user's own data living in the user's own database, which is exactly where Orrery keeps everything. Test suite is **45 green**, including new checks for custom-model routing, the keychain namespace for custom keys, and Mistral model curation.

**On "log in instead of API keys" for ChatGPT and others:** the honest finding is that a safe, *official* subscription login only exists where the provider ships a real command-line tool — that's Claude (already wired) and, in principle, ChatGPT via OpenAI's `codex` and Gemini via Google's `gemini`. On this machine `gemini` isn't installed, and `codex` is both currently mis-configured and heavyweight (it's a full coding agent, so it's slow for plain chat) — which clashes with the "speed matters" goal. So the fast, official answer for everything other than Claude is **API keys**, which now cover OpenAI, Google, Mistral, DeepSeek, and anything OpenAI-compatible. We can revisit a ChatGPT login later if the speed trade-off is acceptable.

## Step 34 - A context window for every chat (June 22, 2026)

Long conversations no longer have to send their entire history to the model every time.

- **A setting on each conversation.** Chat now has a **context** selector beside the model and effort controls: Auto, 8K, 16K, 32K, 64K, 128K, or 256K. The choice is saved with that conversation and comes back when it is reopened.
- **Auto preserves the old behavior.** Existing chats default to Auto, which keeps sending the full remembered history exactly as before. Nothing changes unless the user chooses a limit.
- **Limits do not delete messages.** A fixed window only controls what is included in the next model request. The full conversation and attached-file text stay saved and visible in the database.
- **Recent complete turns win.** Orrery estimates the request size locally, reserves 25% of the selected window for the answer, and removes the oldest complete user/assistant turns first. The newest user turn is always kept. Image data is counted with a fixed estimate instead of counting large base64 bytes.
- **No new dependency.** The estimate uses a conservative local calculation, so no tokenizer package, network request, or provider-specific code was added. API validation rejects context values outside the supported range.
- **Verified and applied.** The backend suite is now **50 green**, the production UI build succeeds, the additive database migration completed, and Orrery was restarted with the session-token protection still active.

## Step 35 - Context choices simplified and raised to 1M (June 22, 2026)

The context selector now has only the three larger choices the user wanted: **128K, 256K, and 1M**.

- **1M is the default and maximum.** New chats start at 1M, and older chats that still had the previous Auto value are upgraded to 1M.
- **Only the requested choices are accepted.** The API now rejects other context sizes, so the screen and backend cannot drift apart.
- **The existing safety behavior is unchanged.** Orrery still reserves 25% for the answer, removes only the oldest complete turns from the model request, and never deletes saved messages or attached-file text.
- **Provider limits still apply.** The setting is Orrery's maximum request budget; a selected model with a smaller native context window may reject a request before 1M.
- **Verified and applied.** All **50 backend tests** pass, the production UI build succeeds, older chats were backfilled, and Orrery restarted with its local session-token protection active.

## Step 36 — Security hardening pass 1 (June 22, 2026)

Went through the live app looking for ways it could be attacked, and fixed what we found. Plain-words summary (full report: `../security/SECURITY_HARDENING.md`):

- **Closed a "make the app fetch the wrong thing" hole.** The new *Add custom model* feature lets you type the address of a model service, and the app then calls it. We now check that address first: only normal web addresses are allowed, and we block tricks that try to point the app at the computer's own internal/cloud-metadata services. Plain (unencrypted) addresses are allowed only for models running on your own machine. Checked both when you add the model and again each time it's used.
- **Stopped a possible key leak into logs.** One provider (Google) was being called with the secret key in the web address; if that call failed, the error written to the log could contain the key. The key now travels in a header instead, so it never appears in a URL or a log.
- **Hardened the local door.** The app's private password check is now done in a way that doesn't leak hints through timing, oversized requests are refused, and every response carries standard browser-safety headers (including a strict content policy that blocks injected scripts).
- **Belt-and-suspenders on error messages.** Any stray key-looking text in a provider error is now scrubbed before it could ever reach the screen.
- **Confirmed the already-safe parts:** database access stays read-only and parameterized with table-name allow-listing; the model command-line bridges never run through a shell; secret keys are only ever shown masked.

What's explicitly *not* done yet, by design: the code-running feature (Phase 4) must arrive sandboxed, and deeper prompt-injection defenses come with Agents (Phase 5). Tests added for all of the above; suite is **60 green**.

## Step 37 - Official CLI account routes completed (June 22, 2026)

Finished the account work that was left half-complete, while keeping every API-key and local-model route intact.

- **Codex / ChatGPT plan now connects correctly.** Orrery detects the installed official Codex CLI, verifies its saved ChatGPT sign-in, and works around an invalid old `service_tier` value without editing the user's config file. Requests run in an empty temporary folder with a read-only sandbox, no approval prompts, and an ephemeral session.
- **No OAuth-token copying.** Claude Code, Codex, and Gemini CLI keep ownership of their own login files. Orrery launches the official executable and stores only a small local `connected` marker in the operating-system keychain. It never reads browser cookies, vendor auth files, refresh tokens, or private web sessions.
- **The warnings now match official documentation.** OpenAI documents ChatGPT sign-in and `codex exec`, so the old blanket "unsupported and may ban you" claim was removed. Google officially ended consumer free, Google AI Pro, and Google AI Ultra service through Gemini CLI on **June 18, 2026** and moved those users to Antigravity CLI. Orrery keeps Gemini CLI only for supported enterprise/API-key accounts and does not pretend Antigravity is integrated before Google publishes a stable restricted headless interface.
- **Connect requires a deliberate acknowledgement.** Settings explains that these are local coding-agent CLIs, may be slower than API models, use plan limits, and can load normal CLI configuration on older releases. The Connect button stays disabled until the user checks the acknowledgement box.
- **Chinese API presets were refreshed.** DeepSeek remains built in. The custom-model presets now use current official examples for Qwen (`qwen3.7-max`), Kimi (`kimi-k2.7-code`), and GLM (`glm-5.2`), while preserving the universal OpenAI-compatible form for any other provider.
- **Safety and speed checks.** Required CLI safety flags are checked before a route becomes available, Codex login status is cached briefly so the model picker does not repeatedly launch the CLI, failed runs clean up their temporary folders, and Gemini JSONL output ignores tool events. The full backend suite is **68 green** and the production UI build succeeds.

## Step 38 - Orrery logo and Git repository hygiene (June 22, 2026)

Updated Orrery's visual identity and tightened what can be pushed to Git.

- **A clearer Orrery mark.** Replaced the small constellation with an orbital **O**: an amber core, ice-blue orbit, and small satellite inside the existing dark UI palette. The same mark now appears in the sidebar, browser favicon, design mockup, and native desktop icon.
- **Native app icon included.** Added versioned PNG and multi-size Windows ICO assets and wired the ICO into pywebview startup. The app still starts normally if an icon file is missing.
- **Git ignores now cover real project risks.** Expanded the ignore rules for Python/Node caches, virtual environments, UI builds, coverage output, logs, runtime data, local databases, temporary files, IDE metadata, credentials, and generated package artifacts.
- **Local agent permissions stay local.** The shared Orrery development skill remains source-controlled, while `.claude/settings.local.json` is ignored because it contains machine-specific permissions. The generated `docs/orrery-development.skill` package is also ignored because its editable source already lives under `.claude/skills/`.
- **Important source remains included.** `.env.example`, package lockfiles, Python requirement locks, source code, tests, documentation, and branding assets are not ignored.

## Step 39 - Production-ready CLI setup and icon controls (June 22, 2026)

Fixed the account-route problem the user found and made the setup understandable without terminal knowledge.

- **Codex plan access works for real.** Orrery was passing its config repair before `codex exec`, so Codex read the user's old invalid `service_tier = "priority"` first and stopped. The override now goes in the correct place. A live request through Orrery returned `ORRERY_PLAN_OK`.
- **The right Codex executable wins.** Orrery now prefers the official Windows Package Manager installation over stale npm shims and editor-extension copies. On this machine it found the official Codex `0.142.0`, verified ChatGPT sign-in, and connected the plan successfully.
- **Version-aware models.** Current Codex uses GPT-5.5. An older compatible CLI automatically uses GPT-5.4 mini for the default/fast route instead of failing; the old saved fast-model id remains compatible.
- **Install, update, sign in, check, then connect.** Settings now shows the installed CLI version and the exact next action. With consent, one click installs or updates only the hard-coded official WinGet packages (`OpenAI.Codex` and `Anthropic.ClaudeCode`). Sign in opens only the vendor executable's fixed login command in a separate console. A refresh button rechecks status, and Connect runs a small safe readiness request before saving Orrery's local marker.
- **No token handling changed.** Orrery still never reads or copies Claude/Codex login files. Installer package ids and login arguments are backend constants; the screen cannot submit a command, package, URL, or shell text.
- **Message actions are icons.** Copy, edit, resubmit, rewrite, regenerate, and resubmit-last-prompt are now compact familiar icons with hover tooltips and accessible labels.
- **Navigation icons were upgraded.** Every main tab now uses a consistent Lucide symbol, and Agents has a distinct bot mark instead of the previous orbit symbol.
- **New dependency, justified and pinned.** Added `lucide-react` for standard, accessible interface icons instead of maintaining more hand-drawn SVGs. The dependency audit reports zero known vulnerabilities.
- **Verified.** Both Claude Pro and Codex/ChatGPT plan status are connected. The complete backend suite is **74 green**, the production UI build succeeds, and the live Codex route produced the expected reply.

## Step 40 - Responsive Settings and honest Claude limit errors (June 22, 2026)

Rebuilt Settings without removing any of its existing controls, and fixed the Claude failure message that made a normal plan limit look like a broken connection.

- **Settings is organized instead of split into two long columns.** General, Accounts, Models, Usage, Integrations, and Feedback now have a dedicated category navigation. Desktop uses a compact side rail; tablets and phones use a horizontally scrollable category bar.
- **Small-screen controls stay usable.** Provider rows and their buttons stack on narrow screens, long provider messages wrap, API-key editing can wrap safely, and Defaults becomes one column. Browser checks at 1440, 900, and 390 pixels found no page overflow, off-screen controls, or overlapping account actions.
- **Every existing setting remains.** API keys, Claude/Codex/Gemini CLI routes, Ollama, model visibility, custom models, spending caps, MCP placeholders, defaults, and feedback are still available under the new categories.
- **Company branding is complete.** General can enable a company header with an uploaded logo, name, tagline, and short details. Saving updates the visible header immediately. Logos are limited to local PNG, JPEG, WebP, or GIF uploads up to 1 MB; remote URLs and SVG data are rejected.
- **Claude did not lose its connection.** The live Claude Code account was authenticated, but Claude returned a provider session-limit response with a reset time. Orrery now reads JSON result errors even when the CLI exits normally and preserves Claude's exact session-limit/reset message instead of showing a generic sign-in failure.
- **Verified.** The full backend suite is **77 green**, the production UI build succeeds, and the responsive screen checks pass.

## Step 41 - Project folders reorganized for growth (June 22, 2026)

Reorganized the repository so related files stay together and new work has an obvious home, without changing how Orrery behaves.

- **The backend now follows ownership.** `backend/core` holds configuration, database, migrations, models, and queue setup. `backend/providers` holds model accounts, routing, and the catalog. `backend/features` holds Chat, Data, RAG, usage, and feedback. `backend/security` holds the keychain, privacy redaction, and network guards. The API entry point stays easy to find at `backend/api.py`.
- **Tests mirror the backend.** Provider, feature, and security tests now live in matching folders, while API tests and shared fixtures remain at the test root.
- **Documentation has clear shelves.** Plans, history, research, security records, and design references now have separate folders under `docs`, with `docs/README.md` as the index. The DEVLOG is now `docs/history/DEVLOG.md`.
- **Setup and assets are grouped.** OneDrive setup helpers live in `scripts/setup`, desktop icons live in `assets/desktop`, and generated documentation packages live under the ignored `docs/generated` folder.
- **Standard entry files stayed at the root.** `README.md`, `app.py`, dependency files, `.env.example`, and `docker-compose.yml` remain where Python, npm, Docker, and new contributors expect them.
- **Navigation notes were added.** Backend, tests, scripts, assets, and documentation each have a short README explaining what belongs there.
- **No behavior changed.** All imports, setup commands, icon paths, project rules, and documentation links were updated to the new locations.
- **A move-sensitive startup path is now protected.** Moving configuration into `backend/core` initially made it look for `.env` one folder too low. The project-root calculation was corrected and a regression test now verifies that it always resolves to the launcher directory.
- **Verified and running.** All **78 backend tests** pass, the production UI build succeeds, the moved setup command works, the API serves the built screen, and the Orrery desktop window is open and responsive.

## Step 42 - Trusted PDF, Word, and Excel exports from Chat (June 23, 2026)

Added the first safe file-production feature: a completed Chat reply can now be downloaded without running any model-written code.

- **One download control, three formats.** Every saved assistant reply has a compact download icon beside Copy. Its menu offers PDF, Word, and Excel.
- **Formatting is reconstructed locally.** Orrery parses the saved Markdown itself and preserves headings, paragraphs, bold/italic text, lists, quotes, code blocks, dividers, and tables in PDF and Word.
- **Excel handles prose and tables.** The workbook includes a structured Reply sheet, and every Markdown table gets its own worksheet with headers, wrapping, filters, and practical column widths.
- **Spreadsheet formulas are treated as text.** Values beginning with `=`, `+`, `-`, or `@` (including after leading spaces) are neutralized before entering a workbook, preventing formula injection.
- **Only saved replies can be exported.** The frontend sends the conversation and assistant-message IDs. The backend verifies that the message belongs to that conversation and is an assistant reply; it accepts no file path and executes no supplied code.
- **Resource limits are explicit.** Extremely large replies or tables are refused with a clear error instead of consuming unbounded memory.
- **New dependencies, justified and pinned.** ReportLab writes PDF, python-docx writes Word, openpyxl writes Excel, and markdown-it-py supplies the restricted Markdown parser. All work is local; no export content is sent to another service.
- **Verified with real saved content.** All **86 backend tests** pass, dependency checks are clean, the production UI build succeeds, the download menu fits desktop and phone widths, and a saved Orrery reply produced readable PDF, Word, and Excel files through the real database-backed export service.

## Step 43 - Safe code-rendered images, visible reasoning routes, and one-click local models (June 23, 2026)

Expanded Chat and local model support without allowing models to execute arbitrary code.

- **Chat can create code-rendered images.** `/image` and natural requests such as "create an image", "draw a diagram", or "design a logo" use the selected text model to write SVG vector markup. The result appears inside the conversation and can be downloaded as SVG.
- **The image path is declarative, not executable.** Orrery rejects scripts, event handlers, CSS, `foreignObject`, embedded or remote files, links, animation, XML entities/DOCTYPE, unsupported tags/attributes, and oversized output. It never runs model-written Python, JavaScript, shell commands, HTML, browser automation, or filesystem code.
- **Image artifacts are saved with the assistant message.** Reopening the conversation restores the rendered SVG from the user's own Postgres database. Standard text/PDF/Word/Excel reply exports continue to work as before.
- **Claude thinking control is real.** The official Claude Code adapter now passes the per-chat effort choice through `--effort` when the installed CLI exposes it. Default, Opus, and Sonnet labels identify adaptive thinking; Haiku is labeled as the fast route.
- **ChatGPT plan routes identify reasoning.** The existing Codex configuration already passed `model_reasoning_effort`; the model labels now make that behavior visible instead of hiding it behind generic names.
- **A new Local Models tab manages Ollama end to end.** With explicit consent, Orrery installs only the fixed official WinGet package `Ollama.Ollama`, starts the local service, streams model-download progress, activates downloaded models in Chat, hides/shows them, and removes them from disk.
- **Reviewed one-click starters.** Qwen 3 4B, Gemma 3 4B, DeepSeek R1 8B, and Llama 3.2 3B are offered with size/capability guidance. Orrery still discovers every Ollama model already installed instead of limiting the model list to four.
- **Chat handoff is direct.** Clicking Chat beside an installed local model opens Chat with that model preferred; local routes remain keyless and use the existing Ollama/litellm chat path.
- **Security boundaries remain fixed.** Installer package ids and service commands are backend constants, no user-provided shell command is accepted, model names are validated, subprocesses use argument arrays with no shell, and provider/account secrets are unchanged.
- **Verification expanded.** New tests cover SVG allowlisting, malicious SVG rejection, fixed-package Ollama installation, model-name validation, local status, API acknowledgement, corrupt artifact handling, and Claude effort forwarding. All **101 backend tests** pass, the production UI build succeeds, the production npm audit reports zero vulnerabilities, Python dependencies are consistent, the migration is applied, and the restarted app is serving normally.

## Step 44 - Requested file previews and model-resilient SVGs (June 23, 2026)

Made Chat's generated-file path match what the user actually asked for, instead of treating every reply as every file type.

- **Only the requested file type shows.** If the user asks for a PDF, only a PDF chip appears; if they ask for Excel and CSV, those two appear; normal answers show no file controls. The recognized safe formats are PDF, Word/DOCX, Excel/XLSX, PowerPoint/PPTX, CSV, Markdown, text, HTML, and JSON.
- **Click the file to preview it.** The file chip itself opens a preview in the side panel. The small download icon beside it saves the real file. PDF previews use the PDF renderer; Office/text formats use an Orrery-built HTML preview from the same cleaned content.
- **Exports use the requested artifact, not the whole chat wrapper.** The backend now looks at the preceding user prompt, strips common assistant wrapper lines like "Here is..." / "Let me know...", extracts Markdown tables for spreadsheet/CSV files, extracts fenced JSON/HTML/Markdown/text when present, and then renders only that body.
- **More formats without extra dependencies.** Existing PDF, Word, and Excel exports remain. CSV, Markdown, text, HTML, JSON, and dependency-free PPTX export were added. Spreadsheet-style outputs still neutralize formula-like values before they enter CSV/XLSX.
- **SVG generation is less model-fragile.** The SVG prompt is stricter, validation gets one extra repair attempt, safe opacity/font attributes are allowed, and if the model repeatedly returns invalid SVG, Orrery creates a safe built-in SVG fallback instead of executing code or failing with no visual.
- **Security boundary is unchanged.** The backend still accepts only known formats, verifies the message belongs to the conversation and is an assistant reply, never accepts file paths, never executes model-written code, and keeps previews temporary.
- **Startup check.** Launch reaches database migration and `API ready on http://127.0.0.1:8765`, but this machine currently fails when pywebview initializes WebView2 with `0x8000FFFF (E_UNEXPECTED)`. Orrery now gives WebView2 a writable ignored `tmp/webview2` profile path, but the remaining failure is in the local WebView2 runtime/session rather than the export code.
- **Verified.** All **109 backend tests** pass, the production UI build succeeds, `pip check` reports no broken requirements, and the production npm audit reports zero vulnerabilities.

## Step 45 - ChatGPT plan model auto-selection (June 24, 2026)

Made the ChatGPT/Codex subscription route resilient to OpenAI model updates and old local Codex installs.

- **Default is now automatic.** Orrery no longer forces a pinned GPT model for `chatgpt_plan/default`; it runs the official Codex CLI without `-m`, so Codex chooses the newest compatible model for that installed CLI and signed-in account.
- **Old Codex installs stay usable.** If the installed Codex version is below Orrery's recommended version, Settings still prompts for an update, but the default route keeps working through Codex's own compatible model choice.
- **Pinned models are guarded.** The explicit GPT-5.5 route is hidden from the model catalog when the local Codex CLI is too old to pin it. The existing fast-route id remains compatible with the older GPT-5.4 mini fallback.
- **Failures recover once.** If Codex rejects a pinned model as unknown, unavailable, unsupported, or requiring a newer CLI, Orrery retries the same request once through the automatic default route before surfacing a safe error.
- **Settings explains the behavior.** The ChatGPT-plan account row now states that default chats let Codex choose the newest model the installed CLI supports.
- **Security boundary is unchanged.** Orrery still uses the official CLI only, never reads or stores Codex OAuth/session tokens, and keeps the same ephemeral read-only execution mode.
- **Verified.** The account-route tests are **25 green**, the full backend suite is **113 green**, and the production UI build succeeds.
## Step 46 - Higher-effort file generation and better decks (June 24, 2026)

Raised the quality floor for generated files after the file path started producing weak decks and documents.

- **File jobs now use higher reasoning automatically.** A file request no longer inherits low or auto chat effort. Standard model routes are promoted to high effort, and Claude plan routes use extra-high effort when the CLI supports it.
- **The sandbox prompt is stricter.** The model is told to behave like a production document designer, avoid placeholders and generic templates, use the best library for the requested format, validate generated files in code, and create only the file types the user asked for.
- **PowerPoint fallback is designed, not default.** The structured `orrery-doc` PPTX builder now creates a widescreen deck with a designed cover, accent rail, stronger typography, slide numbering, speaker notes, and cleaner spacing instead of bare default PowerPoint layouts.
- **Regression tests cover the fix.** New tests verify effort promotion, production-grade file instructions, sandbox output handling, and the designed widescreen PPTX fallback.
- **Note.** The attached `Planet_Earth_preview.pdf` path was not accessible from this runtime, so the fix was based on the generation code path and reproducible builder behavior rather than visual inspection of that exact file.

## Step 47 - Code-execution file generation, thinking, perf, and public repo (June 24-25, 2026)

A large block of work spanning file generation, the chat experience, performance, and shipping the repo.

- **File generation now runs code in a sandbox.** Model writes Python -> it runs in a locked-down Docker
  container (`sandbox/Dockerfile` -> `orrery-sandbox` image; `backend/features/sandbox.py`: `--network none`,
  memory/CPU/PID caps, read-only root + tmpfs, non-root, all caps dropped, 60s timeout) -> files come back.
  `backend/features/filegen.py` runs a plan->code->run->fix loop (<=3 retries feeding the traceback) at high
  reasoning effort. `backend/features/files.py` stores outputs on disk; served via `/api/files/{id}` + `/preview`.
- **Always returns a file.** If code-exec misses, `chat._deliver_docspec` falls back to the deterministic
  `docgen` builder (designed PPTX, real spreadsheets, PDF/DOCX) so a real file is delivered, not a text reply.
- **Office previews.** `backend/features/filepreview.py` renders pptx/xlsx/docx to HTML (slide cards / tables /
  document) since browsers can't show Office binaries inline.
- **Skills.** `backend/features/skills.py` + `skills/*.md` inject per-request guidance into the prompt.
- **Thinking.** API reasoning is surfaced from `reasoning_content` / `reasoning` / `thinking_blocks`; the
  Claude-plan CLI route streams `thinking_delta`. Shown in a collapsible "Thought process" block.
- **Chat UX.** Markdown renders live while streaming; `Markdown` is memoized so completed messages don't
  re-parse per token. Three-star "working" pulse with ~52 rotating phrases.
- **Detached generation.** `chat.start_detached` / `observe` / `cancel_run` run the reply in a background task
  so it finishes + saves even if the client navigates away; `POST /conversations/{id}/stop` cancels explicitly.
- **Database settings.** Settings -> Database connects/tests/reconnects/disconnects any Postgres server.
- **Codex.** CLI updated to 0.142.x. Limit detection fixed (precise phrases) and the real reset-time message
  is extracted cleanly and de-duplicated.
- **Refactor.** `Chat.jsx` split into `chatHelpers.jsx` + `chatWidgets.jsx`.
- **Dependency security.** pypdf 6.13.3, pydantic-settings 2.14.2.
- **Public repo + security.** Published to github.com/zaidt156/Orrery (now private). `.gitignore` excludes
  `docs/`, `.claude/`, `skills/`, all `.env*`; history purged + neutral commit identity. Apache-2.0 LICENSE,
  README with logo + badges + stack, SECURITY/CONTRIBUTING/CODE_OF_CONDUCT.

## Step 48 - Reported bugs cleared + production-hardening P0 (June 25-26, 2026)

Worked through the June 25 bug list and began an external production-readiness plan
(`architecture_imp/architecture Improvments.md`, gitignored). Roughly in order:

- **New logo.** Processed the user's PNG with Pillow (border flood-fill -> transparent, enclosed white
  specks cleared, cropped, resized) to `assets/orrery-brand.png`; verified on a dark composite; wired into
  the README. (Note: Windows is case-insensitive - `Orrery-logo.png` == `orrery-logo.png`; processing in
  place + a cleanup `rm` deleted the original once. Output now uses a distinct name.)
- **`code_images.py` was duplicated end-to-end** (the syntax error was the seam between two copies) ->
  cleaned to one module. Added the new "no visible text unless the prompt requests it" SVG rule's tests.
- **Reasoning panel redesign (plan P0 #12; user chose "summaries only").** Raw model reasoning is NEVER
  streamed or persisted. `backend/features/reasoning_trace.py` emits `reasoning_event` (live work-trace
  steps) + `reasoning_summary`; `ReasoningPanel` renders them. Inline `<think>` is stripped from answers.
- **DB lifecycle (plan #3-5).** `get_engine()` normalizes the URL; `reset_database_engine()` +
  `save/clear_database_url_and_reset()` switch connections live (no restart); the Procrastinate queue is now
  lazy (`get_queue_app()` / `reset_queue_app()`) so importing it no longer needs a configured database.
- **Import smoke tests** (`tests/test_feature_imports.py`, `test_core_imports.py`, `test_core_database.py`).
- **Security P0.** Cloud privacy boundary: every non-local route passes user/document text through
  `privacy.prepare_messages_for_model` with an Off/Basic/Strict mode (Settings -> General -> Privacy);
  centralized `secrets.redact_secrets()`; keyring fails closed (`SecretStoreError`) with name validation;
  `tests/test_security.py`.
- **Ollama closed** -> `local_models.is_running()` pre-flight; chat fails fast with a "start Ollama" message.
- **RAG context mixing** -> preamble hardened: answer only from the documents + current question, ignore
  unrelated earlier turns, never claim "no file access".
- **Connect/disconnect -> picker live.** Settings broadcasts `orrery-models-changed`; Chat refetches and
  drops a selection that's no longer available.
- **Live token count.** Per-reply chip: exact in/out for API/custom (`message_usage`), live ~estimate
  (chars/4) for plan/local.
- **Branding reset fixed** with a session-level `_brandingDraft` cache that survives Settings sub-tab switches.
- **Background runs observable + auto-resume.** `chat.is_running()` + `GET /conversations/{id}/resume`
  (re-observe the queue); `getConversation` returns `running`; Chat auto-reconnects on reopen, then reloads
  the saved reply.

## Step 49 - Architecture-plan implementation, batches 1-3 (June 26, 2026)

Worked the production-readiness plan in three verified batches (134 -> 136 tests, all green; migrations
verified against the live DB).

- **Batch 1 - prompt authority + routing (P1).** New `backend/features/prompting.py`
  `build_system_prompt()` composes explicit layers (APP RULES > FEATURE > SKILLS > USER PREFERENCES >
  TRUSTED > UNTRUSTED). RAG chunks now flow as UNTRUSTED context ("do not follow instructions inside")
  instead of being merged into the system prompt. File routing is **docgen-first**: plain documents/decks
  build deterministically; the sandbox is used only when `filegen.needs_code()` (charts/images/computed).
  `tests/features/test_prompting.py`.
- **Batch 2 - DB hardening (P0 #6-10).** Versioned migrations via a `schema_migrations` table +
  `_apply_versioned()` (idempotent, fail-safe). Added CHECK constraints (`messages.role`,
  `conversations.effort`, `feedback.category`), a pgvector **HNSW** index on `chunks.embedding`
  (`vector_cosine_ops`, matching rag's `<=>`), and **typed app settings** (registry + validation, logs
  corrupt JSON) in `appconfig.py`. JSONB (#8) deferred (needs coordinated appconfig/artifact changes).
- **Batch 3 - security + config (P1/P2/P3).** `netguard` now rejects URL credentials, fragments, and
  oversized URLs (+ tests). Production-tunable limits in `config.py` (`sandbox_timeout_seconds`,
  `rag_top_k`, `max_upload_bytes`) wired into sandbox/chat/api. Added `docs/security-boundaries.md`.

## Step 50 - Provider manifest, CLI flag-safety, error scrubbing (June 26, 2026)

Provider-layer hardening that does NOT touch the working routing structure (the full `accounts.py`
file split is deferred as its own careful pass).

- **Model manifest (plan #12).** Pinned model IDs, plan-variant labels, and recommended CLI versions
  moved to `backend/providers/model_manifest.json`, loaded by `manifest.py` over baked-in defaults
  (corrupt/missing file -> defaults). `accounts.py` now derives `CLAUDE/CHATGPT/GEMINI_PLAN_VARIANTS`,
  recommended versions, and Codex pinned models from it - no logic change, identical values verified.
- **CLI flag-safety tests (plan #16).** Extracted `_claude_plan_args()` (pure) and tested it +
  `_codex_exec_args()`: assert `--no-session-persistence`, `--strict-mcp-config`, disabled tools,
  `--ephemeral`, `-s read-only`, `--skip-git-repo-check`, `--ignore-user-config`, and that the auto
  route sends no pinned `-m`. `tests/providers/test_cli_safety.py`.
- **CLI error scrubbing (plan #14).** Claude/Codex/Gemini plan errors pass through
  `_scrub_secrets()` (-> `secrets.redact_secrets`) before becoming user-facing, so raw CLI stderr can't
  leak paths/tokens.
- **Spend metering honesty (plan #19).** Unknown/custom pricing now sets `pricing_known=False`
  (streamed in `message_usage`) instead of implying the call was free.

## Step 51 - Observability + storage/validation hardening (June 26, 2026)

- **Request IDs + structured logs (plan #14/#15).** `backend/core/observability.py`: a contextvar request
  id (set in the API auth dependency) flows into every log line as `[id]` (incl. inside SSE generators);
  `log_event()` emits `event key=value` lines with secret-shaped values scrubbed. Wired at chat
  generation start/fail and model-discovery fallback.
- **Custom-model validation (plan #18).** `catalog.add_custom_model` enforces label/name length, an
  allowed model-name charset, and a duplicate (base_url, model) check; the API surfaces failures (and SSRF
  rejections) as a clean 400. `tests/providers/test_catalog.py`.
- **Generated-file TTL cleanup (plan #18).** `files.cleanup()` prunes generated files past
  `generated_file_ttl_hours` (default 7d) on boot. `tests/features/test_files.py`.
- **Discovery freshness (plan #15).** `_cached` now tracks live/cache/fallback per provider and logs a
  structured `model_discovery_fallback` event instead of silently serving a stale list.

## Step 52 - Window flash, file naming, file-gen quality (June 26, 2026)

User-reported polish after the architecture work:

- **No more flashing console windows.** Under pythonw.exe every CLI/docker probe (claude/codex/gemini
  status + version checks, ollama, docker) popped its own console window. New `backend/core/proc.py`
  wraps `subprocess.run`/`Popen` with `CREATE_NO_WINDOW`; all call sites in accounts/local_models/sandbox
  route through it. (Fixed the variable-name clash the blind replace created where the local result var
  was also named `proc`.)
- **Files named after the document, not the chat.** `docgen.render_spec` now derives the title + filename
  slug from the spec's own `title` (the model sets it), falling back to the conversation title only if
  absent. Applies to the PDF/DOCX body title too.
- **File-gen quality bar.** Strengthened the orrery-doc instructions with an explicit QUALITY BAR (specific
  descriptive title; decks 6–12 slides with 3–6 substantive bullets + notes; full paragraphs for docs;
  complete sheet data) so docgen-first output matches the depth of the code-exec path. Effort already uses
  `filegen.quality_effort` (high/xhigh) on both paths.

## Step 53 - File-gen validation, dynamic thinking, Task Brain, new logo (June 27, 2026)

- **File generation hardening.** Applied user-provided rewrites of `filegen.py` (backend validation:
  open/parse each generated file, reject placeholders/thin content, enforce requested format, retry on
  failure) and `docgen.py` (normalize+validate the untrusted JSON spec, reject placeholders, reopen
  rendered Office/PDF/CSV, rich PPTX layouts). Document-title naming preserved in both.
- **Dynamic thinking.** `ReasoningCondenser` (reasoning_trace.py) condenses the model's ACTUAL reasoning
  into short multi-step lines instead of canned text; removed the predefined event + summary.
- **No flashing console windows.** `backend/core/proc.py` wraps all subprocess calls with
  CREATE_NO_WINDOW; accounts/local_models/sandbox routed through it.
- **Task Brain (OpenClaw pattern).** Researched OpenClaw + Hermes; user chose the unified task ledger.
  New `tasks` table + `taskbrain.py` + wired into detached chat runs (timeout-isolated) + boot orphan
  reconcile + `GET /tasks` / `POST /tasks/{id}/cancel` + an Activity panel in the chat sidebar. Verified
  live (Docker Desktop had stopped — Postgres was down; restarted it).
- **New logo.** `assets/orrery-logo.svg` — clean orbital mark (gold sun, tilted orbits, planets) +
  wordmark on a dark brand panel; the disliked 3D render was removed.

## Open issues (updated June 27, 2026)

- **OpenRouter provider**, **skills-for-everything** (self-improving skills), and the remaining plan items
  (accounts.py split, JSONB) are the next requests.
- **Speed.** A 10-slide deck took ~5 min on API at high effort; only *perceived* speed can improve (the user
  is firm: never cut effort). docgen-first routing should make plain decks near-instant - verify quality.
- **Re-verify in the live app** with the user: the RAG isolation fix, branding header, and deck quality
  now that decks route through docgen first.
- **Architecture plan remainder (still open):** provider adapter interface + `accounts.py` split (the big
  refactor); per-provider model **manifest** (move pinned model IDs/CLI versions out of code); discovery
  **freshness metadata**; CLI **flag-safety tests**; custom-model validation lifecycle; **spend metering**
  known/unknown pricing; **structured logs + request IDs**; JSONB columns; user-safe error structure;
  sandbox security tests; generated-file cleanup; DB read-only role guidance.
- **Ollama-free local models** (own runtime) - large; collaboration deferred.

## Next up

The provider-layer refactor is the largest remaining plan item (split `accounts.py` into per-provider
adapters behind a `ProviderAdapter` interface + a model manifest) - do it as its own careful pass so model
routing never breaks. Then observability (structured logs + request IDs) and **web search with visible
citations**. Photorealistic image/video adapters and the reusable media library remain on the Media Hub roadmap.

## Step 54 - Capability planner, automatic skills, audio artifact base (June 27, 2026)

- **Task routing architecture.** Added `docs/planning/TASK_ROUTING_ARCHITECTURE.md`: one planner first,
  skills loaded by task type, sandbox for artifact creation, safe work trace instead of raw reasoning, and
  project/voice as next capability layers.
- **Backend capability router.** Added `backend/features/taskrouter.py`, returning a `TaskPlan` for chat,
  file, image, audio, and project requests. Chat now emits a planning step before choosing the route.
- **Image requests no longer depend on UI commands only.** Standalone "draw/design/create an image/logo"
  prompts now route through the backend sanitized SVG generator even when the user does not type `/image`.
- **Audio-file foundation.** Filegen now recognizes explicit audio/WAV/MP3 file requests, prompts the
  sandbox to synthesize WAV with standard-library audio tools, and validates WAV/MP3 outputs before delivery.
- **More skills.** Added image, audio, sandbox, and project skill playbooks so models get the right procedure
  automatically instead of making the user specify every mode.

## Step 55 - Project workspaces wired into chat (June 27, 2026)

- **Projects are real data now.** Added a `projects` table plus nullable `conversations.project_id`, with
  additive migrations so existing chats remain untouched.
- **Project API.** Added list/create/get/update/delete project endpoints and conversation assignment endpoints.
- **Trusted project context.** Chats attached to a project now load that project's description/instructions as
  trusted context in the prompt builder, separate from untrusted RAG/uploaded document text.
- **Projects UI.** Added a Projects tab for creating/editing project metadata, viewing project chats, and jumping
  back into Chat. Chat also has a project selector in the header so new and existing chats can be grouped.
- **Project intent routing.** Clear prompts like "create a project workspace for Acme" now create the project
  and attach the current chat automatically through the backend router.
- **Safety boundary preserved.** Project text is user-owned preference/context only; it does not grant tools,
  bypass sandbox limits, or override app rules.

## Step 56 - Project hierarchy and refreshed logo (June 27, 2026)

- **Project hierarchy.** Project listing now returns nested chat summaries, and the Projects tab shows each
  project with its chats underneath instead of a flat editor-only view.
- **Scoped project chat start.** Projects now has "New chat" actions that open Chat with the selected project
  already attached, so the first user message creates the conversation inside that project.
- **Chat handoff.** Chat understands project-scoped startup from the Projects tab and does not auto-open the
  most recent global chat in that case.
- **Logo refresh.** Updated the full `assets/orrery-logo.svg` and the in-app rail mark with a sharper orbital
  identity, better depth, and cleaner planet/orbit geometry.

## Step 57 - Architecture docs pass and planner telemetry (June 27, 2026)

- **Docs reconciled before more hardening.** Re-read the tracked docs, local architecture implementation file,
  security references, and skill playbooks so already-implemented production items are not duplicated.
- **Planner telemetry.** Added route telemetry rows for chat/file/image/audio/project decisions, final outcomes,
  sandbox fallbacks, and deterministic-builder fallbacks.
- **Privacy boundary preserved.** Route telemetry records only capability metadata and sanitized outcome details;
  it does not store prompts, attachments, generated code, document text, or secrets.
- **API surface.** Added an authenticated `/api/task-routes` summary endpoint for future Settings/debug views.

## Step 58 - Simplified Orrery app logo refresh (June 28, 2026)

- **Simpler visual direction.** Used the user's orrery reference as inspiration, then reduced it to a product mark:
  an orbital O, central amber sun, two small orbit nodes, and a plain Orrery wordmark.
- **Logo changed across app surfaces.** Updated the README/full logo SVG, web favicon SVG, in-app rail logo component,
  native desktop PNG, and multi-size Windows ICO used by pywebview.
- **Fallback page aligned.** The backend-only placeholder now renders the current Orrery mark when the production UI
  build is missing.
- **No feature behavior changed.** This was a visual asset pass only; auth, chat, routing, sandboxing, and storage paths
  were left untouched.


## Step 59 - Project files and project chat window (June 28, 2026)

- **Per-project files.** Each project now has its own document collection. Files of any text-bearing type
  (PDF, Word, Excel, PowerPoint, text, code) are extracted, chunked, embedded, and answered from automatically
  by chats inside that project. Images and other binaries are skipped instead of polluting search with base64.
- **Projects rebuilt as a workspace.** The project page is now a name top-bar, a collapsible details/instructions
  area, a files panel, and a message window: typing a first message starts a new chat inside the project.
- **Layout fix.** Fixed a flexbox overflow (composer button was clipped) and a height-chain gap so the view fills
  the window.
- **Safety boundary preserved.** Uploaded project files are untrusted context used for facts only, exactly like RAG.

## Step 60 - Two-layer reasoning work trace (June 28, 2026)

- **What the user sees.** Replaced the single flat "how this was produced" list with a two-layer activity panel,
  like a high-end AI workspace: a collapsed outer card (what Orrery is doing, in one line) that expands into a
  step timeline (choose route -> load context -> run tool/sandbox -> validate -> done) plus a closing summary.
- **Universal by design.** Every visible line is written by Orrery about its own actions, not the model's private
  thoughts, so the panel looks and behaves identically whether the model is reached by API, a CLI plan, or a local
  model that exposes no reasoning at all.
- **Stronger privacy.** The think-stream no longer condenses raw model reasoning into visible text; it only strips
  inline think blocks and counts how much hidden reasoning was removed. Raw chain-of-thought never reaches the screen.
- **Consistency.** Normal chat, file, image, and project routes and the regenerate path all emit the same trace.

Next up: decide the next roadmap step - Deep Reasoning Mode selector (Quick/Standard/Deep/Max) wired to effort and
trace detail, or centralizing the SSE event helpers, or the JSONB metadata migration. Pending: push local commits
(Projects files, reasoning trace) to main once approved.


## Step 61 - Deep Reasoning Mode (June 28, 2026)

- **Reasoning depth as a named mode.** Added Quick / Standard / Deep / Max, mapped onto the existing
  per-chat effort value so no database change was needed. The mode drives three knobs at once:
  the provider's reasoning effort, the file-generation repair budget (Quick 1 -> Max 4 attempts),
  and how the depth is labelled in the activity card.
- **Single source of truth.** A new reasoning module owns the mode<->effort mapping so the UI,
  chat, and file generator all agree.
- **Next up:** generalize the sandbox into a chat code-interpreter so the model can write and run
  Python for any computational/'strange' request and hand back the output. Then Deep Research.


## Step 62 - Chat code-interpreter: the model writes and runs Python (June 28, 2026)

- **Run real code for real answers.** When a request is best solved by computation (math, data
  wrangling, parsing, simulation, a chart, a generated file), the model now writes a fenced
  `orrery-run` Python block and ends its turn. Orrery runs it in the existing locked-down sandbox
  (no network, capped, isolated), captures stdout and any files written to out/, feeds that back,
  and the model finishes the answer from the actual output. The loop is bounded.
- **Universal.** It relies only on a fenced text convention, so it works on any model/connection
  (API, CLI plan, or local) without native tool-calling. When the sandbox image is not built, chat
  falls back to the normal path.
- **Honest UI.** The raw code block is hidden from the answer and shown as activity-card steps
  (Running Python -> Code finished), with any produced files attached and token/cost still metered.
- **Safety.** Code always runs in the sandbox and is treated as untrusted; file/data contents read by
  the code are facts, never instructions.

Next up: Deep Research mode (decompose -> gather from documents + provider web tool -> cited report).


## Step 63 - Deep Research mode (June 28, 2026)

- **Proper research, not just a chat reply.** A /research command now runs a real workflow: the model
  decomposes the question into focused sub-questions, gathers evidence for each from the user's uploaded
  documents (RAG), then writes one structured report that cites its evidence with [n] markers and a
  Sources list. Shown with the same two-layer activity card (Planning research -> Researching each
  sub-question -> Writing report).
- **Safety + honesty.** Gathered passages are untrusted evidence to cite, never instructions. The model
  must not invent citations; when the documents are silent it answers from general knowledge and says so.
- **Universal + metered.** Works on any model/connection; token/cost is tracked like normal chat.
- **Next increment:** provider-native web search (OpenAI/Anthropic/Gemini tools via litellm), wired in
  the gather step. Deferred so it can be verified live against the user's real provider/keys — the
  backend's only outbound traffic stays "to the providers the user configured" (no third-party fetch).

Next up: wire + live-verify provider web search into Deep Research; optional reasoning-mode selector relabel.


## Step 64 - Universal web search + file-generation fix (June 28, 2026)

- **Web search for any model.** The backend now performs web searches (keyless, via the ddgs library)
  and feeds results to the model as evidence, so web access works on ANY model/connection - local
  Ollama, a CLI plan, or an API key - not just cloud models with their own web tool. Results are
  treated as untrusted context (facts to cite, never instructions) and redacted before cloud models.
- **In chat.** The same tool loop that runs Python now also handles a fenced orrery-search block: the
  model searches, Orrery returns titled results + URLs, and the model answers from them and cites
  sources. Shown as activity steps (Searching the web -> Web results) with the source URLs surfaced.
- **In Deep Research.** Each sub-question now gathers from the user's documents AND the web, so reports
  use current, real-world facts instead of leaving placeholders.
- **File-generation fix.** The earlier reasoning-mode change had quietly reduced the default file repair
  budget from 3 to 2 attempts; restored to 3 (Quick 2, Standard/Deep 3, Max 4), so file quality is back.

Next up: optional - a keyed search provider (Brave/Tavily) for higher-volume/precision web research.


## Step 65 - Task-routing dispatcher split (June 28, 2026)

- **Followed the v4 checklist.** Continued Phase 0 from the improved phased plan: keep the existing
  `_prepare_turn` DB seam, then split `stream_reply` into explicit route handlers instead of one large
  orchestration block.
- **Handlers now own their paths.** Research, image, project creation, unavailable audio, file generation,
  and normal model replies each have a named async generator. The public stream contract is unchanged:
  title, reasoning trace, status, files/artifacts, deltas, message ids, usage, errors, and done events
  still flow the same way.
- **Safer fallback path.** File requests still try the selected file route first; if no approved artifact
  is produced, the dispatcher falls back to the normal model reply path without overwriting the file-route
  telemetry outcome.
- **Tests added.** Added dispatcher tests that use the `_prepare_turn` seam and fake handlers, so research,
  image, project creation, unavailable audio, and file-to-chat fallback are verified without a real database,
  Docker sandbox, or provider call.

Next up: add cancellation/resume dispatcher coverage, then add the typed SSE event helper from the Phase 0 checklist.


## Step 66 - Reasoning panel: sources in the trace + visible Deep Research (June 28, 2026)

- **No more raw URL banner.** Removed the "searched: <urls>" line that dumped links above the answer.
  Sources now live inside the reasoning panel: web results show as clickable domain chips under the
  "Web results" step, plus a combined "Sources" list at the bottom of the expanded panel (document
  names render as plain chips, web URLs as links). They appear when the user opens the reasoning card.
- **Lingering spinner fixed earlier; this builds on it.** The trace reads cleanly: each step resolves
  to a check when the turn ends, and the real query/result detail is shown per step.
- **Deep Research is now discoverable.** Added a "Deep Research" toggle in the chat toolbar next to
  "Use my data". When on, the turn runs the decompose -> gather (documents + web) -> cited-report
  workflow. Removed the easy-to-miss /research chip in favour of the toggle.

Next up: optional keyed search provider; per-step expand/collapse if the trace grows long.


## Step 67 - Real reasoning in the panel + Deep Research in the chatbox (June 28, 2026)

- **Show the model's actual reasoning, live.** ThinkStream no longer discards reasoning; it streams the
  model's real thinking (provider reasoning channel AND inline <think>) into the panel as it happens.
  The reasoning panel now shows that live thinking, the trace line of what was actually done (searched
  the web, ran Python, produced files), the sources used, and a Done state - then stays, rolled up,
  once the answer is finished.
- **Dropped the childish steps.** Removed the "Loaded skills" line; kept only genuine activity.
- **Deep Research moved into the chatbox.** The toggle now sits next to the attach button in the
  composer (not the top toolbar); on = the turn runs decompose -> gather (documents + web) -> cited report.
- **Files: produce the real thing.** File requests now prefer the sandbox whenever it's available, so
  the model writes code to generate an actual downloadable file (real file card) instead of falling back
  to an on-demand export; deterministic docgen remains the fallback.

Remaining: richer file cards (thumbnail + Download-and-open + Download all); persist reasoning across
reloads; per-segment outer reasoning headlines.


## Step 68 - Rich file cards (June 28, 2026)

- **Produced files look like real files.** Generated files now render as a rich card: a file thumbnail,
  the name, a "Type / EXT / size" subtitle, and Preview + Download actions; when a reply produces more
  than one file, a "Download all" button appears. Matches the reference design the user shared.
- Pairs with the earlier change that routes file requests through the sandbox so an actual downloadable
  file is produced (rather than the on-demand export fallback).

Next: persist the reasoning trace across reloads; per-segment outer reasoning headlines.


## Step 69 - Universal model reasoning on every route (June 28, 2026)

- **The root cause:** raw reasoning only appears if the model emits it, and not all models do; the file
  and image routes also weren't all streaming it. So the user often saw only backend narration steps.
- **Universal fix:** every built system prompt now includes a reasoning directive telling the model to
  think inside <think></think> before its output. ThinkStream already extracts that, streams it to the
  reasoning panel as live thinking, and removes it from the final answer. So real reasoning now shows on
  every route that builds a prompt - chat, file/document/deck generation, and Deep Research - on ANY
  model/connection, even ones that don't natively emit reasoning tokens. The strict SVG route is left
  untouched (separate prompt).

Remaining: stream reasoning from the image (SVG) route too; persist reasoning across reloads; per-segment
outer reasoning headlines.


## Step 70 - Reasoning on the image route too (June 28, 2026)

- **Image creation now streams reasoning like everything else.** generate_svg became a generator: it
  applies the reasoning directive, streams the model's <think> reasoning live to the panel, then yields
  the sanitized SVG. _deliver_code_image passes the reasoning through. So chat, file/document/deck,
  research, AND image all show the model's real thinking now - universal across every creation type.

Remaining: persist reasoning across reloads; per-segment outer reasoning headlines.


## Step 71 - Streamlined the reasoning panel (June 29, 2026)

- **Less narration, more real reasoning.** Now that the model's actual thinking streams into the panel,
  the redundant backend narration steps were removed: "Choosing response path", the generic "Thinking" /
  "Generating answer" steps on the chat and regenerate paths. The outer card already states the route.
- **What remains in the trace:** the model's live reasoning, only the meaningful action steps (project
  context / document search when present, web search, code run, file produced), the sources used, and Done.

Next: persist reasoning across reloads; per-segment outer reasoning headlines.


## Step 72 - Reasoning survives reloads (June 29, 2026)

- **Persisted reasoning.** Added a `reasoning` column on messages (additive migration). After a turn
  finishes, the frontend saves the reasoning snapshot (live thinking + trace steps + outer card +
  summary + sources) via POST /conversations/{cid}/messages/{mid}/reasoning; get_conversation returns
  it and the panel is rehydrated on load. So the reasoning no longer vanishes on refresh - it stays,
  rolled up. Verified the round-trip end to end.

Next: context handling fixes for chat + data (RAG) + project files (the dangerous context-mixing issue).


## Step 73 - Context fix: combine data + project files in retrieval (June 29, 2026)

- **The bug:** data ("use my data") and project files were either/or - turning on a data collection
  silently dropped the project's own files, and only one collection was ever searched. So files/data
  often weren't used, and project files seemed "forgotten".
- **The fix:** retrieval now gathers from ALL relevant collections at once - the selected data
  collection AND the project's files - merges + de-duplicates the passages, and redacts for cloud
  models. Project/data files are searched on every turn regardless of chat length, so they don't get
  lost as the conversation grows. Verified live that both a data collection and project files come back
  together.

Next (if still needed): retention of ad-hoc chat attachments across very long chats; matching the
context window to the selected model's real limit.


## Step 74 - Unified context + Ontology tab; roadmap: MCP, user skills, admin (June 29, 2026)

- **Context, unified.** Every chat turn now searches all relevant sources together: the selected data
  collection, the project's files, THIS chat's own uploaded attachments, and any connected ontologies -
  merged + de-duplicated. Chat attachments are indexed into a per-chat collection (new conversations.
  collection_id) so they stay retrievable no matter how long the chat grows. Fixes "files/data not used"
  and "forgets files".
- **Ontology tab (new).** Users build reusable knowledge bases from their own files. Collections now have
  a kind ('collection' vs 'ontology') + a 'connected' flag + description (additive migration). A connected
  ontology is automatically used as standing context in every chat; ontologies are hidden from the Data
  tab and managed in their own tab (create, add files, connect/disconnect, delete). New /ontologies API.
  Verified end to end (create -> add file -> connect -> retrieved in chat).

Logged to the plan for later (not built yet):
- **MCP server support** - connect Model Context Protocol servers as tools/context; untrusted output,
  per-server opt-in.
- **User-creatable skills** - create/upload/edit/enable user skill playbooks from the UI.
- **Admin user + feature flags** - an admin role (SSH-key/token gated) to turn any feature on/off globally.


## Step 75 - Ontology tab: search, per-item connect, connected-now block (June 29, 2026)

- **Pick specific ontologies easily.** Added a search box to filter ontologies by name/description, a
  per-item connect toggle right in the list (search and turn on without opening), and a "Connected now"
  block listing exactly which ontologies are active as chat context (each with a quick disconnect). Makes
  it easy to connect only the one(s) you want when there are many.


## Step 76 - User-creatable skills (June 29, 2026)

- **Bring your own skills.** New Skills tab: create, upload (.md), edit, enable/disable, and delete your
  own instruction playbooks - the same mechanism as Orrery's built-in skills. Each has trigger phrases
  (or "always on"). Enabled user skills are merged with the built-in ones and matched against every
  message, then injected into the model's prompt.
- **How it works.** A new user_skills table (created via create_all); skills.refresh_user_skills() mirrors
  enabled skills into memory so select() stays synchronous; loaded at startup + after any change. Uploads
  reuse the built-in frontmatter parser. New /skills API (list/create/upload/update/delete).
- Verified end to end: trigger match, off-trigger miss, disable drops out, markdown upload parses.

Next: MCP server support; then admin user + feature flags.


## Step 77 - Skills: generate-with-AI, built-in display, MCP config (June 29, 2026)

- Generate-with-AI: describe a skill in plain language and the selected model writes the full playbook
  (name, triggers, body), saved for review/edit. New /skills/generate API.
- Built-in skills shown (read-only) in the Skills tab Overview, marked active.
- MCP config in the same tab: add servers (stdio command or http/sse URL), enable/disable (opt-in),
  remove. New mcp_servers table + mcp module + /mcp API. Config/storage only; connection + tool
  execution into the chat loop is the next increment (needs a live server; untrusted output).


## Step 78 - Admin user + feature flags (June 29, 2026)

- New Admin tab: an admin sets a token (OS keychain) and turns capabilities on/off for everyone -
  code interpreter, web search, Deep Research, ontologies, file generation, Media Hub, Automations,
  Agents, MCP. Once a token is set, changing flags requires it; flags live in app config and reads
  fail open so a glitch never breaks chat.
- Enforced in chat (Deep Research, ontology context, file gen, sandbox code path, web search in the
  tool loop) and reflected in the UI (rail hides tabs for turned-off features). Verified live.


## Step 79 - MCP live connection + tools in chat (June 29, 2026)

- Orrery now actually *connects* to the MCP servers you add (not just stores them). A "Test connection"
  button in the Skills tab launches the server, lists its tools, and caches them (you see the tool
  count). Enabled servers' tools are advertised to the chat model, which can call any of them mid-answer
  (server::tool) - Orrery runs the call and feeds the result back, treated as untrusted context.
- The how: Windows only allows subprocess-based servers on a different async loop than the one the
  database needs, so instead of the heavyweight official client we speak the MCP protocol directly over
  a plain background subprocess (JSON-RPC over stdin/stdout). No event-loop conflict. stdio servers
  (the common npx ones) work today; http/SSE servers are the next increment.
- Gated by the admin "MCP servers" flag. Verified live end-to-end against a real server
  (server-everything): listed 13 tools and the model called `echo` through the chat loop.

Next: http/SSE MCP transport; then the team/multi-user direction (shared-database vs shared-server) the
user is weighing - awaiting their pick before building, since it changes the local-first boundary.


## Step 80 - Team access: lock screen, keys & roles (June 29, 2026)

- Orrery can now be a shared, multi-person workspace. From Admin -> "Set up team access", the founding
  admin names themselves and gets an access key (shown once). After that, any Orrery pointed at the same
  database is **locked** until a valid key is entered; the admin issues a key per teammate from the same
  screen, each marked admin or member, and can revoke (key stops working immediately), change role, or
  delete - with a guard that won't let you remove the last admin.
- A member who unlocks sees the normal app but not the admin controls; admins see the toggles and the
  user list. Each person still keeps their own model API keys on their own machine - the access key is
  only about identity and permissions, never provider secrets.
- Keys are high-entropy and stored only as a hash; the unlock key for a machine lives in the OS keychain.
  Single-user installs are unaffected - no key, no lock, full local access (solo = implicit admin).

Next: tie private data (chats/projects) to the signed-in user so each person sees only their own, while
skills/ontologies/MCP stay shared; then the approval queue (members propose skills/MCP -> admins approve
-> team-wide).


## Step 81 - Team: per-user privacy + approval queue (June 29, 2026)

- **Private by person.** In team mode each teammate now sees only their own chats and projects; shared
  things (skills, ontologies, MCP servers) stay common to everyone. Setting up team access hands the
  founder's existing chats to the founder, so new members start clean. Single-user installs are
  untouched.
- **Propose -> approve.** A member who creates a skill or adds an MCP server has it marked *pending* -
  it isn't active for anyone until an admin approves it. Admins get a "Pending approval" list in the
  Skills tab (Approve / Reject); members see their own items badged "pending". Admin-made (and
  single-user) items are active immediately. This is the "push to admin for approval" flow.
- Verified end-to-end: ownership isolation (a member can't see/open/delete another's chat) and the
  approval gate (a member's skill stays inactive until approved, then goes live).

This completes the team/multi-user feature (identity + keys + roles, lock screen, per-user privacy,
and the approval queue).


## Step 82 - Team privacy hardening: locked clients fail closed (June 29, 2026)

- Fixed a real access-control bug in the team privacy layer: `current_owner_id()` used to return `None`
  for both solo mode and a locked/revoked team client. Some callers treated `None` as "no owner filter",
  which could expose private rows if a client made direct API calls while locked.
- `current_owner_id()` now fails closed in team mode when there is no valid access key, and the API maps
  that to a 403 instead of relying on the UI lock screen. Conversation/project reads, writes, streaming
  starts, resume/stop, exports/previews, project attachment, project files, and reasoning saves now
  preflight or re-check ownership before touching private data.
- Added regression tests for locked team clients, cross-owner conversation access, cross-owner project
  attachment, and the API permission response. Verified the full test suite: 176 passed.


## Step 83 - Stream event protocol cleanup (June 30, 2026)

- Centralized chat/SSE event construction in `backend.features.events` so `delta`, `status`, `error`,
  `done`, `files`, `sources`, `message_id`, usage, project, artifact, SVG, result, and reasoning-delta
  payloads come from one explicit helper instead of scattered raw dictionaries.
- Kept the existing wire format exactly the same for the UI: events still use the current top-level
  keys, so this is a protocol hardening change, not a frontend-breaking migration.
- Moved the main chat generator, detached resume/error path, research, code interpreter, file generation,
  SVG generation, and reasoning delta streams onto the shared helpers. Added tests that lock the helper
  shapes plus dispatcher coverage for missing conversations, resume-without-run, and detached stream
  generator errors. Verified the full suite: 181 passed.

Next: finish the remaining dispatcher hardening by covering cancellation and the full sandbox miss ->
docgen -> plain-reply fallback chain.


## Step 84 - Broader sandbox artifacts + cleaner thinking trace (June 30, 2026)

- Expanded sandbox-backed artifact generation beyond documents/slides/sheets/images/audio basics:
  HTML/web pages, self-contained web apps, video/MP4/WebM, WebP, Markdown, text, JSON, audio, images,
  archives, decks, sheets, PDFs, and Word files are now recognized as file outputs and routed through
  the validated sandbox path when code is needed.
- Upgraded the sandbox image with offline audio/video tooling (`ffmpeg`, `espeak-ng`,
  `imageio`, `imageio-ffmpeg`) so strong models have real Python-accessible tools for narration/audio
  and generated video without web access.
- Added backend validators for self-contained HTML, JSON, WebP/image formats, basic MP4/WebM signatures,
  and kept WAV/MP3/archive/document validators in the same approval gate. HTML with external scripts,
  CDNs, file URLs, or unsafe references is rejected before preview.
- Audio requests such as narration now route to the file-generation sandbox instead of the old
  unavailable voice-status path. Generated audio/video files can be previewed directly from the file card.
- Cleaned up visible thinking: hidden provider reasoning and `<think>` scratchpad text are stripped by
  default; the reasoning panel now relies on public work-trace events such as writing artifact code,
  running the sandbox, validating output, repair attempts, files, and done.

Next: structured input/workspace/output directories plus explicit manifest capture for every sandbox run.


## Step 85 - Windows release package fixed (July 1, 2026)

- Fixed the Windows release packaging bug that uploaded only `Orrery.exe` from a PyInstaller onedir
  build. That exe needs the bundled `_internal` folder beside it, including `python312.dll`, so the old
  GitHub asset could not start after download.
- The GitHub release workflow now builds an explicit onedir package, copies the full `dist/Orrery`
  folder into `Orrery-Windows`, validates the Python runtime, bundled UI, bundled skills, assets,
  Docker compose file, sandbox Dockerfile, launcher, and Windows notes, then publishes only
  `Orrery-Windows.zip`.
- Added `run-orrery.bat` to the release package so Windows users can start the included PostgreSQL
  service, build the sandbox image, and launch the app from one entry point. The docs now warn not to
  copy or publish the executable by itself.
- Added a local `scripts/build-windows-onedir.ps1` builder that reproduces the GitHub package and
  performs the same completeness checks before creating `release/Orrery-Windows.zip`.
- Packaged resource paths now understand the difference between bundled read-only files and writable
  runtime files, so the frozen app can find its UI, skills, model manifest, icon, `.env`, WebView data,
  and generated-file directory in the right places.
- Test discovery now ignores generated `build`, `dist`, and `release` folders so bundled third-party
  tests inside local release packages do not pollute the Orrery test suite.


## Step 86 - Windows release: bundled queue SQL (July 1, 2026)

- Fixed the next packaged-startup failure after the full onedir release: Procrastinate loads its SQL
  files from package data at runtime, and PyInstaller had not bundled
  `_internal/procrastinate/sql/queries.sql`.
- The Windows workflow and local release builder now collect Procrastinate data and package metadata
  explicitly, then validate both `procrastinate/sql/queries.sql` and `procrastinate-*.dist-info`
  before publishing the zip.


## Step 87 - Dispatcher fallback tests + sandbox run manifests (July 1, 2026)

- Finished the next production-hardening checklist item for the chat dispatcher. Tests now cover the
  full file route fallback chain: sandbox miss -> deterministic docgen success, sandbox miss -> docgen
  miss -> normal model reply, plus detached run resume and cancellation bookkeeping.
- Added structured sandbox run metadata without changing the user-facing `./out` contract. Every run now
  has `input`, `workspace`, and `out` directories, and `sandbox.run_code()` returns a sanitized manifest
  with run id, layout, resource limits, exit status, timeout state, and output filenames/sizes.
- `filegen` carries those sandbox manifests through success and final failure results so the backend can
  explain artifact generation without exposing prompts, generated code, logs, raw file data, or secrets.
- Updated the file-generation prompt and architecture doc to describe the new directory contract. Verified
  focused backend coverage: `tests/features/test_chat.py` + `tests/features/test_filegen.py` = 37 passed.


## Step 88 - Windows release runtime probe + interactive setup (July 1, 2026)

- Fixed the release process for the Windows onedir package without bumping the public version number.
  The GitHub workflow now uses the same local builder script, pins release packaging to Python 3.12.0,
  and overwrites the existing release asset for the same tag instead of requiring a new tag.
- Added `Orrery.exe --packaging-probe`, a fast frozen-build check that loads the pywebview/pythonnet
  desktop runtime before a zip can be published. This catches the `Python.Runtime.Loader.Initialize`
  crash during packaging instead of letting a broken zip reach users.
- The release package now includes `setup-orrery.bat` with an interactive first-run menu: use included
  Docker PostgreSQL, enter a custom PostgreSQL URL, build/refresh the sandbox image, or start only.
  `run-orrery.bat` remains the normal launch path after setup.
- The local and CI builders now collect pythonnet/clr_loader explicitly, copy their package metadata,
  validate their runtime files, run the packaged probe from both `dist/` and `release/`, and then zip
  the complete `Orrery-Windows` folder.


## Step 89 - macOS packaging scaffold (July 1, 2026)

- Added a macOS release path without changing the app architecture: PyInstaller builds `Orrery.app`,
  copies Docker/Postgres/sandbox assets, adds Terminal-friendly setup/run helpers, and writes
  `release/Orrery-macOS.zip`.
- Added a `Build macOS Release` GitHub Actions workflow. On version tags it can attach
  `Orrery-macOS.zip` beside the Windows zip; manual runs upload the zip as a workflow artifact.
- Made runtime paths macOS-aware so packaged builds write `.env`, WebView data, and generated files
  beside `Orrery.app` instead of inside `Orrery.app/Contents/MacOS`.
- Extended the packaged `--packaging-probe` to check bundled UI/skills/assets and to load the macOS
  pywebview Cocoa backend. This keeps missing resources or broken desktop-runtime imports from reaching
  users.
- Documentation now distinguishes Windows preview packaging from macOS preview packaging. Remaining
  release work: sign/notarize macOS builds and validate architecture coverage on GitHub's macOS runners.


## Step 90 - Windows release: Qt desktop runtime (July 1, 2026)

- Replaced the Windows packaged desktop backend with Qt WebEngine so the release no longer depends on
  the fragile pythonnet/.NET WinForms bridge that failed with `Python.Runtime.Loader.Initialize` after
  extraction.
- The packaged health probe now loads the same Qt WebEngine backend Orrery uses at runtime. The local
  builder runs that probe from both `dist/Orrery` and the final `release/Orrery-Windows` folder before
  creating the zip.
- Fixed the release dependency lock for PowerPoint generation. `python-pptx`, Pillow, XlsxWriter, QtPy,
  PySide6, and shiboken6 are now pinned so the Windows package keeps file-generation support instead of
  failing with `No module named 'pptx'`.
- Updated the Windows setup checks and docs: the package validates bundled Qt and PowerPoint support, and
  users no longer need Microsoft Edge WebView2 for the Orrery desktop window.


## Step 91 - Electron migration shell + in-app update checks (July 1, 2026)

- Started the Electron migration without rewriting the React UI or Python backend. `app.py` now has
  `--backend-only`, and Electron can start that backend as a child process with its own per-session
  token before loading the normal Orrery URL.
- Added `desktop/electron`: Electron main/preload files, package metadata, Electron Builder config,
  backend lifecycle management, external-link handling, and a native save-file bridge that preserves
  the existing `window.pywebview.api.save_file(...)` UI contract.
- Added an in-app update check path. The backend exposes `/api/app/update`, which reads public GitHub
  release metadata, compares it to Orrery's current version, and returns release assets without
  downloading or executing anything.
- Added a Settings -> Updates section that shows current/latest release status and release downloads.
  Native automatic installer updates are scaffolded for Electron, but final auto-install requires
  signed packaged builds and release metadata.
- Updated architecture docs: Orrery is a modular monolith with sidecars. Electron is the desktop-shell
  direction; microservices are deferred until a specific worker needs independent deployment or scale.


## Step 92 - Release fixes: token-counter packaging, persisted failed turns, Windows installer (July 1, 2026)

- **Fixed the release-breaking chat error.** In the packaged build, every API-key chat failed with
  "Unknown encoding cl100k_base". The token counter's encoding data loads through a plugin package the
  packager silently leaves out; the Windows and macOS build scripts now bundle it, and the packaging
  probe verifies the encoding loads so a broken build fails at build time, not in users' chats.
- **Failed turns no longer vanish.** A failed model call used to show its error only in the live stream -
  click anywhere else and it was gone, leaving a question with no answer and a hole in the chat history.
  Both the plain chat path and the tool loop now save the failed turn (any partial answer plus an error
  note), so it survives switching chats and reloads.
- **A real Windows installer.** New scripts/build-windows-installer.ps1 builds the backend as its own
  bundle (no Qt - Electron owns the window), wraps it in the Electron shell, and produces an NSIS
  installer with Start Menu/Desktop shortcuts and in-app updates. Install once, launch like any app -
  no more unzipping and hunting for the .exe. The zip release stays as the portable option; macOS keeps
  the drag-to-Applications .app zip (its build got the same token-counter fix).

Next: rebuild the release with these fixes; consider a macOS DMG via the same Electron path.


## Step 93 - Installers built: Windows NSIS verified, macOS DMG wired (July 1, 2026)

- **Windows installer works.** scripts/build-windows-installer.ps1 produced
  Orrery-0.1.3-win-x64.exe (~178 MB): the backend passed its packaging probe (including the new
  token-encoding check), Electron wrapped it, and NSIS packaged it - double-click to install
  per-user with Start Menu/Desktop shortcuts; no more unzip-and-hunt-for-the-exe.
- **macOS DMG pipeline.** scripts/build-macos-installer.sh mirrors the same flow on a Mac
  (backend-only bundle -> Electron -> DMG, unsigned). DMGs can only be built on macOS, so a new
  CI job builds it on a Mac runner; Windows CI likewise gained an installer job. Both attach
  their installer to tagged releases next to the portable zips.

Next: tag a release (v*) to let CI produce all four artifacts; consider code signing later.


## Step 94 - Dashboards are real: AI designs, Orrery renders (July 2, 2026)

- The Dashboards tab is no longer a mockup. Describe what you want to see, pick the model that
  designs it and one or MORE data connections (multi-source dashboards - each widget records which
  connection it queries). The model reads each connection's schema and returns a widget spec: stat
  cards, line/bar/pie charts (Apache ECharts), and tables.
- Safety, per the security standard: every AI-written query is parse-checked (sqlglot - exactly one
  SELECT, nothing data-modifying), runs in the database-enforced read-only path with timeouts and row
  caps, and is always visible per widget (the SQL button). Opening or refreshing re-runs the SAVED
  queries - no model call, no token cost, no new unseen SQL.
- Revise in plain words ("add a weekly signups widget") with any model; every revision snapshots the
  previous version, and Roll back restores it in one click. Dashboards are per-user in team mode and
  admins can turn the whole tab off with the new 'dashboards' feature flag.
- Also this session: context sizes are now per-model (no more picking 1M on a 200K model), Claude
  plan gained the Fable 5 variant, and the model chip shows a clean short name with a PLAN badge.

Next: review ontology/MCP/skills for improvements; then Automations (the engine + canvas).


## Step 95 - BI transforms, fixed file routing, working Settings General (July 2, 2026)

- **Dashboards, BI-style.** The designing model can now define named *transforms* - prepared datasets
  (cleaning, joins, derived columns) that widgets on the same connection reference like tables; Orrery
  validates each one (single read-only SELECT) and attaches them as CTEs at run time. A collapsible
  Transforms panel shows every prepared dataset's SQL. New data sources can be connected right in the
  dashboard create form (stored in the keychain as always).
- **Fixed the web-app-became-CSV bug.** "Build me a dashboard web app ... with a Download CSV button"
  produced a CSV, because format detection matched the mentioned button before the actual deliverable.
  Deliverable words (web app/page/site) now outrank incidental format mentions - that exact request
  routes to an HTML page.
- **No more 'read-only workspace' excuses.** A new app rule tells every model it is inside Orrery, not
  its own CLI, and must never refuse files on environmental grounds. And when the Docker sandbox is
  offline, the reasoning panel now says so explicitly instead of silently degrading.
- **Settings -> General is real now.** Default model + default reasoning depth (applied to new chats,
  stored in app config), a working Integrations panel showing your actual MCP servers with live enable
  toggles, and the shared Toggle component supports controlled use (it used to flip visually and do
  nothing).

Next: prompt/answer evaluation (compare candidate answers with an AI judge, on demand).


## Step 96 - Pick the best answer: on-demand evaluation with an AI judge (July 2, 2026)

- Every assistant reply now has an Evaluate action (the scales icon). Pick up to three other models
  to re-answer the same prompt, pick a judge model, and Orrery generates the candidates in parallel,
  strips the model names, and has the judge score each anonymously (A/B/C) on accuracy, completeness,
  and clarity with a one-line comment. Candidates come back ranked, the judge's pick is highlighted,
  and "Use this answer" swaps the chosen one into the chat (persisted like any edit).
- Judging is anonymous so brand names can't bias scores; a failed candidate or a judge that returns
  no scores degrades gracefully (unranked list, visible warnings). Runs only when the user asks -
  it costs extra model calls, so it's a per-message action, not an always-on pipeline.

Next: the architecture split (shared tool registry + per-feature API routers), then Automations.


## Step 97 - BI connectors: CSV/Excel uploads and REST APIs become queryable data (July 2, 2026)

- Dashboards can now pull from more than Postgres. The "Connect new data source" form in the
  Dashboards tab has three modes: PostgreSQL (connection string), CSV/Excel file upload, and REST API
  (JSON, with optional auth headers). Files and API responses are imported as real tables - column
  types inferred (numbers vs text), rows capped at 50k - under a dedicated "Workspace datasets"
  source, which dashboards query like any database (and can mix with other connections per widget).
- Isolation both ways: the datasets source sees ONLY the imported tables (never chats/projects/app
  tables), and normal database connections never see the datasets schema. Identifiers are sanitized
  and quoted, values parameterized, API auth headers live in the OS keychain, responses are size-
  capped. API datasets are refreshable (re-fetch -> rebuild the table); file datasets re-import.
- Also confirmed the Settings -> General tab is fully functional end to end: Branding (logo upload,
  live header update), Privacy (PII redaction modes), Defaults (default model + reasoning depth),
  and Integrations (real MCP servers with working toggles).


## Step 98 - Chat attachments accept Office documents again (July 2, 2026)

- Fixed the Chat composer file picker. It was still limited to images, PDFs, and text/code files, so
  Word documents were rejected even though Projects/Ontology already supported document ingestion.
- Chat now accepts `.docx`, `.pptx`, `.xlsx`, and `.xlsm` files, reads them as binary data URLs, and
  extracts their text locally before sending context to the model. Unsupported legacy `.doc` files now
  get a clear "save as .docx" message instead of silently failing.
- Uploaded Office documents are also indexed into the chat's durable file memory, so later turns can
  retrieve them through the same per-chat RAG path as PDFs and text files.


## Step 99 - Chat polish: copy that works, real attachment chips, paste images, logo fix (July 2, 2026)

- **Copy buttons actually copy now.** The desktop webview can silently deny the modern clipboard
  API; every copy control (prompt, reply, code blocks) now falls back to the classic method and
  flashes a green check with a little pop animation so you know it worked.
- **Attachments look like files, not a text blob.** Uploaded files used to render as one comma-run
  paragraph baked into the message. They're now separate chips below the prompt - click one to open
  what's inside (the extracted text, retrieved from the chat's index even after a reload; images
  open in the preview panel). Attachment metadata is stored with the message.
- **Paste or drop images/files straight into chat.** Ctrl+V a screenshot into the composer or drag
  files onto the conversation - both attach instantly (the picker allowed images all along, but
  paste/drop is how people actually do it).
- **Company logo uploads fixed.** Any reasonably sized image works now: logos are downscaled
  client-side to header resolution (crisp on high-DPI), so the old "too large" rejections and
  validation failures are gone; small GIFs keep their animation.
- Also landed this session: the shared tool registry (backend/tools) - stable keys, schema-exposed
  configs, scope allow-lists enforced at the tool layer - the groundwork Automations and Agents
  build on next.

Still on the list from user reports: specifics of the 'API limit' issue (need a repro - cap not
triggering, or blocking wrongly?).


## Step 100 - Vision on plan routes, native copy, relevance-gated file context (July 2, 2026)

- **Images now work on plan connections.** Claude plan turns with images write the attachment into a
  throwaway folder and allow the CLI exactly one tool - Read, scoped to that folder - so the model
  actually sees the picture while the no-write/no-persistence posture is unchanged. ChatGPT plan uses
  Codex's official --image flag. Gemini CLI stays text-first (deprecated consumer route) with an
  accurate message.
- **Copy finally works everywhere.** The desktop webview disables JS clipboard access at the engine
  level (both modern and legacy APIs), which is why earlier fallbacks still failed. Copy buttons now
  route through a native bridge (OS clipboard via the Python side); browsers/Electron keep the
  standard APIs. Green-check pop confirms every copy.
- **Files stop haunting unrelated questions.** Retrieval had no absolute relevance bar - the vector
  arm always returned the top k chunks, so earlier uploads leaked into every answer. Chunks past a
  cosine-distance ceiling are now dropped (keyword matches always pass), so an unrelated question
  simply gets no file context; the trace no longer claims attachments are in context twice.
- **Branding:** uploading a logo now auto-enables the header (it was easy to upload and see nothing).

Next: user to clarify the 'API limit' symptom; then the router split -> Automations.


## Step 101 - Context depth fix, dark dropdowns, update prompt, v0.2.0 (July 3, 2026)

- **The real context fix.** Beyond the retrieval gate: the FULL TEXT of every uploaded file was
  riding inside the model-bound history on every later turn, which is why unrelated questions kept
  "looking into" old uploads. Now only the most recent prior turn keeps its full attachment text
  (so "now shorten it" still works); older uploads return only through relevance-gated retrieval
  when the question actually matches them.
- **Dropdowns behave.** The webview was rendering native light-theme select popups against the dark
  UI (white flashes, unreadable lists). The app now declares itself dark to the engine
  (color-scheme) and styles option lists explicitly.
- **Update prompt.** When a newer GitHub release exists, a dismissable banner appears at the top of
  the app with a download link (full details stay in Settings -> Updates). Version bumped to 0.2.0
  for the first installable release.
- Ops note: the app failing to boot during this session traced to Docker Desktop being off (Postgres
  runs in Docker) - not an app bug; the DB error message says exactly that.


## Step 102 - HTML answers become previewable files; files stop tagging along (July 3, 2026)

- **Ask for a page, get a page.** When a reply contains a complete HTML document, Orrery now saves
  it as a real file and shows the same Preview/Download card documents get - no more walls of code
  with "save this yourself" (unless you actually ask for the code). Works on every model route,
  including plan CLIs that can't run the sandbox.
- **Vague follow-ups keep their intent.** "Do it" after "build me a finance dashboard web app" now
  plans with the previous ask's intent instead of losing it.
- **Relevance before retrieval.** When a message carries its own attachments (it's about THOSE) or
  is too short to judge ("Do it"), stored files must clearly match before they're allowed into
  context - and the reasoning panel now says either "N stored file(s) match this question" or
  "Files not needed - answering on its own". Default retrieval gate tightened as well.
- **Dropdowns de-highlighted.** The forced blue option background made every row in a select popup
  look selected; the engine's own dark rendering handles it now.

Next: refactor chat.py into a modular package (user ask; also api.py routers), Data tab dataset
management, app-like density for Settings/Admin.


## Step 103 - Shell commands in the sandbox (July 3, 2026)

- The model can now run shell commands, not just Python, inside the SAME hardened container: no
  network, read-only root, dropped capabilities, non-root user, cpu/memory/process caps, wall-clock
  timeout. A new orrery-shell block joins orrery-run in the chat tool loop (grep/sed/awk, archives,
  file inspection, CLI chains); files written to out/ come back as cards like always. Also exposed
  as run_shell in the shared tool registry for Automations/Agents.
- Verified live: commands executed, output files returned, and the network confirmed dead from
  inside the container (download attempt blocked).


## Step 104 - chat.py split into a modular package (July 3, 2026)

- The 1,280-line chat module is now a package with focused files: conversations (CRUD + ownership),
  retrieval (relevance-gated file context), persistence (saving replies, HTML->file conversion),
  generation (the streaming model call), runs (detached background generations), and router (turn
  prep + task routes + the dispatcher). The public surface is unchanged - everything still imports
  `backend.features.chat` - and cross-module calls go through module attributes so each function has
  exactly one patch/extension point.
- Zero behavior change: all 205 tests pass (only their patch targets moved to the owning modules),
  and the app boots and serves normally. This is the modular-monolith shape the rest of the backend
  (api.py routers next) will follow.


## Step 105 - api.py split into routers; image attachments get real thumbnails (July 3, 2026)

- **The 1,400-line api.py is now a package.** create_app keeps the middleware, auth token check,
  static serving, and the sandboxed artifact endpoint; the 135 API endpoints moved into fourteen
  per-feature router modules (system, models, settings, providers, local models, data, dashboards,
  collections, skills, MCP, admin/team, projects, conversations, files) with shared request models
  in schemas.py and shared helpers in deps.py. Same URLs, same auth, zero behavior change - all
  205 tests pass and the app serves normally. Together with the chat package split, the backend now
  matches the modular-monolith conventions end to end.
- **You can see which image is which.** Composer chips show a small thumbnail + filename before
  sending; sent messages show captioned thumbnails (click to view full size); and generated image
  files display a real preview thumbnail in their file card instead of a generic icon.

Next: full security review pass (user ask), Data tab dataset management, Settings/Admin density.


## Step 106 - Data tab manages datasets; SSRF guard; denser Settings/Admin (July 3, 2026)

- **Data tab caught up with the BI layer.** A new "Imported datasets - workspaces" section lists
  every workspace with its datasets (kind, row counts, source), lets you refresh API/Sheet imports,
  delete datasets, and create workspaces - with a pointer to the Dashboards import flow. Workspace
  sources no longer clutter the database-connections cards, and the connection form now mentions
  MySQL/SQLite alongside Postgres.
- **Import hardening.** User-entered import URLs pass an SSRF guard: cloud-metadata/link-local
  ranges are always blocked, and in team mode members can't point imports at the host machine's
  LAN or loopback (solo users keep their local APIs). Verified against metadata IP, credentialed
  URLs, and team-mode loopback.
- **Less vertical slop.** Admin lays out team + features side by side on wide screens; Settings
  General puts Privacy and Defaults in two columns and uses wider content - closer to an app panel
  than a scrolling website. Copy/download got a resilient fallback chain ending at a token-guarded
  local endpoint, so they work in every shell.


## Step 107 - Context discipline, viewable image attachments, nested raw thinking, more connectors (July 3, 2026)

- **Attachments are used only when needed - and you can verify it.** A turn that brings its own
  attachment with a short prompt now answers from that attachment ALONE (stored files aren't even
  searched), and the reasoning panel states the context decision explicitly every turn: "this
  message's attachment(s) only", "matched stored files: <names>", or "none of your stored files
  apply". Treating cross-topic file bleed as the safety issue it is.
- **Attached images stay viewable.** Image bytes are kept in the file library at send time, so the
  thumbnail and click-to-view work after reloads too - click any attachment chip/thumbnail to
  confirm exactly what was sent (images open in the panel; documents show their extracted text).
- **Raw thinking inside the hierarchy.** The model's live reasoning now streams NESTED under the
  step it belongs to, so each level of the trace shows what the model was actually thinking there;
  it persists with the message like the rest of the panel.
- **Connector set grown (research-grounded).** New: SQL Server (mssql:// via ODBC; use a read-only
  login - every dashboard query is also parse-gated to a single SELECT), MongoDB collection imports
  (URI in the keychain, refreshable), and JSONL/NDJSON + XML uploads. Joins Postgres, MySQL,
  SQLite, CSV/Excel/JSON, REST APIs, and Google Sheets - twelve connector types.

Deps: aioodbc/pyodbc, pymongo, defusedxml (pinned).


## Step 108 - User/admin access hardening (July 4, 2026)

- **Solo stays simple.** If Orrery has no team users, the local user is still treated as the admin:
  no access key, no extra setup, and full control over local settings.
- **Team mode is stricter.** Sensitive routes now require admin access in team mode: provider key
  changes, official plan/CLI connection actions, primary database connection management, shared
  model activation/custom model credentials, branding/defaults/privacy/spending caps, and team user
  management.
- **Feature access can be per member.** Admins can now set member-specific feature permissions from
  the Admin tab. The UI hides tabs based on the effective permissions, and chat capability gates use
  the same backend calculation.
- **Secrets stay server-side.** Members can use configured models and allowed features, but they
  cannot retrieve API keys or database URLs. The backend remains the authority; the UI is only a
  convenience layer.
- **Documented the model.** Added `docs/security/USER_ADMIN_ACCESS.md` covering solo/team behavior,
  roles, per-user feature overrides, secret handling, route enforcement, and follow-ups.

Next: broaden route-level feature checks tab by tab, and add automated team-mode authorization tests.


## Step 109 - Capability planner foundation, TeX source files, optional Crabbox (July 4, 2026)

- **TeX is now a real file target.** Requests for LaTeX/TeX source route through sandbox file
  generation, validate strict UTF-8 `.tex` output, check for recognizable LaTeX structure, reject
  binary/corrupt/placeholder content, and show TeX source as a previewable/downloadable file card.
  The local sandbox still does not bundle TeX Live or MiKTeX; PDF-from-LaTeX remains source plus a
  normal Orrery PDF unless a remote compile path is configured later.
- **The capability loop now has a registry contract.** Existing `orrery-run`, `orrery-shell`,
  `orrery-search`, and MCP blocks keep working, but execution now goes through `backend.tools`
  so allow-lists, argument validation, safe errors, and artifact handling are centralized. The new
  `capability_agent` flag exposes a generated tool catalog for broader model-guided tool choice.
- **File generation is a registered tool.** `file_generate` wraps the existing validated sandbox
  builder without persisting generated code or raw model reasoning; final answers, safe trace data,
  sanitized metadata, and approved artifacts remain the durable outputs.
- **Crabbox is optional and gated.** Orrery can report Crabbox status with non-mutating
  `crabbox doctor --json`, stores only non-secret preferences, and exposes `crabbox_run` as a
  side-effectful tool only when the admin/user feature gate and settings both allow it. Crabbox
  tokens, provider credentials, and broker config stay in Crabbox's own config/keychain.

Next: build a Settings UI for Crabbox, add optional remote LaTeX compile when a trusted executor is
configured, and broaden capability-agent tools for RAG/DB/dashboard workflows without bypassing gates.


## Step 110 - Capability planner becomes a grounded first-class module (July 5, 2026)

- Reviewed the Step 108/109 foundation (tool registry, Crabbox, automations, TeX skill) — coherent
  and secure — then finished the planner it set up.
- New `backend/features/capabilities.py` replaces the ad-hoc tool-catalog string that lived in the
  chat router. Each tool now states what it is FOR so the model chooses by intent ("self-realization"),
  and the catalog is GROUNDED: it injects the real ids the model would otherwise have to guess —
  reachable database connections (db_query), saved dashboards (dashboard_refresh), and document
  collections (doc_search). file_generate is described as the single file maker spanning HTML/web app,
  LaTeX (.tex), PDF, Word, Excel, PowerPoint, CSV, image, and audio.
- Closed the "scattered route-specific code" gap: when the Model-guided tool planner feature is ON,
  file and image requests are no longer pre-routed by regex to the deterministic handlers — they flow
  to the model, which self-selects file_generate (or another tool) and the produced files surface as
  the usual preview/download cards. Default OFF preserves today's routes exactly, so nothing regresses.
- 223 tests pass (added: grounded-catalog content + end-to-end model self-selection of file_generate
  with backend-injected model/context).

Next: a Settings UI to enable/configure Crabbox and the capability planner; then Agents (Phase 5)
building on the same registry.


## Step 111 - Fix vision-question misrouting + phantom file buttons; write the Agent Computer plan (July 5, 2026)

The user reported several things that "feel patched, not architected," worst of all: attaching a
screenshot and asking "what do you see" produced a `session_context_report.pdf` instead of just
answering. We traced and fixed the acute bugs, then wrote the architecture doc we agreed to produce
before building the bigger "computer for agents."

- **A picture question can no longer turn into a file.** The router used to route purely on text and,
  for a short prompt like "what do you see", would borrow the *previous* message's wording — so an
  earlier "…generate a PDF…" hijacked the turn into file generation and ignored the image entirely.
  Now: a turn that brings its own attachment is about *that* attachment (it never inherits an earlier
  turn's intent), and any turn carrying an **image** is answered as a vision question — it can never
  be sent to file or image generation. Locked in with a regression test that even "generate a PDF
  report of this" plus an attached image stays a normal chat answer.
- **No more PDF/Word buttons under a failed message.** The file buttons were being drawn from the
  words in your prompt, regardless of whether a file was actually made — so a reply like "I couldn't
  create the file (usage limit)" still showed export buttons that implied one existed. The UI now
  recognizes a "could not create a file" reply and hides the buttons.
- **The "streaming raw thoughts" turned out to be honest work-steps, not leaked thinking.** We traced
  every path (normal chat, file generation, the tool loop) and the model's private reasoning is already
  suppressed at the source: whatever channel a provider uses for thinking (separate reasoning tokens,
  inline `<think>…</think>`, Anthropic thinking blocks, or the Claude/ChatGPT CLI routes) is counted for
  diagnostics but never shown or stored. What was visible under "Reasoning" was the play-by-play of what
  Orrery was *doing* (the work trace). In the mis-routed image case that play-by-play was also alarming
  because the model was being forced to build a file out of a picture and kept failing — the "Attempt
  1/3 → Repairing 2/3 → Repairing 3/3" ladder was real retries, now gone since images no longer trigger
  file generation.
- **Made the file-generation trace tell the truth instead of looking scripted.** The first pass no
  longer says "Attempt 1/4" (which read as a canned ladder even when it worked first try); it just says
  "Writing the file", and a retry counter appears only when a repair genuinely happens.
- **Wrote `docs/planning/AGENT_COMPUTER_ARCHITECTURE.md`** — the detailed plan for the real goal: a
  persistent, isolated **Computer** the model/agents can drive across many steps (filesystem, shell,
  interpreter, optional real OS/network), with pluggable backends (a local Docker computer by
  default, the user's Crabbox as an optional backend behind the *same* interface). It maps every
  reported symptom to a root cause, folds file generation and Crabbox into one abstraction instead of
  scattered routes, keeps the security floor (secrets in the keychain, model code only on a computer,
  an approval gate for writes/network — closing the current ungated `crabbox_run`), and lays out a
  phased, non-breaking migration. Today's fixes are "Phase 0" in that plan.

Next (from the plan): Phase 1 — introduce the `Computer` interface and a persistent-per-session local
Docker backend behind a small broker; then move `file_generate` onto it (Phase 2) so the deterministic
and sandbox file paths return one unified file card instead of today's buttons-vs-card split.


## Step 112 - Heavy scenario testing + context window now follows the model (July 5, 2026)

- **Heavy routing/context test pass.** Added `tests/features/test_heavy_scenarios.py`: a broad matrix of
  realistic prompts (chat / documents / decks / images / speech / projects) through the planner, plus
  integration cases through the real chat pipeline covering attachments, vague follow-up inheritance,
  and the guarantee that an attached image is always answered as a vision question and never turned
  into a file. Writing it surfaced (and documented) two real behaviors: audio requests are delivered
  through the file route (there is no separate "audio" route), and a file build that succeeds does not
  also run the model-reply fallback. 256 tests pass.
- **Live smoke test of the running app** (no model cost): the SPA shell and freshly built assets serve,
  the localhost auth boundary holds (real `/api` routes require the session token → 401 without it),
  unknown artifacts 404 cleanly, and the security headers are present. One small note: unknown
  extension-less `/api/*` paths fall through to the SPA and return index.html instead of a JSON 404 —
  harmless (real routes are protected), logged for later tightening.
- **Context window now matches the chosen model.** The reported problem was "the context window isn't
  set according to the model." Root cause: the backend already knows each model's true window
  (Opus/Sonnet 5 = 1M, GPT‑5.5 ≈ 1.05M, a Claude‑plan standard route = 200K and its `-1m` variant = 1M,
  a local Llama = 8K, …) and `/api/models` already sends it per model — but the chat UI ignored it and
  defaulted every new chat to a hard‑coded 1,000,000, only ever clamping *down* on an explicit model
  switch. So an 8K local model, or a 200K plan route, still displayed and budgeted as if it had 1M. Fix:
  a new‑chat's window now defaults to the selected model's real maximum, and switching models moves the
  window to the new model's window (keeping a deliberately smaller choice, clamped to the new max). The
  backend was already the correct source of truth and needed no change.

Next: still Phase 1 of the Agent Computer plan; and optionally tighten the `/api/*` SPA fallback.


## Step 113 - One Claude model, 1M reached by the slider (July 5, 2026)

Follow-on to the context-window work: the user picked "Claude Opus (PLAN)" and it capped at 200K even
though Opus supports 1M. The cause was a confusing two-entry design — a standard "Opus" (200K) and a
separate "Opus 4.8 - 1M context" model that had to be found, activated, and selected. The user asked to
merge them into one.

- **One entry per Claude-plan model; the context slider reaches 1M.** The 1M-capable models
  (Opus / Sonnet / Fable) now report their full 1,000,000 window from a single menu entry, so the
  per-chat slider offers sizes all the way up. Haiku and the generic "adaptive" route, which have no 1M
  mode, still show 200K.
- **The window turns on 1M mode automatically.** When the chosen window is above the 200K standard tier,
  Orrery runs the Claude CLI's long-context ("[1m]") mode for that turn; at or under 200K it uses the
  standard mode. So picking a big window *is* how you get 1M — no separate model to hunt for. The old
  "-1m" entries still exist internally as the flag carriers but are hidden from the picker.
- **Cost stays in the user's hands:** 1M mode can use the Claude plan's quota faster, so it's driven by
  an explicit window choice rather than always-on. A new Opus chat defaults to the model's full window
  (what the user expected), and dialing the slider down to 200K or less returns to standard mode.
- Backend-only change (models list, `model_context_window`, a new `plan_long_context_model`, and the
  chat/regenerate paths); the UI already reads each model's real window from `/api/models`. 259 tests
  pass, including new coverage for the 1M reporting, the window→mode switch, and the hidden "-1m" menu.

Next: unchanged — Phase 1 of the Agent Computer plan.


## Step 114 - Attachments preview as the real file; file results look consistent (July 5, 2026)

Clearing two more of the reported screenshot issues.

- **Attachments now preview as the actual file, not just their text.** Orrery had only kept the raw
  bytes of image attachments; for a PDF or Office file it stored just the extracted text, so clicking
  one could only ever show text. Now the real bytes of every binary attachment (PDF, Word, Excel,
  PowerPoint, images) are kept, and opening one shows the true file — a PDF renders as a PDF, an image
  as an image, text as text. Office files (which a browser can't render inline) open as the real file
  via the preview pane's "Open" action instead of dumping text. (Applies to files attached from now
  on; older messages had only image bytes saved.)
- **A requested file looks the same whether it was pre-built or made from the reply.** Before, a real
  generated file showed a rich card (thumbnail, name, size, Preview/Download) while a reply that could
  be turned into the asked-for format showed a different little "Requested file:" row of chips — the
  "why do I get buttons instead of a file?" confusion. Both now use the same file card, so the result
  is consistent. (The deeper unification — always producing one real stored file for every file
  request regardless of path — remains Phase 2 of the Agent Computer plan.)

Next: uploaded-file context relevance (stop pulling unrelated attachments into a turn), then the
write-tool approval gate; then Phase 1 of the Agent Computer.


## Step 115 - A real download page and installable build (July 5, 2026)

We turned Orrery into something a person can actually download and run, and gave it a home on the web.

- **Built the Windows package.** Ran the existing packaging pipeline to produce a self-contained
  Windows folder (Orrery.exe plus its runtime) zipped as `Orrery-Windows.zip` (~310 MB). It carries the
  setup/run helper scripts, the optional bundled PostgreSQL, and the sandbox image definition.
- **Published it as a download.** Uploaded the Windows zip to the GitHub release so it sits alongside
  the macOS build. Both download links resolve. Because the preview isn't code-signed yet, Windows will
  show a one-time "Windows protected your PC" box — the fix for that is a code-signing certificate
  (a paid, identity-verified cert), so for now the "More info -> Run anyway" step is documented in the
  packaged README, on the site, and in the release notes.
- **Built a landing site.** A single self-contained page (`docs/index.html`) with an orbital/cosmic
  look that fits the name: a hero, the six-surface feature grid, the local-first principles, a download
  section wired straight to the release assets, a getting-started flow, and links into the docs.
- **Hosted it on GitHub Pages** from `main/docs`, live at https://zaidt156.github.io/Orrery/. Verified
  the page serves and the Windows/macOS download buttons resolve to real files.

Next (unchanged): the write-tool approval gate, then Phase 1 of the Agent Computer.


## Step 116 — Stop plain questions from generating junk files, and a full architecture grind (July 6, 2026)

Two things this session: a real bug fix you reported with a screenshot, and a deep,
plain-words map of how the app actually works so we can decide together what to speed up.

- **Fixed the "what do you see" → useless PDF bug.** You attached a screenshot and typed
  "what do you see"; instead of looking at the image, Orrery built a `session_context_report.pdf`
  — and the same thing happened after an earlier file turn even with no attachment. The cause:
  a short message like "what do you see" counts as "vague," and a vague follow-up was allowed to
  **inherit the previous turn's intent** ("…make a PDF…"). So a plain question after a file
  request quietly kept making files. The fix: a vague turn that is actually a **question**
  ("what do you see", "who is this?") is treated as a fresh question and never inherits a prior
  file/image intent. Added regression tests; the whole routing/retrieval suite passes (73 tests).
  The "broken preview" you also saw was just that junk PDF failing to render — with the routing
  fixed, the junk file is never produced, so that clears too.
- **Ground-up architecture grind.** You asked to understand, before changing anything, how
  Context, RAG, document indexing/chunking, project context, the sandbox, file generation, and
  artifacts/preview really work. Nine focused readers went through the actual code and reported
  how each piece works today, its strengths, its weak points, and where it gets slower as the
  app grows. The full briefing — with file references and a ranked performance list and a
  decision menu — is saved at `docs/planning/ARCHITECTURE_GRIND.md`. Headline: the app feels
  slower as it grows mainly because (1) every chat turn reloads the **entire** conversation
  history from the database, (2) the chat screen re-draws every message on every streamed word,
  and (3) a Docker check runs on the main thread on every turn. All three are fixable without
  changing what the app does.

Next: you decide which improvement track to take first (backend speed pass, history/pagination,
frontend streaming, filegen routing, or the security/policy questions). Also still open from
your messages: attach/publish the Windows + macOS builds via the release workflows and prompt
for prerequisites (Docker) during install; a README/contribution overhaul; the Dashboard
onboarding + state-persistence work; and in-place message versioning (‹ › like Claude/GPT)
instead of appending a duplicate on resubmit/redo.


## Step 117 — Backend speed quick-wins (July 9, 2026)

You chose the low-risk backend speed pass first, so we removed redundant per-turn work without
changing what the app does. Four fixes, all covered by tests:

- **The Docker check no longer runs on every turn.** Before, Orrery ran a `docker image inspect`
  (to see if the code sandbox is available) several times per message, on the main thread — so if
  Docker was slow or starting up, the whole app stalled. Now the answer is remembered for a short
  while (30s when the sandbox is present, 5s when it's missing so a just-started Docker is noticed
  quickly). Shipped earlier this session and now joined by the rest.
- **The search query is turned into numbers once, not once per place we search.** Answering with
  "use my data" searches several collections at once (your data, the project's files, this chat's
  attachments, connected knowledge). Each search was separately re-encoding the *same* question.
  Now it's encoded a single time and reused everywhere — same results, less repeated work, and it
  stops growing as you connect more knowledge sources.
- **Listing your collections is one database query instead of one-per-collection.** The Data and
  Ontology tabs counted each collection's chunks with a separate query in a loop; now a single
  grouped query returns them all.
- **Listing projects dropped a redundant count query.** It already had every project's chats loaded
  in memory, yet ran a second query just to count them — now the count comes from what's already
  loaded.

Deliberately deferred: caching the "is team mode on?" check. It's called a lot per turn, but caching
it carelessly could, for a moment right after someone turns team mode on, make a locked client look
like a solo user (which removes the per-user privacy filter). That one needs a fresh-per-request
approach, not a timed cache, so it waits.

Next (from your messages): the README + contribution overhaul with an install-time prerequisite
check (Docker/Postgres) — you said do this now and you'll trigger the build; then the bigger speed
levers (bounding the per-turn history load, frontend streaming re-renders); then Dashboards
onboarding + the reset-on-close bug, and in-place ‹ › message versioning.


## Step 118 — First-run prerequisite check and docs polish (July 9, 2026)

You asked that installing Orrery should actively push people to install what it needs (like Docker)
during setup, and that the README be tidied up.

- **Setup now surveys prerequisites up front.** Before the Windows and macOS setup menus appear,
  Orrery now checks whether Docker Desktop is installed and running (and whether Ollama is present
  for local models), prints a clear OK / needs-attention / optional line for each, and — if Docker is
  missing — offers to open the Docker Desktop download page for you. Docker is only required for the
  bundled database and the file sandbox, so if you bring your own PostgreSQL you can still continue.
  The old checks only complained *after* you'd already picked a Docker option and gave no link; now
  it's a friendly, actionable first screen on both platforms.
- **README + contribution docs polished.** Documented the new prerequisite check in both the Windows
  and macOS run sections, and fixed a stale cross-reference in the contribution guide (it pointed at
  a "Getting started" section that had been renamed). Confirmed the whole docs set is intact —
  README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, the bug/feature issue templates, and the PR
  template all present and linked.

Note: these are source changes to the packaged setup scripts and docs. They ship the next time the
Windows/macOS release build runs — which is the step you said you'd trigger.

Next: the bigger speed levers (bound the per-turn history load, then the frontend streaming
re-renders), then Dashboards onboarding + the reset-on-close state bug, then in-place ‹ › message
versioning.


## Step 119 — Message versioning: the safe foundation (July 9, 2026)

Starting the Claude/GPT-style ‹ › message versions you asked for — so pressing redo/resubmit revises
a message *in place* with little arrows to flip between versions, instead of dumping a duplicate at
the bottom. This step lays the groundwork without changing any behavior yet:

- **The conversation becomes a tree.** Each message can now point to the one it follows (a "parent"),
  and one flag marks which version is the one you're currently looking at. Regenerating a reply or
  editing a prompt will later add a *sibling* version instead of replacing or duplicating — every
  version is kept so the arrows can bring it back.
- **Existing chats are safely upgraded.** A one-time backfill links every current message into a
  single straight line (its natural order), so nothing looks different today; new versions branch off
  from there. The change is additive — no data is moved or lost, and every existing test still passes.
- **The path logic is written and tested on its own.** The rules for "which version is showing" and
  "how many versions exist" are pure, database-free functions with their own tests (linear chains,
  regenerated replies, hidden branches, fallback when nothing is flagged). 272 tests pass.

Still to come for this feature: wire regenerate/resubmit to create versions, make history + loading
follow the active version, add the switch-version action, and add the ‹ › arrows in the chat bubble.

Next: finish wiring message versioning, and triage the rest of the current backlog (landing-site
redesign, 4 selectable themes, the dashboard connection-persistence bug, the macOS build not
launching, and adding the new GPT models).

## Step 120 � Message versioning finished and verified (July 9, 2026)

Finished the Claude/GPT-style in-place message versioning that Step 119 started. The backend now
keeps both edited user prompts and regenerated assistant replies as sibling versions in the message
tree, instead of appending duplicates to the bottom of the chat. Conversation loading follows the
active path, so switching versions restores that version's own branch of replies.

- **Regenerate now branches in place.** Re-answering a turn keeps the old assistant reply as a
  switchable sibling and saves the new reply as the active version under the same user message.
- **Resubmit/edit now branches in place.** Revising a saved prompt creates a new user-message sibling
  with its own follow-up reply, while the old prompt and old reply stay available.
- **The API can switch versions.** `POST /api/conversations/{cid}/messages/{mid}/activate` flips the
  active sibling and returns the refreshed conversation.
- **The UI shows `� n/m �` controls.** Chat bubbles with sibling versions now show previous/next
  arrows, and switching reloads the active branch rather than duplicating messages.
- **Added an end-to-end regression test.** The new DB-backed smoke test creates a disposable chat,
  sends a normal prompt, resubmits it as a user sibling, switches back to the older prompt, regenerates
  an assistant sibling, and switches back to the older assistant reply. Model calls are mocked, so the
  test exercises persistence without spending tokens.
- **Hardened test isolation.** Tests now default to solo/admin mode with default feature flags, so the
  suite no longer inherits local team-mode or feature-toggle state from the developer database.

Verification:
- `python -m pytest -q` -> **285 passed**, 1 existing Starlette/httpx deprecation warning.
- `cd ui && npm run build` -> passed; Vite still warns about large dashboard/chat chunks.

Next: triage the remaining backlog � landing-site redesign, 4 selectable themes, dashboard
connection-persistence/reset-on-close bug, macOS build not launching, and new GPT model entries.


## Step 120 — Message versioning wired end to end (July 10, 2026)

The ‹ › in-place message versions from Step 119 now actually work, front to back:

- **Regenerating keeps every answer.** Pressing regenerate no longer deletes the old reply — the new
  one takes its place on screen and the old one stays one arrow-click away. Nothing is lost anymore.
- **Resubmitting revises in place.** Resubmitting a prompt used to dump a duplicate question at the
  bottom of the chat. Now it revises the original message where it sits: the new version (and its
  answer) replaces it visually, and the arrows flip between prompt versions — each remembering its
  own reply, like Claude and ChatGPT do it.
- **Little ‹ 1/2 › arrows on the bubbles.** Any message with more than one version shows the switcher
  next to its action buttons. Flipping a version reloads the thread down that branch, so the whole
  follow-up conversation that belonged to that version comes back with it.
- **Everything reads the same view.** The reply history the model sees, the loaded chat, per-message
  evaluation, and file exports all follow the currently-selected versions — other branches can never
  leak into the model's context or an export.
- **Old chats repaired automatically.** Messages written in the short window before this change didn't
  yet know their place in the version tree; a one-time cleanup threads them in at next start.
- **Two chat glitches fixed along the way.** Re-attaching to a reply that kept generating in the
  background crashed silently (a missing function); and the new post-turn refresh could briefly wipe
  the live reasoning panel — it now keeps what's on screen until the saved copy catches up.

All 284 backend tests pass and the UI builds clean. A planned multi-agent adversarial review of the
change couldn't run (the account hit its monthly agent-spend limit), so the review was done by hand
instead — that's how the two glitches above were found.

Next: the landing-site pass you asked for — replace the "local-first" wording with plainer language
("Local AI"), a correct screen demo, soften the white patch on the pages, and proper step-by-step
copy — then the rest of the backlog (4 selectable themes, dashboard connection-persistence bug,
macOS build not launching, new GPT models).


## Step 121 — Landing-site pass: plain words, honest demo, softer paper, real steps (July 10, 2026)

Four fixes you asked for on the website, all in the one-page site:

- **Plainer language.** Every "local-first" became plain "Local AI" (page title, search/social
  previews, the hero line, the footer).
- **An honest app demo.** The hero screenshot-mockup previously showed an invented app (cryptic
  sidebar letters, chart panels inside the chat). It now mirrors the real product: the icon rail
  with the actual tabs and the database status light, a Chats list, and a true chat turn — the
  activity summary line, Orrery's reply with a dashboard file card, the new ‹ 1/2 › message-version
  arrows, and the message box.
- **Softer pages.** The bright cream sections are toned down so the white patch no longer glares
  against the dark theme; same palette, lower intensity.
- **Real setup steps.** The Start section now has Windows / macOS / From source tabs (no scripts —
  plain HTML), each with four accurate steps matching how setup actually behaves.

## Step 122 — Docker installs itself; the database sets itself up (July 10, 2026)

You asked that installing Orrery push the user through Docker setup instead of leaving them stuck.

- **Fresh installs no longer dead-end.** The installed desktop app used to crash quietly on first
  run: with no database chosen yet it tried to ask a question on a console that doesn't exist. Now,
  when Docker is available, Orrery simply creates and starts its bundled PostgreSQL by itself
  (locked to your own machine) and remembers the connection in the OS keychain — open the app,
  get a working workspace.
- **If Docker is missing or asleep, the app says so usefully.** Instead of a generic "startup
  failed", a dialog offers the actual next step: a button to get Docker Desktop, or one to start it.
- **The setup scripts now do the installing.** On Windows they can install Docker Desktop through
  winget or the official installer; on macOS through Homebrew or the official disk image — then
  start it and wait until it is ready, rather than telling you to come back later.

Next: the ontology fix (chat cannot see inside ontology files — embedding/vector build + a
300-file, multi-ontology stress test), the thinking-stream raw-thoughts view, and the macOS build
verification in the cloud.


## Step 123 — Ontologies proven at scale, and the context-mixing leak closed (July 10, 2026)

You asked to make chat genuinely see inside ontology files and to hard-test the architecture with
300 files across multiple ontologies.

- **The pipeline itself was sound** — a full test against the real local database (3 ontologies ×
  100 files, each carrying a unique retrievable fact) showed ingestion, embedding, search, and the
  chat-level gathering all working, with correct attribution and good speed (600 chunks embedded in
  about 23 seconds; searches in fractions of a second).
- **What was actually broken was the relevance gate — in both directions.** Measured on real prose,
  a single fixed "how close must a snippet be" threshold cannot tell an off-topic question apart
  from an on-topic one: unrelated questions were pulling ontology text into chats (the dangerous
  context-mixing on the issue list), while the same threshold could starve legitimate questions.
  The gate is now anchored on each ontology's BEST match: if the best match isn't close enough, the
  whole ontology stays out of that turn; if it is, only that best match's neighbourhood rides along.
  Exact word matches always pass.
- **Connected ontologies now count as automatic context** (like a chat's own uploads), so standing
  knowledge answers on-topic questions and never tags along on unrelated ones. Collections the user
  explicitly picked ("use my data", a project) keep their generous bar.
- The 300-file stress test is saved as a repeatable script (scripts/stress_ontology_rag.py) and
  passes every check, including "an unrelated question must pull nothing".

## Step 124 — The thinking stream shows the model's raw thoughts (July 10, 2026)

The activity panel used to show only Orrery's own narration of the work; the model's raw thinking
was silently discarded. Now the raw thoughts stream into the same panel — click the activity card
open to read them, live while the model thinks — and they're saved with the rest of the panel so
they survive reloads. The boundaries stay: thoughts never appear in the answer itself, are never
fed back into prompts, and are never written to logs.

Next: verify and fix the macOS build in the cloud (GitHub Actions macOS runner), then the rest of
the backlog (4 selectable themes, dashboard connection persistence, new GPT models).


## Step 125 — The macOS build gets tested on a real cloud Mac (July 10, 2026)

You asked to verify the released macOS build on an online Mac service. Instead of a paid rental
(MacinCloud needs an account and card), the repo now has a GitHub Actions workflow that runs on
GitHub''s own Apple Silicon macOS machines: it downloads the released .dmg, checks the app bundle''s
integrity, launches it headlessly with no database configured, and uploads all output plus macOS
crash reports as a downloadable artifact. It ran automatically on this push and can be re-run any
time from the repository''s Actions tab.

Strong lead on the "macOS build not launching" bug: the released build crashes on first run because,
with no database chosen yet, it tried to ask a question on a console that doesn''t exist in a
double-clicked app. That exact failure was just fixed by the Docker self-provisioning change
(Step 122) — the fix ships with the next release build. The workflow''s log annotations distinguish
the old crash from the new behavior so the rebuilt release can be verified the same way.

Next: read this first run''s artifact (Actions tab), rebuild the macOS release with the Step-122 fix,
and re-run the smoke test; then the rest of the backlog (4 selectable themes, dashboard connection
persistence, new GPT models).


## Step 126 — "nice" is praise, not a work order (July 10, 2026)

You showed screenshots: after Orrery drew the clock SVG you asked for, replying "nice" made it
draw a second, random SVG. Two stacked causes, both fixed and proven with tests plus a live run
of your exact conversation:

- **Praise no longer inherits intent.** Short follow-ups used to inherit the previous request''s
  intent unless they were questions — so "nice" counted as "go again". Now a turn made purely of
  appreciation words ("nice", "thanks", "love it", "great job") is recognized as a social reply
  and routes to normal chat. A single action word ("make it blue", "again", "add a second hand")
  still keeps the old behavior, so genuine confirmations aren''t broken.
- **Follow-ups are no longer context-blind.** When a real confirmation ("do it") does inherit,
  the image/file generator now receives the inherited ask alongside it — before, it literally got
  just the two words and drew from nothing.

Also discovered while verifying live: the Claude plan account has hit its **monthly spend limit**,
so model calls themselves currently fail app-wide with an honest error note in chat (raise the
limit at claude.ai/settings/usage, or use an API key / local model meanwhile). The routing fix is
verified independently of that.

The app was restarted with this fix and is running. macOS status: the shipped DMG''s bundle is
verified intact on a real cloud Mac; the full launch check is in its final iteration (watch the
repository''s Actions tab — anonymous API polling from this machine is rate-limited for a while).

Next: read the macOS launch-run results and rebuild the release with the first-run fix; then the
backlog (4 themes, dashboard connection persistence, new GPT models).

## Step 127 - Same-tag release rebuild and mobile GitHub Pages update (July 10, 2026)

The release pass continues from Step 126 with two constraints: keep the public release tag stable, and make the GitHub Pages download site work cleanly on phones.

- The GitHub Pages site now treats mobile as a first-class layout: centered page gutters, a visible icon-sized download CTA in the sticky header, a bottom-anchored hero mockup that no longer relies on fixed top offsets, single-column setup tabs, and tighter footer/download wrapping for 320px-wide screens.
- The macOS download card now points at both expected DMG assets: Apple Silicon (`Orrery-0.2.0-mac-arm64.dmg`) and Intel (`Orrery-0.2.0-mac-x64.dmg`), while keeping the portable zip link.
- The Intel build now uses GitHub's supported `macos-15-intel` runner instead of the retired `macos-13` label, and the release badge plus both portable zip links are pinned to `v0.1.0-preview` instead of the moving `latest` alias.
- The macOS smoke test now starts automatically after a successful `Build macOS Release` run, so the rebuilt arm64 DMG is checked on a real cloud Mac before this step is considered done.
- The release rebuild should reuse `v0.1.0-preview` exactly as requested, moving that existing tag to the current `main` commit so the Windows and macOS release workflows rebuild artifacts under the same public release URLs.

Next: push this site/workflow/devlog commit, force-update `v0.1.0-preview` to the commit, then watch the Windows/macOS release workflows and macOS smoke workflow in GitHub Actions.


## Step 128 — The release shipped and the new macOS build survives first run (July 10, 2026)

Executed the plan from Step 127 (continuing the Codex session''s work, which was reviewed, tested —
299 backend + 3 UI tests — and committed):

- **Raw thinking now truly streams live.** The model''s raw thoughts appear in their own "Raw model
  thinking" block inside the activity panel while the model is still thinking (the panel opens
  itself during streaming), are saved without corruption, and survive reloads. Connections that
  don''t expose a raw stream say so honestly instead of showing Orrery''s narration as if it were
  the model''s thoughts.
- **The v0.1.0-preview release was rebuilt in place.** The tag moved to the current code, the
  Windows and both macOS installers rebuilt under the same public download links — now carrying
  the first-run Docker self-provisioning fix, message versioning, the ontology gate, and the
  context-mixing fix.
- **Proof on a real Mac:** the chained cloud smoke test pulled the freshly rebuilt DMG, launched it
  on a machine with no Docker and no database — the exact situation that killed the old build
  instantly — and the app was still alive and healthy 90 seconds later with zero crash reports.
  Windows and macOS release builds, the smoke test, and the site deployment are all green.

Next: the remaining backlog — 4 selectable themes, dashboard connection persistence, new GPT
models — and raising the Claude plan spend limit so model calls work again.


## Step 129 — Four selectable themes (July 10, 2026)

Orrery now has an Appearance page in Settings with four looks, applied instantly and remembered on
this computer:

- **Simple** — the classic deep-indigo star map (unchanged, still the default).
- **Futuristic** — near-black night sky with electric teal and violet accents.
- **Winter** — a bright, frosty light theme with gently falling snow (the snow is pure styling, no
  scripts, and switches off automatically for people who prefer reduced motion).
- **Summer** — warm paper tones with sun-orange accents.

Because the entire interface was already driven by a small set of color variables, each theme is
just a different tuning of those variables — every tab restyles at once, nothing was rebuilt per
screen. Status colors (green = ok, red = error) are deliberately identical in all four so meaning
never changes with the look. The choice applies before the first paint on startup, so there is no
flash of the wrong theme.

Next: dashboard connection persistence (retest on the rebuilt release first — the database now
starts itself, which may have been the real cause), then the new GPT model IDs (waiting on which
ones), the speed levers, and the site redesign around the concept art.


## Step 130 — Concept shell + four complete themes (July 10, 2026)

You asked for the tabs and overall appearance to follow your concept art, and for the four themes
to be genuinely different looks, not recolors. Both shipped:

- **The sidebar now matches the concept.** The narrow icon strip became the concept''s labeled
  sidebar: the Orrery mark and wordmark at the top, icon-plus-name rows for every tab with a soft
  pill highlight (amber icon on the active one), a live "System healthy / Database connected" pill
  at the bottom that turns amber or red on real problems, and the open-source license line.
- **A concept top bar across the app.** Workspace identity on the left (your custom branding when
  it''s on), and the workspace''s default model shown as a live chip on the right.
- **Four complete looks.** Each theme now changes the sky behind the app, the corner geometry, and
  the surface treatment — not just colors. Simple stays the quiet flat star map; Futuristic is the
  concept: deep navy, a faint holo-grid over the starfield, glowing amber and electric-blue
  accents; Winter is an icy gradient sky with frosted-glass chrome and falling snow; Summer is a
  golden-hour glow over warm paper with the roundest corners. Green/red status colors stay
  identical everywhere.

The app is running with the new shell — flip the looks in Settings → Appearance.

Next: your visual feedback on the new shell (per-view polish to the concept — Chat''s context
panel, Home-style hero cards — is a further step), then dashboard connection persistence, GPT
model IDs, speed levers.


## Step 131 — Concept polish everywhere, an Observatory theme, and a fresh release (July 10, 2026)

This step finishes the concept pass that Step 130 started, adds the fifth theme you asked for
(the same colors as the website), and ships everything as a rebuilt release.

First, the work from earlier this morning that hadn''t been written up yet:

- **Surfaces got real depth.** A five-layer elevation system (sky → panel → card → chip →
  overlay) now drives every surface, so each theme can lift panels with its own shadows instead
  of everything sitting flat.
- **"Check connections" is a real button.** The sidebar''s passive health pill became an action:
  press it and Orrery live-checks the database and every configured model, reporting exactly
  what''s reachable.
- **Home is a real landing page.** The Home tab now opens with a hero banner and live workspace
  numbers (chats, collections, dashboards, automations) instead of placeholder copy.

Then this session''s work:

- **Every page-style view now opens like the concept.** The hero banner (title, subtitle, orbital
  art) that Home introduced now heads Data, Settings, and the Media Hub in a compact form, so the
  app reads as one designed product instead of one polished tab and plain siblings. Views built
  as list-plus-detail (Chat, Dashboards, Automations, Agents, Projects) keep their toolbars — a
  banner would only push their content down.
- **A fifth theme: Observatory.** You asked for a theme with the same colors as the website, and
  the download site''s palette is now a selectable look: warm charcoal sky with a faint drafting
  grid, antique-gold accents, teal highlights, parchment-colored text, and the site''s sharp 8px
  corners. Same rule as always: green-ok / red-error stay identical in every theme.
- **Small cleanups.** The Settings hero lines up with the settings content width, and style rules
  for headers that no longer exist were removed.

Verified: the UI builds clean, all 3 UI tests pass, and the new theme''s variables land intact in
the built stylesheet. A multi-agent adversarial review went over the whole diff before shipping.

Released: pushed to main (which redeploys the website), and moved the `v0.1.0-preview` tag so the
Windows installer and both macOS installers rebuild under the same public download links, with the
cloud-Mac smoke test chained after the macOS build — the same proven release path as Step 128.

Next: dashboard connection persistence, the new GPT model IDs (waiting on which ones), and the
remaining speed levers (bound the per-turn history load, frontend streaming re-renders).


## Step 132 â€” Independent interfaces and upgrade-safe Life Memory (July 11, 2026)

The redesign and durable-memory work now have enforceable foundations rather than visual or
documentation-only promises.

- **Interface and color are independent settings.** Classic and Concept now have separate stored
  structural modes, while Simple, Futuristic, Winter, Summer, and Observatory are palette choices.
  Legacy theme preferences migrate automatically. Classic starts in Chat without a Home tab;
  Concept keeps the labeled navigation and Home workspace.
- **LIFE.md survives upgrades.** Orrery bootstraps the user's private runtime memory into the native
  OS user-data directory, never the installation folder. Electron explicitly passes that directory
  to the packaged backend; generated files, WebView state, and packaged `.env` configuration also
  moved out of the signed/update-replaced application directory.
- **Agents cannot silently rewrite memory.** The dedicated Life service prepares an immutable
  proposal with base and target SHA-256 hashes. Settings shows the exact plaintext diff, and a local
  owner must approve that exact target digest. Writes use a cross-platform lock, stale-base check,
  same-directory atomic replace, link/reparse-point defense, secret screening, and content-addressed
  snapshots. Approval is crash-reconcilable; rejected, expired, or mismatched proposals cannot
  apply.
- **History is usable.** Settings now includes a Life Memory editor, pending review queue, exact
  approve/reject actions, runtime-file location, revision list, and rollback proposals. Team users
  receive isolated canonical files, while background work must carry an explicit snapshotted owner.
- **The old macOS write failure is addressed at its root.** A packaged backend previously tried to
  write under Electron's `resources/backend` directoryâ€”inside the signed `.app` on macOS. All
  durable mutable paths now resolve through platform user data instead.

Verified: 58 focused Python tests pass across paths, LIFE storage/approval, secrets, files, config,
and authenticated APIs; the production UI build also passes. Browser-plugin verification remains
blocked by its local kernel-asset error, so full live visual/runtime checks stay in the final matrix.

Next: versioned Agent persistence and real CRUD/builder state, followed by bounded execution,
schedules, the scoped external agent API, Slack/Gmail connectors, full Concept page composition,
and clean-machine Windows/macOS installer gates.


## Step 133 - Agents foundation shipped, faster long chats, installers verified (July 11, 2026)

The Agents tab now has its real data layer, a big chat speed lever landed, and both reported
installer failures were run to ground before rebuilding the release.

- **Agents are real data now.** Every agent is a typed, validated definition: a goal in plain
  words, guidelines, the model that runs it, the context it may draw from (skills, datasets,
  ontologies, projects), tool grants that name exactly which resources each tool may touch and
  what needs approval, connector grants (Slack/Gmail), trigger modes (manual, schedule, API,
  Slack, Gmail), hard budgets (steps, runtime, input/output size, runs and spend per day), and
  a cron schedule with a timezone that can never fire more than once a minute. Every save creates
  an immutable version - queued or running work can never be changed out from under itself - and
  a config that appears to contain a secret is refused outright.
- **Scope is enforced in code, not prompts.** The shared tool registry now carries a risk level
  on every tool, and the tool runner itself checks an agent's grant before executing: no grant
  for a resource, or the wrong resource id, and the call is refused - the same floor Chat,
  Automations, and Agents all share. The most dangerous risk levels (destructive actions,
  external writes, credential use) can never be marked pre-approved.
- **The storage for what comes next is in place.** Runs, per-step traces, approval requests,
  hashed per-agent API keys (for the "integrate an agent into your own website" direction), and
  de-duplicated trigger events all have their tables - the run loop that uses them is the next
  step, so nothing executes yet.
- **The suite caught a release-blocker before it shipped.** A missing import in the conversation
  loader would have crashed every chat open in the live app; the end-to-end versioning test
  failed exactly there, and the one-line fix was verified with the full suite.
- **Long chats got their speed lever.** Loading a conversation and preparing each turn now reads
  light "skeleton" rows to walk the version tree and only loads full message text for the recent
  turns the model actually sees, instead of every text column of every message ever written.
  This was one of the two big items on the speed backlog; the streaming re-render fix remains.
- **Both installer reports were triaged with evidence.** The Windows installer asset was
  re-downloaded, verified byte-identical to the release, and installed cleanly on this machine -
  the July 10 "error writing to file" was a stale pre-rebuild download or a transient temp-file
  lock, not a broken release; Defender's history shows no Orrery detections. The macOS "Orrery is
  damaged" dialog is Gatekeeper blocking an unsigned app, not a crash: the workaround is removing
  the quarantine flag, and the real fix - code signing and notarization - stays on the list.
- **Verified.** 342 backend tests pass, all 12 UI tests pass, and the production UI build is
  clean. Committed to main and the v0.1.0-preview tag was moved so the Windows and macOS
  installers rebuild under the same public download links, with the cloud-Mac smoke test chained
  after the macOS build.

Next up: the bounded agent run loop (execute within budgets, per-step trace, approval gates),
then the scoped external per-agent API and Slack/Gmail connectors; after that the frontend
streaming re-renders, the dashboard-connection persistence retest, and the new GPT model IDs
(still waiting on which ones).


## Step 134 - July 11 issue batch logged before fixing (July 11, 2026)

The user filed a batch of issues (screenshots in the local Issues/ folder, 12:20-12:26) covering
the installed app, both layouts, and several Settings areas. Logged here first so every fix that
follows is traceable to a report. The list, in the user's priority order:

1. **Installed app fails to start** - "Orrery startup failed: the backend exited during startup".
   Likely cause on this machine: the development instance was already holding the app's local port
   when the installed copy was launched; needs the packaged log to confirm, and a friendlier
   port-in-use message either way. Both release rebuilds of this morning's commit also FAILED in
   CI (Windows and macOS) - diagnosed separately.
2. **Release hygiene** - once the fixed build is published under v0.1.0-preview, the older releases
   (v0.2.0, v0.1.3, v0.1.2, v0.1.1) should be removed from the Releases page.
3. **Classic layout: the bottom-left status dot cannot be closed** - clicking opens the
   connection-check details; clicking again does not collapse them.
4. **Life.md should be the app's soul, not a form** - start BLANK on first run, ask the user a few
   onboarding questions and store the answers; then keep learning automatically from chats
   (through the existing propose-diff-approve pipeline), instead of expecting manual edits. The
   current page also shows the internal template text and a mojibake heading ("Â€""), both wrong.
5. **Theme picker has no visual identity** - the interface cards are empty boxes; each theme/mode
   needs a real visual preview so they can be told apart at a glance.
6. **"Add a custom model" belongs with the API accounts** - move it from Models to the accounts/API
   area under an "Add other API" title; adding any OpenAI-compatible model must keep working.
7. **Concept Settings hero shows a wrong logo** - the oversized amber disc on the right of the
   Settings banner is not the Orrery mark.
8. **The Concept layout reads as "weird blocks"** - the background grid is too large and too loud,
   making every page look like empty wireframe boxes (clearest on Dashboards and Home). Bring the
   look to the user's concept art: subtler grid, real panel depth, futuristic accents.
9. **Skills tab structure** - "MCP servers / + Add server" sits at the very bottom; split the view
   into side sub-tabs (skills list, create skill, MCP servers) and add a create-MCP option.
10. **Home scrolls as a whole page** in both layouts - the hero and stat cards should stay fixed;
    only the bottom panels (Recent activity, System) should scroll internally.

Next: diagnose the CI release failures, then work the list top to bottom, logging each fix.


## Step 135 - The July 11 issue batch fixed (July 11, 2026)

Worked Step 134's list top to bottom. What changed, in the same order:

1. **Both CI release builds were failing for one reason:** Step 132 made the packaging probe
   require a bundled LIFE.md template, but none of the four build scripts copied it into the
   package. All four now bundle it. Separately, the installed app's "backend exited during
   startup" turned out to be a PORT COLLISION - the dev copy was already holding the app's local
   port, and the packaged log proved the installed backend was otherwise healthy. Two-sided fix:
   the desktop shell now picks a free port at startup instead of assuming 8765 (it also actually
   passes it - the backend never read the shell's port before, the two only agreed by luck), and
   a source run falls back to a free port with a clear log line when the preferred one is busy.
   Two Orrerys can now run side by side.
2. **Release hygiene** is queued: once the rebuilt installers publish, the old releases come down.
3. **The bottom-left status dot now closes.** Clicking it while the connection details are open
   collapses them; before, every click re-probed and re-opened the panel.
4. **LIFE.md is now the soul, not a form.** A fresh install starts with an (almost) blank memory
   file instead of the internal charter text. On first run, Orrery asks a few questions - what to
   call you, what you do, what Orrery is for, what it should always remember - and your answers
   become the first LIFE.md through the normal exact-diff approval path. From then on, chats can
   TEACH it: a message that carries something durable ("call me...", "I prefer...", "from now
   on...") triggers a small extraction pass, and anything worth keeping lands as a PENDING
   proposal in Settings > Life Memory - the owner still approves the exact diff, cooldowns keep
   the queue quiet, and a failure can never break a chat turn. Also fixed the garbled heading on
   that Settings page.
5. **The theme picker shows real previews now:** the two interface cards render live mini-mockups
   of each layout (painted from the active palette), and every color theme shows a thumbnail in
   its OWN sky/panel/accent colors instead of three bare dots.
6. **"Add a custom model" moved to Accounts as "Add other API"** - same OpenAI-compatible form,
   same keychain storage; its models still appear under Models for on/off control.
7. **The Settings hero art no longer shows a wrong-looking giant amber disc** - per the concept
   art it is now a small sun with a tight glow inside thin orbit rings.
8. **The "weird blocks" are gone.** The Concept sky's loud 56px holo-grid (the thing that made
   every page look like empty wireframe boxes) is removed entirely - the reference art has no
   grid. The sky is now a calm dark field with one soft glow and sparse stars, and Concept
   corners rounded up to the reference's 14px.
9. **Skills is split into side sections.** MCP servers moved off the bottom of Overview into
   their own sidebar entry with a summary row and a prominent "Create MCP server" action.
10. **Home no longer scrolls as a whole page** (desktop): the hero, quick actions, and stat cards
    stay put; Recent activity and System scroll inside their own panels.

Verified with the full backend suite, the UI unit tests, and a production build; released by
moving the v0.1.0-preview tag again (same public URLs).

Next: watch the rebuilt installers + macOS smoke test go green, remove the old releases, then
continue the Concept parity pass (top-bar search, per-view composition) and the Agents run loop.


## Step 136 - Executables proven, macOS signing, once-ever first run, Concept pass 1 (July 11, 2026)

The user's direction for this stretch: make the executables work properly FIRST, then work
heavily on the futuristic look. Both moved:

- **The rebuilt installers are live and the Windows one is proven end to end.** Both release
  workflows went green on the fixed commit and the cloud-Mac smoke test passed. The new Windows
  installer was then downloaded fresh, byte-verified, silently installed, and launched WHILE the
  development copy was already running - the exact scenario that crashed this morning. The
  installed app picked a free port on its own, connected to the database, and stayed healthy.
- **The macOS "damaged" message has a root cause and a fix in the build.** The DMG app was being
  shipped with NO signature at all (signing was fully skipped on CI), and Apple Silicon
  hard-blocks completely unsigned apps with exactly that "damaged" dialog. The build now
  ad-hoc signs every binary in the app and verifies the signature before packing the DMG.
  A quarantined first open still needs right-click > Open until real notarization ships.
- **Old releases removed.** v0.2.0, v0.1.3, v0.1.2, and v0.1.1 are gone from the Releases page;
  v0.1.0-preview is the one canonical release, as requested.
- **The first-run questions can only ever appear once.** Answering or skipping now records a
  durable per-user flag in the app's own settings, so the dialog is gone for good after the
  first start - even if the browser-side storage gets wiped.
- **Concept pass, part 1 (the reference's top bar).** A real global search now sits in the
  middle of the Concept top bar - Ctrl/Cmd+K from anywhere, searches chats, projects,
  dashboards, ontologies, collections, skills, and the tabs themselves, and picking a chat
  opens that conversation. The workspace identity on the left became the reference's chip, and
  the sidebar footer now shows the app version (the health check reports it).

Also in this pass, from the user's next screenshot batch (Agents tab):

- **The agent builder could "break" the whole window.** The create/edit form had no bounded
  height, so it silently overflowed a pane that cannot scroll - and clicking a checkbox deep in
  the form made the browser scroll that unscrollable pane, leaving fragments at the top and a
  void below. The editor now scrolls internally. Two undefined style variables (corner radius
  and font aliases the new view referenced) were also defined, and the garbled "Â·" characters
  across the Agents screens were fixed at the source.
- **Interacting with a created agent is now honest.** Edit, Pause/Activate, and Archive work;
  schedule editing lives under Edit > Triggers & schedule; and a visible (disabled) Run button
  plus the Activity panel say plainly that the RUN ENGINE ships in the next update - the
  definition, schedule, and grants are saved as immutable versions and will start executing
  when it lands. Building that engine is the next milestone.
- **Asking for a bare ".png" / ".mp3" now routes to file generation.** A word-boundary quirk in
  the file-intent pattern made standalone extension mentions unmatchable; fixed, and the
  extension test spec dropped in by the parallel session was adopted (20 cases green).

Released by moving v0.1.0-preview once more so the installers pick up the macOS signing.

Next: the Agents run engine (bounded execution, manual Run, schedules firing), then continue
the Concept parity pass (per-view composition, cards, chat panel).


## Step 137 - Agents RUN: the bounded execution engine (July 11, 2026)

Agents now actually work. The engine turns a saved definition into real, auditable runs:

- **Press Run, watch it work.** The Run button starts a run (with an optional task for that run);
  the Activity panel shows every run live - status, trigger, each model step, each tool call and
  its result, the final output - and lets you cancel. Scheduled agents fire on their cron via a
  one-minute heartbeat in the durable job queue, honoring the overlap policy (forbid / queue /
  replace) and de-duplicating across workers.
- **Every run is an immutable snapshot.** A run executes the exact config version it started
  with - editing the agent never changes queued or running work. The whole conversation is
  rebuilt from the durable step trace, so a run survives suspensions and app restarts (runs left
  "running" by a closed app are marked interrupted at boot).
- **The loop is bounded by the agent's own budgets:** model steps, wall-clock runtime,
  input/output sizes, runs per day, and daily API cost are all enforced in code - a looping
  agent stops with a plain explanation instead of burning tokens.
- **Tools stay behind the grant wall.** The model calls tools through one fenced convention;
  every call goes through the registry's grant check (allowed tools AND allowed resources).
  An ungranted tool returns a refusal the agent can adapt to - verified by test.
- **Risky actions suspend for the owner.** A call whose risk needs approval creates a pending
  approval card in the Activity panel showing the EXACT action; nothing executes until you
  approve, and a rejection is fed back so the agent can finish differently. Approve resumes the
  run automatically. Approvals expire after a day.
- **A latent Automations bug died on the way:** manual workflow runs were deferred to a queue
  task name that was never registered, so queued runs could sit forever - both run_workflow and
  the new run_agent are now properly registered on the worker.

Verified: 8 new engine tests (tool loop, approval suspend/resume, step and runs-per-day budgets,
ungranted-tool refusal) - 376 backend tests total, UI build clean.

## Step 138 - Agents builder verified by screenshot; macOS Docker detection fixed (July 11, 2026)

The evening's Agents-builder complaints were run down with a NEW verification method: a headless
probe driving the exact same engine the desktop window uses (Qt WebEngine), clicking the real UI
and screenshotting every step. Three real defects fell out, each proven fixed by a screenshot:

- **The builder went blank because of the catalog, not the checkboxes.** /agents/catalog bundled
  live model discovery (which can probe provider CLIs for seconds), and the screen blocked the
  agent list AND every checkbox group on it - bare boxes with headings and nothing inside. The
  catalog now returns only fast database lists, models come from the same cached source as the
  chat picker, and each part renders the moment it arrives with honest "Loading..." states.
- **Selected chips showed no tick.** The checkbox fill relied on a CSS :has() rule that the
  app's webview did not paint. The checked state is now a plain class set directly from React -
  it cannot silently fail - with a bold dark tick on the amber box.
- **The tick sat low in its box.** The icon kept its built-in 24px height attribute and a text
  baseline; explicit sizing and block display center it exactly.

Also this step:

- **macOS "install Docker" loop fixed at the root.** A packaged .app launches with a minimal
  PATH, so the bundled-database bootstrap could not SEE an installed Docker and asked the user
  to install it again and again. The shared subprocess helper now resolves bare command names
  (docker, ollama, soffice) against the well-known macOS install locations, and every docker/
  ollama call site plus the bootstrap goes through it. Ships in the next installer rebuild.
- **Stress-test residue swept.** The parallel session's 100-file lifecycle test cleaned its own
  database rows (verified: no scratch collections/projects/chunks remain), but left ~131 MB of
  Edge browser test profiles under tmp/ - removed. One real find: the eam_demo_work_orders
  dataset exists TWICE (a July 2 double-upload) - the known re-upload-duplicates issue, already
  Task 3 of the current plan.
- Fixed issue screenshots were removed from the local Issues/ folder at the user's request.

## Step 139 - Scale pass lands; GPT-5.6 lineup; the model knows its own name (July 11, 2026)

Phase 1 of the plan moved four tasks, plus two fresh user reports, all verified by the suite:

- **Streaming is smooth in long chats (plan Task 1).** Tokens now paint at most once per frame
  instead of re-rendering the whole thread per token; the in-flight reply renders as plain text
  and becomes formatted Markdown exactly once, at completion; finished messages cache their
  derivations. The final rendered reply is byte-identical to before.
- **Lists paginate and are indexed (plan Task 2).** The chat sidebar loads the newest 100 with
  a "Show older chats" button and a true total; new indexes back the sidebar sort and the
  per-turn message walk. Search handoffs open chats by id, so older chats still open directly.
- **Big document drops no longer freeze the app (plan Task 3).** Re-uploading a file REPLACES
  its old passages (the duplicate-on-reupload bug is dead), and larger uploads index in the
  durable job queue with live progress in the Ontology tab while chat keeps working.
- **The team-mode check is memoized per request (plan Task 4)** - the safe version of the memo
  deliberately deferred in Step 117: a fresh cache per authenticated request (background work
  always reads fresh), invalidated by every team-state mutation, so it can never fail open.
- **The chat model now knows what it is** (user report: "which model are you" got a guess).
  Orrery states the serving model in the system prompt, so the answer is exact on every route.
- **OpenAI's July 9 GPT-5.6 family is wired in** (user request): sol (flagship), terra
  (balanced), and luna (fast) map onto the API-key model picker's four slots, and the ChatGPT
  plan menu gains all three tiers - existing 5.5 selections keep working, and old Codex CLIs
  now hide EVERY current-generation pin (not just one id) while the auto route keeps working.

Verified: 380 backend tests pass; UI builds clean.

## Step 140 - A model-backed decider ends the context-mixing class (July 12, 2026)

The routing bugs kept coming from the same place: a regex heuristic (taskrouter) that reads
keywords but not meaning. Reported this round: "Whats 12598653 + 1836493" typed after a
"sing me a song" turn produced a 3.4MB wandering_star_song.wav instead of the sum. Same shape as
the earlier "what do you see"->PDF and "nice"->random-SVG bugs. The user asked for the real fix:
a decider that takes context and, before acting, asks the model how to handle the task.

- **Immediate fix (regex).** _is_question now accepts apostrophe-less contractions (whats/hows/
  wheres) and recognizes an arithmetic expression as a fresh ask, so a calculation can never
  inherit a prior generative intent. Regression tests added.
- **Root-cause fix (the decider).** New taskrouter.decide(): the fast heuristic still runs
  instantly, but BEFORE an expensive/irreversible generative action (file/image/audio/project)
  Orrery asks the model to classify the TRUE current message against recent context, returning
  strict JSON {route, format}. If the model says the turn is really a chat answer, chat wins.
  Plain-chat turns never call the model (no added latency on ordinary messages); any model
  failure - limit, offline, malformed - falls back to the heuristic, so a turn is never blocked.
  It is universal (works on any model/connection via a plain JSON convention, not a provider
  structured-output API) and can be turned off with one config flag (model_intent_decider).
- Wired into the chat dispatcher; the model judges user_content while the heuristic keeps its
  fast "do it"-inheritance path on the concatenated text. 428 backend tests pass (new:
  decision parsing, chat-skips-the-model, model-overrides-a-false-audio-route, real-file
  confirmed, failure-falls-back, disabled-flag).

## Step 141 - Security-review fixes, real Office previews, and a fresh release (July 12, 2026)

This step lands the parallel session's implementation of the security re-review findings plus the
real file-preview feature, verifies the whole tree is releasable, and rebuilds the release for
both platforms. Everything below was gated on the full suite, a clean UI build, an additive
migration, and a clean boot before shipping.

- **The cross-user data-leak class is closed (E3).** Collections now carry an owner_id (additive
  migration 0007, backfilled from a collection's parent chat/project only when unambiguous; legacy
  standalone rows stay owner-less and are invisible in team mode until an admin claims them). A
  member can no longer list, search, connect, or delete another member's collections, and a
  client-supplied collection id is validated against the owner before it is searched.
- **The privacy boundary now covers every channel (E1/E2).** prepare_request_for_model applies the
  user's privacy mode (off/basic/strict) to the SYSTEM-PROMPT channel too - trusted project
  context, user preferences, and RAG evidence - not just the messages array, so personal data in
  those layers is masked before a cloud model on every route (chat, Deep Research, file gen).
- **Real Office previews (the "PPTX shows only text" report).** filepreview renders pptx/xlsx/docx
  to a faithful preview through the local converter when present, with the HTML rendering as the
  fallback; a small officePreview helper drives the UI. New backend + UI tests.
- **Provider-limit handling groundwork.** ai.py raises a typed ProviderLimitError and estimates
  input tokens against the model's window, so a quota/limit failure is a clean, catchable signal
  (the base for cross-model failover) instead of a raw dump.
- **Team authorization tests** (Step 108 / plan Task 5c): locked clients fail closed on the newer
  private surfaces, and cross-owner isolation on agents/runs/approvals is verified.

Verified before release: full backend suite 431 passing (incl. the new rag-security, privacy-
boundary, team-authz, filepreview, file-preview-api, and datasets suites); UI build clean;
migration 0007 additive/idempotent and applied cleanly on a live boot. Released by moving the
v0.1.0-preview tag to this commit so the Windows installer and both macOS DMGs rebuild under the
same public download links (the landing site's pinned links keep resolving), with the cloud-Mac
smoke test chained after the macOS build.

## Step 142 - The installed app now brings its own database up (July 12, 2026)

The released executables were failing to open with "Orrery setup failed" whenever Docker wasn't
already running — the app worked only if the user had started Docker themselves first. The user's
long-standing ask was: if Docker/the database isn't there, guide me; if it IS there, just start it
and run. This step makes that real.

- **The app auto-starts Docker when it's installed but stopped.** provision() no longer gives up
  on the "Docker installed, engine down" state — it launches Docker Desktop, waits for the engine
  to come up (polling, up to ~2.5 min), then starts the bundled database. Only if Docker truly
  isn't installed, or can't be started, does it fall back to the actionable Install/Start dialog.
- **A saved connection no longer bypasses this.** Before, once a URL was stored (from a prior
  run), the app skipped the Docker logic entirely and just tried to connect — so reopening with
  Docker stopped failed outright. Now Orrery ensures the bundled local database is up whenever the
  URL it would use IS that local database (fresh install OR returning user); a user's own external
  Postgres URL is still left untouched.
- **Fixed a Windows regression before it shipped.** Resolving the docker binary to a full path
  picked up the extensionless WSL 'docker' file shutil.which reports, which CreateProcess rejects
  (WinError 193) — it made a running Docker look "stopped". The Windows path now uses the bare
  name so PATHEXT resolves docker.exe, with an explicit docker.exe fallback only when it's off PATH.
- **Detection is disk-based, not PATH-based.** Docker Desktop is recognized by its app/exe on
  disk, so a not-yet-started engine or a packaged app's minimal PATH no longer reads as "missing".
- **Two smaller fixes the user flagged:** the installer's subtitle was the internal "Electron
  shell for Orrery desktop." — now "Orrery — your local-first AI workspace."; and a new idempotent
  scripts/start-orrery.sh brings Docker + the database + the app up and is safe to re-run (anything
  already running is left alone).

Verified: 432 backend tests pass (incl. new should_ensure_local cases); docker_state reads "ready"
correctly on a live Docker; the app boots end to end through provision() (starts the existing
container, connects, opens). Released by moving the v0.1.0-preview tag so both installers rebuild.

## The plan from here (user direction, July 11)

1. **Architecture hardening for scale** - re-plan and secure the foundations so Orrery stays
   fast and correct with LARGE amounts of files and data: storage/indexing strategy for big
   collections, bounded context assembly at scale, the remaining frontend streaming re-render
   fix, and a security re-review of the grown surface.
2. **Real file previews** - a generated PPTX (and other Office types) currently previews as
   text; previews should look like the real file (slides with layout and images, styled
   documents, formatted sheets), with the current HTML preview as the fallback.
3. **One-off "small apps"** - when the user asks for a quick app for urgent or one-time use,
   Orrery should handle it end to end: generate it AND give a safe way to actually use it
   (sandbox-hosted interactive preview or packaged download) - any sort of asked work.
4. **Concept/futuristic theme, continued** - per-view composition to match the concept art.
5. **Agents next increments** - scoped external API keys, Slack/Gmail triggers, learning notes.


## Step 138 - A real 100-file mixed-format lifecycle stress test (July 11, 2026)

The scale-hardening work now has a repeatable mixed-format gate instead of relying only on small
unit tests or the existing text-only ontology benchmark.

- **100 real files, every FileGen format.** The new manual harness creates five each of PDF,
  DOCX, XLSX, PPTX, CSV, TeX, PNG, JPEG, GIF, WebP, SVG, WAV, MP3, MP4, WebM, ZIP, HTML,
  Markdown, text, and JSON. Each batch runs inside Orrery's actual offline, non-root,
  resource-capped Docker sandbox; the AI provider is deliberately excluded so the result is
  deterministic and costs nothing.
- **The complete internal lifecycle is checked.** All 100 outputs must pass FileGen's backend
  validators, persist to the temporary generated-file library, reload byte-for-byte, and produce
  a preview. The 50 text/PDF/Office files that Orrery can search are then indexed into a disposable
  project, queried one by one, gathered through the same chat retrieval path, relevance-isolated
  from an unrelated question, and deletion-tested. Media and archives are correctly treated as
  downloadable artifacts rather than searchable text.
- **The harness is safe to repeat.** It requires an explicit command-line opt-in, refuses any
  non-loopback database, names every database resource with a fresh UUID, deletes only IDs created
  by the current run, keeps generated blobs in an OS temporary directory, and runs every cleanup
  path independently even after a failure. It never sweeps user resources by a shared name.
- **Measured on this machine.** The passing run took 25.2 seconds: 17.0s for 20 sandbox batches,
  2.1s for 100 store/reload/preview cycles, 4.6s to index the 50 readable files, and 0.8s for
  50 pointed searches. The serialized 100-file payload was 0.77 MiB against the configured 64 MiB
  request cap. Cleanup removed all 200 blob/metadata entries and the current run's database rows.
- **The older broad context test still passes.** The 300-file ontology run completed in 29.7s
  (25.4s ingestion, 0.3s direct search, 0.2s chat gathering) with attribution and no unrelated
  context leak.

Verified: the new 100-file lifecycle passes, the 300-file ontology stress test passes,
376 backend tests pass, all 12 UI tests pass, and the production UI build is clean. The build's
existing large-chunk warning remains visible; it is not a build failure.

Next: execute the five-workstream plan recorded in Step 137, starting with scale foundations
(streaming, pagination/indexes, idempotent off-thread ingestion, request-scoped team-mode caching,
and the security re-review), then real Office previews and safe one-off app bundles.


## Step 139 — Multilingual documents (July 14, 2026)

Until now the search-your-documents feature only really understood English. The model that turns
text into the numbers used for meaning-based search was an English-only one, and the exact-word
side of search was pinned to English rules too, so a French, Spanish, or Chinese document searched
poorly. This step makes document search work across roughly fifty languages.

- **Meaning-based search is now multilingual.** New document collections are built with a
  multilingual model (paraphrase-multilingual-MiniLM-L12-v2) that still runs entirely on the user's
  machine and produces the same size of vector as before, so nothing about how the data is stored
  had to change. The choice is now a setting, not a hard-coded name.
- **Old collections keep working, untouched.** Every collection remembers which model built it, and
  each one is searched with its own model — so documents indexed before this change still return
  correct results instead of quietly breaking. Nothing is silently mixed or re-processed behind the
  user's back.
- **A one-click upgrade for old collections.** A "Make multilingual" button appears on any
  collection still on the old English model. It re-processes that collection's existing text in
  place with the multilingual model — no need to find and re-upload the original files.
- **Exact-word search went language-neutral.** The keyword half of search no longer applies
  English-only word rules; it now treats terms plainly, so words in any language can match. The
  trade-off is that English word-family matches (e.g. "running" also matching "run") now lean on the
  meaning-based half of search rather than the keyword half — which already handles that better.
- **A safety guard.** If anyone ever points the setting at a model whose vector size doesn't fit the
  store, the app now refuses it with a clear message instead of silently corrupting the data.

Why this model specifically: it was the one multilingual option that keeps the exact vector size we
already use, so existing data and its fast-search index carried over with no migration of the
numbers themselves — only the small, automatic keyword-column rebuild. The heavier, higher-accuracy
multilingual models would have forced re-processing every existing document. The one first-run cost:
the new multilingual model is a larger one-time download than the old English model; it is fetched
once and cached, exactly as the old one was.

Verified: 14 targeted RAG/retrieval tests pass (new multilingual model default, the dimension-mismatch
guard, language-neutral keyword column, and legacy-vs-multilingual collections each embedding with
their own model); the production UI build is clean.

Next: same five-workstream plan from Step 137 — scale foundations, real Office previews, and safe
one-off app bundles.

## Step 143 - Long chats stream without repainting the whole thread (July 15, 2026)

The remaining frontend scale bottleneck is now implemented and protected by a focused regression
check. Completed message rows keep stable identities while a reply streams, incoming text is
coalesced to one screen update per animation frame, and the unfinished reply stays plain text until
it is complete. A 100-message test proves that a token delta invalidates only the active row.

The full verification run also exposed two ingestion tests that accidentally tried to download the
new multilingual embedding model. They now use deterministic local vectors, so the suite proves the
ingestion behavior without depending on internet access or a warm model cache.

Verified: all 35 UI tests pass; the production UI build succeeds; all 513 backend tests pass. The
existing large dashboard-chunk build warning remains unchanged. Manual React Profiler capture for
a live long chat stays in Checkpoint 1.

Next: finish Task 8's app-bundle persistence (zip artifact plus extracted preview directory and its
dedicated tests), then add the traversal-proof, CSP-locked serving route in Task 9.

## Step 144 - Small app requests now produce one safe bundle artifact (July 15, 2026)

Orrery can now recognize an explicit one-off app request, build the client-side app in the secure
offline sandbox, validate the bundle, and save it as one downloadable ZIP instead of attaching its
HTML, JavaScript, CSS, and assets as unrelated files.

- **A real bundle contract.** The builder requires one index.html, local JavaScript and CSS,
  supported local assets, bounded file counts and total size, and a single normalized bundle root.
  The exact plan example, "Build me a small expense-splitter app", now selects this path.
- **Self-containment checks fail honestly.** External URLs, network APIs, browser storage, unsafe
  paths, missing local references, inline scripts/events, remote CSS/SVG references, duplicate
  attributes, and platform-specific path tricks are rejected. A failed app never falls through to
  the document generator and never produces a fake success attachment.
- **One durable artifact.** The generated-files library writes a deterministic ZIP plus a private
  extracted preview tree. The preview and ZIP publish before metadata, making metadata the final
  commit marker; injected-failure tests prove rollback leaves no partial artifact. Expiry cleanup
  removes the ZIP, metadata, and preview as one group.
- **Every entry point agrees.** Chat routing and the shared file.generate tool use the same
  storage contract and return one app_bundle file record with its entry point and member count.
  ZIP creation and disk publication run off the async request loop.
- **The runtime boundary remains explicit.** Static source checks are a quality gate, not a
  JavaScript security sandbox. Preview files remain private and unserved in this step. Task 9 must
  add the authenticated route, strict response CSP, traversal-proof lookup, and sandboxed iframe
  before Orrery exposes an interactive preview.

An independent adversarial review found and verified the duplicate-attribute and uncommon
URL-bearing-attribute hardening before approval. No Critical or Required findings remain.

Verified: all 541 backend tests pass (one existing Starlette/httpx deprecation warning); all 38 UI
tests pass; the production UI build succeeds. The existing large Dashboards chunk warning remains
unchanged.

Next: Task 9 - serve the private bundle through a session-gated, CSP-locked route and open it only
inside a sandboxed iframe, while preserving the ZIP download.

## Step 145 - The reported issues, and why a CV came out looking like a report (July 16, 2026)

Five reported problems turned out to be four unrelated bugs and one that explained two complaints at
once. Each was traced to a proven cause before anything was changed.

- **Asking for a CV produced no file at all.** This was the big one, and the reasoning panel was
  telling the truth about it. Orrery has an optional setting, "Model-guided tool planner", which the
  owner had switched on. With it on, Orrery stopped handling file requests itself and left the model
  to decide whether to make a file — but the model is only *offered* that ability, never required to
  use it, so "Creat me a CV..." came back as a chat message with the CV typed into it and no
  document attached. The chat history shows both halves of the story in one conversation: with the
  setting off, the same request produced a real Word CV and a full activity trace; with it on, one
  line, "Done", and no file. Worse, the panel had already announced "Preparing the requested file"
  before the code decided to skip that path, so Orrery promised a file it never made. A request for
  a deliverable now always uses Orrery's own file builder; the planner still picks tools freely for
  everything else.

- **The "pathetic CV" was the same bug wearing a different hat.** Because no file was generated, the
  owner exported the chat reply instead — and an exported reply is rendered by the generic document
  renderer, which is why a CV arrived shaped like a report. That path also stamped "Orrery" and a
  page number onto the bottom of every page, and recorded Orrery as the document's author.

- **Files no longer advertise Orrery.** A CV, a letter or a report belongs to the person who asked
  for it; a document footed with the name of the app that typed it is not one anyone would send. The
  file's own code already said so in a comment and then did the opposite. Page numbers stay, the app
  name is gone, and the Word author field is now cleared rather than left to say "python-docx".

- **The model was told to deface its own documents.** It had been instructed to mark sample content
  as fictional but given nowhere to put that, so it wrote "This is a fictional sample CV..." into the
  top of the CV, above the contact details, and narrated the document to its reader
  ("Reverse-chronological summary of 5 roles..."). It is now told to keep such notes in the chat
  message, where they do not deface the file, and that a CV opens with a person's name.

- **Two ways to crash a chat turn, and one real security hole.** Reviewing the app-bundle work from
  Step 144 found that Orrery read the model's hand-written SVG images with the standard XML reader.
  That reader expands "entities", so roughly 270 bytes of a well-known malicious pattern balloons
  into as much memory as the attacker likes — the size limits do not help, because the growth happens
  after the check. Orrery already ships a hardened reader and already uses it in two other places;
  the file builder now uses it too. Separately, a broken image, or an app that used one name as both
  a file and a folder, raised errors of a type nobody was catching, so instead of a plain "could not
  build it" message the whole turn fell over. Both now fail politely.

- **The Local Models refresh button.** It was never broken. It fetched, it updated, it just did so
  invisibly: no spinner, and because Ollama was already running the answer came back identical, so
  not one pixel changed. It now spins while checking and shows the time it last checked, so an
  unchanged answer still looks like an answer.

- **The dashboard toolbar.** The "Last run" time sat underneath the auto-refresh dropdown, making
  that side of the bar two rows tall while the buttons beside it were one, so nothing lined up. It
  is one row now.

- **A test file that could only be run with company.** Not reported, found on the way past: the
  exports module imported the chat module while the chat module imported exports, so the export
  tests only passed when another test dragged the chat module in first. Running them alone failed on
  untouched code. The import now happens where it is used.

Task 8 is now genuinely complete; it had been recorded as complete while three real defects were
still in it. Regression tests lock in the two failures a user would actually notice: a file request
with the planner on must still reach the file builder (verified to fail against the old code), and a
generated file must not carry Orrery's name.

Verified: all 543 backend tests pass; all 38 UI tests pass; the production UI build succeeds.

Next: Task 9 - serve the private bundle through a session-gated, CSP-locked route and open it only
inside a sandboxed iframe, while preserving the ZIP download.

## Step 146 - A full architecture map people can actually read (July 16, 2026)

Orrery now has one durable architecture document that maps the system from the outside in. It
shows the desktop launch, all workspace areas, the Python modules, a complete Chat turn, data and
retrieval, dashboard creation and refresh, durable Automations and Agents, storage ownership, and
the security chain as separate Mermaid diagrams instead of squeezing everything into one unreadable
box chart.

The map was checked against the current code rather than copied from the original roadmap. That
matters because the app has grown: Electron is now the desktop direction, Agents and Dashboards are
wired through the interface, the shared tool and job layers are real, and the Automations and Media
Hub screens are still at different stages of connection. The document says those differences
plainly so a future contributor does not mistake a working backend engine or a polished screen for
an end-to-end feature.

No runtime behavior changed. This was a documentation-only pass.

## Step 147 - One clear story per architecture diagram (July 16, 2026)

The first architecture map was accurate, but several pictures tried to explain too many
relationships at once. That made arrows cross between unrelated parts and forced the reader to
decode the whole application before understanding any one flow.

The document now moves in layers: system context, workspace, live request path, background work,
startup, backend boundaries, and then one focused map per feature. Data access, imported datasets,
document ingestion, retrieval, dashboard design, dashboard refresh, Automations, Agents, the shared
tool gate, storage, and each security boundary all have their own small picture. Every flow has one
direction and one question to answer. Repeated decorative colours and large all-to-all component
maps were removed.

The underlying architecture did not change. This was a readability and information-design pass.

Next: finish and verify the safe interactive preview for small app bundles, then keep these focused
maps current whenever a major boundary or feature moves.

## Step 148 - The architecture map now follows executable code, not the mockups (July 16, 2026)

The architecture document has been rebuilt after reading the runtime, API registration, Chat
orchestration, model adapters, shared tools, storage models, data paths, retrieval, dashboards,
agents, workflow engine, desktop shells, security boundaries, and the React views themselves. Each
diagram now names the implementation files that prove it.

That deeper pass corrected several important assumptions. Automations has a real backend workflow
engine but no registered API route, no workflow scheduler, and only a hard-coded UI. Media Hub is a
static screen, although Chat can generate media files through its separate file pipeline. Chat does
not directly start Agents, run workflows, or create dashboards. Agent Slack, Gmail, and API triggers
exist in configuration and storage but have no inbound receivers. LIFE learning creates reviewable
proposals, but LIFE.md is not injected into ordinary Chat and the agent LIFE permission is not yet
used by the run loop. The document also distinguishes the strict no-network app-bundle preview from
the more permissive generic HTML preview instead of treating them as the same boundary.

The result is deliberately honest about four states: live end to end, conditional, backend only,
and static UI. No runtime behavior changed; this was a code-derived documentation correction.

## Step 146 - Runnable app bundles, and a batch of reported fixes (July 16, 2026)

Two threads landed together: the app-bundle feature reached the point where you can actually use a
generated app, and a run of reported problems got fixed at the root.

- **You can now run a generated app.** Small apps were being built and stored but nothing served
  them, so they were dead files. There is now a read-only route that serves a bundle's own files
  into a sandboxed panel, and the chat file card gained "Open app" alongside "Download ZIP". The
  serving is deliberately locked down: the app runs in a walled-off frame that cannot reach the
  network or touch the workspace, each app has an unguessable address, and requests cannot escape
  the app's own folder (tested against a spread of path-escape tricks).

- **Dashboards were dead, and the reason was a packaging gap.** Every widget showed "No module named
  'sqlglot.dialects.postgres'". The SQL checker loads its Postgres knowledge by name at run time,
  and the packaged app had not bundled that piece. Two fixes: the checker now falls back gracefully
  so dashboards work even in the current build, and the build now includes the missing piece for
  next time.

- **The biggest complaint — settings resetting on close — is fixed.** The desktop window was running
  in a private/incognito mode that throws away all saved preferences when the app closes, so a theme
  or layout choice never survived a restart. It now remembers. (Your actual data was always safe in
  the database; only the on-screen preferences were being discarded.)

- **The light themes are usable again.** In Winter and Summer, chat text was a pale colour baked for
  the dark themes, so it vanished on a light background; the selected Skills/MCP tab was a dark block
  with barely-visible text; and the Automations toolbar was a dark slab. All three now follow the
  active theme. The two captions on the Appearance page are centred under their cards.

Still open from this report and queued next: an SVG request that is confirmed with "do it" can come
back as a PDF containing the SVG's source text instead of a picture (a routing choice worth verifying
against the full scenario matrix); the dashboard edit flow shows "working" without showing what it is
doing; local models cannot yet reach the code/tool capabilities (a boundary question that deserves a
design pass); a dedicated dashboard-editing side tab; and a conservative dead-code/unused-file sweep.

Verified: all 562 backend tests pass; the UI builds; the app-serving route was checked live against a
real server for headers, MIME, and traversal.

Next: Task 10 - app-intent routing polish and the heavy-scenario tests, then Checkpoint 3.

## Step 149 - Connected Chat tools hardened and long history preserved (July 22, 2026)

The remaining Chat, retrieval, MCP, web-search, and sandbox review work landed as one verified
security pass. Web search now requires a visible choice for each message and resets after sending;
common personal details and secret-looking values are masked before a search query leaves the
computer. Web and approved MCP tools no longer depend on Docker being available, while Python and
shell execution still require the current locked-down sandbox.

MCP servers now launch as fixed argument lists without a shell, inherit only a small operating-system
environment plus that server's own keychain values, refuse pending/disabled execution, bound their
messages and output, and terminate timed-out process trees. The sandbox now verifies its image
version and tightens code/input, scratch/output, file, process, memory, CPU, network, and time
boundaries. PDF ingestion prefers that same offline boundary and adds scanned-page OCR.

Long conversations now hydrate history backward until the selected model's token budget is covered,
instead of silently losing early facts at a fixed message count. Retrieval also rejects weak vector
matches more carefully, and the architecture map was added to version control.

Verified: 616 backend tests passed, including 96 focused Chat/security tests; the production UI build
succeeded. Commit `f6f1c2d` was pushed to `feature/plan-remaining`.

## Step 150 - One architecture, one plan, one TODO, one completed-work log (July 22, 2026)

Orrery's work documents had grown into several overlapping plans. Some described features that had
already shipped, some still called working screens “not started”, and one checklist said the root
architecture file was untracked after it had already been reviewed, committed, and pushed. That made
the next task depend on which old file someone happened to open.

The repository now has four clear sources of truth: `ARCHITECTURE.md` describes executable behavior,
`PLAN.md` holds direction and dependency order, `TODO.md` contains unfinished actions only, and this
DEVLOG remains the append-only completed-work history. Valid security and product gaps were reconciled
against code before being moved. Superseded planning, migration, architecture-review, and duplicate
task files were removed; READMEs, the documentation site, LIFE pointers, code comments, and ignore
rules now point to the canonical files. The local Orrery development skill also points to those files
instead of carrying a second architecture and roadmap that could drift.

The audit also corrected two misleading product claims. Agent API, Slack, and Gmail receivers are now
reported as unavailable until they actually exist, and Chat no longer promises that `/` can “run
anything” while agent/workflow/dashboard command paths are still unfinished. A regression test locks
the Agent catalog contract. The public feature summary now distinguishes live paths from backend-only
or static screens and calls out the temporary dataset-URL credential limitation.

Verified: 617 backend tests and 38 UI tests pass, the production UI builds, Markdown links and stale
document references are clean, the revised documentation page renders at desktop and narrow browser
widths, and an independent five-axis review found no Critical or Required issues.

Next: execute `TODO.md` from P0 downward, beginning with the shared approval gate and fail-closed
team/admin authorization; keep future status changes in the four canonical documents only.

## Step 151 - P0 trust boundary closed: approvals, fail-closed identity, guarded fetches, clean URLs (July 22, 2026)

All six P0 security items landed as one pass, designed so day-to-day use barely notices them.

A central approval gate now sits in the shared tool registry, below the model. It is risk-tiered so
it rarely asks: read-only tools, sandboxed code, and file generation never prompt; only tools with
external or destructive effects (MCP calls, Crabbox) pause the chat turn with an inline card. An
approval is bound to a digest of the exact validated arguments, is single-use, and expires — so a
granted click cannot be replayed or repointed at different arguments. "Always allow" is remembered
per user (and per server+tool for MCP), so a trusted tool asks once, not per call. Agent runs keep
their existing durable approval flow; a disabled tool refuses cheaply before any prompt appears.

Identity now fails closed. A database or configuration error reports team mode with a locked
identity instead of silently promoting the caller to solo-admin; feature gates disable for team
callers when their restrictions cannot be read; and founding a team requires a successful query
proving no team exists — an outage is not first-run evidence. Solo mode on a healthy machine is
unchanged.

Outbound fetches for dataset imports and the Automation HTTP node go through one guarded helper:
every redirect hop is re-validated (scheme, credentials, host, port, and every resolved address),
the connection is pinned to the validated IP so a DNS answer cannot change between check and
connect, bodies stream into a hard byte cap instead of buffering first, low service ports are
blocked, and auth headers are dropped when a redirect leaves the original host. The Google Sheets
refresh path, which previously had no size cap at all, now shares the same guard.

Dataset API URLs no longer persist credentials: secret-looking query parameters are stripped into
the OS keychain, only a redacted canonical URL is stored and shown (legacy rows are redacted on
read), refresh resolves the real URL from the keychain, and import/refresh errors are scrubbed
before they reach the interface.

Verified: 648 backend tests pass (31 new abuse-case regressions covering approval replay/tampering/
expiry, database outages, redirect chains to blocked hosts, redirect loops, oversized bodies, pinned
connections, and credential-bearing URLs), 38 UI tests pass, and the production UI builds.

Next: Workstream 2 — the bounded document worker, deterministic test groups, and the web-search
provider interface.

## Step 152 - Review pass hardened three edges of the new boundary (July 22, 2026)

An adversarial review of Step 151 confirmed three real weaknesses, all fixed the same day. The
Google-Sheets fetch path chose its branch by substring, so a URL that merely mentioned the sheets
host could take the relaxed fetch on refresh and follow a redirect into the local network in team
mode — the branch now requires the host to actually be docs.google.com and applies the team-mode
address policy. "Always allow" could turn one benign approval of the remote executor into standing
permission for arbitrary future commands — destructive-risk tools are now never rememberable and
ask every time, and the checkbox disappears from their card. The secret-parameter detector missed
common names like pwd, pass, jwt, bearer, and session — the match list is broader now, biased
toward over-masking because the display URL is cosmetic while the real URL lives in the keychain.

Verified: 651 backend tests pass (3 new regressions), the production UI builds.

## Step 153 - Documents preview like documents, not text dumps (July 22, 2026)

The user's Workstream 2 priority: files Orrery creates or receives should look right in the
viewer using Python libraries alone, without depending on the optional LibreOffice converter.
The Python fallback renderers were rebuilt for fidelity, all inside the existing preview budgets.

Word previews now keep bold/italic/underline and font color at the run level, paragraph alignment,
and embedded pictures (inlined with count and byte caps); headings stay clean plain text. Excel
previews keep merged cells (real row/column spans), bold/fill/color/alignment per cell, column
widths, and readable number/date formatting. PowerPoint previews place every shape at its true
position and size on a correctly proportioned slide, with per-run font size/color scaled to the
render width, pictures inlined, and tables rendered — instead of the old title-plus-bullets card.
CSV and TSV files render as real tables with delimiter sniffing, and Markdown renders as formatted
HTML where raw HTML is escaped and remote images are never fetched. File creation already used
Python libraries (reportlab, python-docx, openpyxl, python-pptx) plus the sandbox; this closes the
viewing half of that promise.

Verified: 658 backend tests pass (7 new preview-fidelity regressions and one adjusted heading
assertion), the full suite stays green. ODF/RTF coverage remains tracked in TODO.md.

## Step 154 - Orrery is delivered to your own browser (August 18, 2026)

Orrery stopped shipping a window. The Electron shell and the pywebview window were both removed, and
`orrery web` now starts the local backend and opens whatever browser the user already has. Nothing
about local-first changed: the backend, PostgreSQL, the keychain, and the Docker sandbox all still
run on the user's machine. What went away was the packaging tax - code signing, notarization,
per-platform installers, and a bundled Qt WebEngine runtime that existed only to draw a window
around a page FastAPI was already serving.

The security consequence needed real work. A real browser is not a window Orrery controls, so the
old `?token=` handoff would have left the session credential in history, in bookmarks, and readable
by extensions. The launcher now mints a single-use launch code; the page trades it for an httpOnly
session cookie and strips it from the address bar. Cookie-authenticated requests also carry an
Origin check, because cookies ignore port: `http://127.0.0.1:<other port>` is same-site with Orrery,
so `SameSite=Strict` alone would let another local process drive the API. Header authentication
stays for clients that use `X-Orrery-Token`, and needs no Origin check, because a cross-origin page
cannot set a custom header without a CORS preflight Orrery never grants.

This step turned that into something a person can actually install. `pyproject.toml` makes `orrery`
a real console script, so the whole install is `pip install -e .` plus one UI build. Startup now
fails loudly when the workspace bundle is missing instead of serving a blank page, and everything
the CLI prints is ASCII - an em dash in a startup message crashes on a legacy Windows console. The
Electron-wrapped Windows and macOS installer scripts were deleted along with the shell they wrapped;
the two portable package builds survive and no longer bundle pywebview or Qt WebEngine, and they now
assert that WebEngine is absent rather than present. The new CI workflow was also repaired: it ran a
linter that had never been installed and a formatter this tree has never been run through.

Documentation was reconciled with all of it: the README leads with the browser install, ARCHITECTURE
describes the startup handshake and the two authentication paths that exist today, and the published
guide no longer tells people to download an installer that is not built any more.

Verified: 84 tests across the session, API, CLI, startup, packaging-contract, and import groups pass,
including 10 new CLI regressions covering the default mode, `--no-browser`, the build/service flags,
unknown arguments, and the missing-bundle failure. `ruff check .` is clean against the newly pinned
configuration. The live browser round trip is still unproven - the tests cover the boundary, not the
handshake in a real browser.

## Step 155 - CI runs against a real database instead of failing against none (August 18, 2026)

The pipeline introduced with the browser delivery had never been able to pass. It ran the whole
backend suite on three operating systems without providing a database, and 38 tests across six
files need one: they call `run_migrations()` and write real rows. Measured here, that configuration
fails 38 and passes 654. The suite is not slow and does not hang on its own - with PostgreSQL up it
finishes in about 40 seconds and is fully green.

The earlier "some combination hangs with no output" note turned out to be the same root cause seen
from the other side. A database that is *configured but unreachable* does not fail fast the way an
*unconfigured* one does; psycopg keeps retrying until its connection timeout expires, so the run
stalls silently and, in CI, would have burned the job limit with nothing on screen.

CI is now two backend jobs instead of one three-OS matrix. Ubuntu runs the complete suite against a
`pgvector/pgvector:pg17` service container - the same image `docker-compose.yml` uses, so CI and a
developer laptop agree on the available extensions - and sets `ORRERY_REQUIRE_DB=1`. macOS and
Windows cannot host service containers, so they run `-m "not db"`. Splitting this way is what makes
the skip honest: the `db` tests are covered on Linux rather than quietly dropped everywhere.

The `db` marker carries that split. Without a database a marked test skips with a reason that names
the fix (`docker compose up -d`); under `ORRERY_REQUIRE_DB=1` the same condition is a hard failure,
so the job that spun a database up can never silently skip the coverage it exists to provide. Every
job now has `timeout-minutes`, `pytest-timeout` bounds each test at 120 seconds, and `--durations=10`
publishes the slowest tests - together these mean a future hang names itself and dumps its stack
instead of stalling in silence.

Verified: the Linux path (database provided and required) passes 692 tests; the cross-platform path
(no database) passes 634 with 58 deselected, where it previously failed 38; the require-a-database
guard was confirmed to fail rather than skip; `ruff check .` is clean; and a deliberate 30-second
hang was confirmed to be cut off and reported against the test's own name.

Next: the launch handshake still needs its real-browser round trip, and the remaining feature groups
are still one undifferentiated run.

## Step 156 - The app was starving its own backend (August 18, 2026)

Orrery felt slow to the point of being unusable: switching tabs stalled, and the backend sometimes
stopped answering altogether. Three separate defects were behind it, all found by measuring rather
than guessing.

The largest was a one-line mistake in the launcher. After the backend signalled readiness, `main()`
idled with `while not _boot_error: _ready.wait(timeout=1.0)` - but `_ready` is *set* by that point,
and waiting on a set Event returns immediately. The main thread therefore span as fast as Python
could go, and because it held the GIL, it starved the event loop running in the backend thread. The
cost was measured by A/B against the identical app with the loop removed: a trivial 404 went from
530ms to 4.6ms, `/api/health` from 350ms to 2.4ms, and the 1.1MB Dashboards chunk from 2.4s to
12ms. The idle wait now uses a `_stopped` Event that stays unset while Orrery runs, so each
iteration really does sleep for a second.

The second was `GET /api/models` importing litellm on the event loop. That import walks the whole
litellm package and costs about 4.7s of pure CPU on a warm filesystem; doing it inside an `async def`
blocked every concurrent request, which is why the first fetch of the Dashboards chunk once took
239 seconds. The import now happens in a worker thread, and startup warms it in the background so
no user request pays for it at all.

The third was a promise the code made and never kept. `_FreshHtmlStatic` documented that
content-hashed assets "can cache forever", but only ever set `Cache-Control` on index.html, so the
browser revalidated every chunk on every load at 200-385ms each. Fingerprinted assets under
`/assets/` now carry `public, max-age=31536000, immutable`, while index.html stays uncached so a
new build is always picked up.

Verified: 697 backend tests pass (5 new regressions covering the idle wait, the off-loop model
metadata call, and the two cache headers), `ruff check .` is clean, and the measurements above were
taken against the running app before and after. One of the new tests caught a real bug in the fix
itself: Starlette normalises static paths with `os.path.normpath`, so the asset check had to match
Windows' backslash separator too.

Next: the Home view still fires eleven API calls on mount, and the route chunks are not prefetched -
both worth revisiting now that the per-request floor is milliseconds instead of half a second.

## Step 157 - Policy attaches at a seam instead of another inline branch (August 18, 2026)

The user asked for four properties from DeepSeek Harness: hook seams around the agent loop, a
session log that supports fork/resume/replay, layered configuration, and plugin mounting. ADR-004
records the design for all four and the order they depend on each other in. This step is the first
of them, because the later three attach to it.

The borrowed idea is that policy should register at a named extension point rather than be added as
another branch inside the loop. Orrery's version differs on one rule, and that rule is the reason
it is safe to have at all: **a hook may deny, observe, or annotate, but never grant.** The existing
guards in `run_tool()` - scope allow-list, feature gate, grant actions and resources, argument
validation, the central approval gate - all still run and still have the final say. A hook that
returns nothing has not approved anything; it has only declined to object. Deleting every hook
leaves behavior exactly as strict as before.

Two seams exist now. `tools/pre-execute` runs in `run_tool()` after every built-in guard and before
the approval gate, so a denial never raises a pointless approval prompt, and it covers Chat,
Automations, and Agents at once because all three already funnel through that one function. An
agent `pre-step` seam runs before each model request in a run and can stop the run. Registration
returns an unregister callable, so a mounted hook can be taken back off - the reversible-effect
property the plugin step will need. A hook that raises is treated as an objection, never as
consent.

Verified: 706 backend tests pass, including 9 new ones that pin the deny-only contract - a
permissive hook cannot revive a call the allow-list refused, an unknown tool stays unknown however
many hooks pass it, a broken hook fails closed, the first objection wins, and unregistering really
detaches. The seam was also exercised against the live registry, where it blocked a destructive
tool before the approval gate and recorded which hook did it.

Next: the remaining three ADR-004 steps - session log fork/resume/replay, configuration layering,
then plugin mounting.

## Step 158 - Agent runs can be replayed and forked from their own log (August 18, 2026)

The second ADR-004 step. The harness idea being borrowed is "model-visible means logged": if every
model request is reconstructible from an append-only log, then fork, resume, and replay follow for
free. Orrery already half had this - `_transcript()` has always rebuilt an agent's model-bound
conversation from `agent_run_steps` rather than from memory, which is why a run could survive a
restart. What was missing was any way to use it.

`replay()` returns the messages a run's log reconstructs to, optionally truncated at a step. It is
the honest answer to "what did this agent actually see", and it is how a fork can be inspected
before it is started. `fork_run()` branches a new queued run from an existing one, copying the steps
up to a chosen point, and optionally replacing the input so the same context can be asked a
different question.

Two details matter more than the feature. A fork reuses the *source run's* version and config
snapshot rather than the agent's current settings, so branching re-runs what actually ran instead of
whatever the agent has been edited into since. And the copied steps keep counting toward the
step budget, so forking cannot be used to walk past a limit the original run hit. Both are
owner-scoped with the same filter `get_run()` uses, and both are exposed as
`GET /api/agent-runs/{id}/replay` and `POST /api/agent-runs/{id}/fork`.

Verified: 713 backend tests pass, including 7 new ones covering reconstruction from the log,
truncation, carrying the log into a branch, replacing the input, refusal of unknown runs, and that
another owner can neither replay nor fork a run they do not own.

Next: ADR-004 steps three and four - configuration layering, then plugin mounting.

## Step 159 - Configuration has layers, and says where each value came from (August 18, 2026)

The third ADR-004 step. A setting could previously come from exactly two places - a field default or
`.env` - and there was no way to ask why a value was what it is. Harness designs answer that with
ordered layers plus a command that dumps the resolved tree; this is the same idea at Orrery's scale.

Five layers now resolve, lowest precedence first: field defaults, a checked-in `orrery.toml` beside
the project (or `ORRERY_PROFILE`), a `config.toml` in the per-user data directory that survives
reinstalling the app, `.env`, and finally real environment variables, which still always win.
Nothing about existing setups changes: with no TOML files present the resolution is exactly what it
was. Both file layers accept either a flat table or an `[orrery]` section, unknown keys are ignored
rather than fatal, and malformed TOML raises a clear error instead of being silently dropped - a
config file that does not parse should not look like a config file that is absent.

`orrery --dump-config` prints every setting, its value, and the layer that supplied it, then exits
without touching the database, the server, or a browser. Values whose names look credential-shaped
are redacted through the existing scrubbers, so the output can be pasted into an issue: the local
database URL shows as `postgresql+psycopg://orrery:****@127.0.0.1:5432/orrery`. No secret is read
from or written to any layer - provider keys and the real connection string stay in the OS keychain.

Verified: 725 backend tests pass, including 12 new ones covering precedence in both directions,
flat-versus-sectioned files, unknown keys, malformed TOML, provenance reporting, redaction, and that
`--dump-config` starts nothing. Each test points all three layers at a tmp_path so none of them read
the developer's real configuration.

Next: the last ADR-004 step, plugin mounting, which reads a layer declared here and registers into
the seam from Step 157.

## Step 160 - Plugins mount, and can only ever say no (August 18, 2026)

The last ADR-004 step, and the one that had to be narrowed the most. In the harness this was
borrowed from, a plugin can replace any capability from configuration - including the agent loop and
the tool registry. Read literally against Orrery's threat model, that is a way to configure the
approval gate out of existence, so Orrery's version keeps the seam and drops the replacement.

A plugin is an importable module named in a configuration layer (`plugins = ["..."]` in
`orrery.toml`). Mounting imports it and calls `setup(ctx)`. The context it receives exposes exactly
two things: register a pre-execute hook, and register a pre-step hook. Both are deny-only, both run
after every built-in guard, and neither can widen a grant or approve a call the allow-list already
refused - there is a test that mounts a plugin whose hook approves everything and confirms an
out-of-scope tool is still refused.

Everything a plugin registers is recorded, so `unmount_all()` takes it all back off. A plugin that
raises part-way through `setup()` has its earlier registrations rolled back rather than left
half-applied, because half a policy is not a policy. A declared plugin that cannot be imported is a
startup failure, not a warning: the user asked for that policy, and running without it silently is
the least safe outcome available. Nothing is fetched - a plugin name must be a module path, and
anything resembling a URL or a filesystem path is refused before import.

Verified: 735 backend tests pass, including 10 new ones covering mounting, a hook that really
denies, the permissive-plugin case that must still be refused, reversal on unmount, rollback of a
half-failed setup, missing `setup`, unimportable modules, and hostile names.

That completes the four properties from ADR-004: the seam (Step 157), fork and replay over the
durable log (Step 158), configuration layers with provenance (Step 159), and plugin mounting here.

## Step 161 - The tests that only ever passed on Windows (August 18, 2026)

CI was still red, and local runs could not see why: every configuration passed on this Windows
machine. Reproducing the Linux job in a container found it immediately - eight tests encode
assumptions that are true on Windows and false everywhere else.

Two frozen-path tests built a fake executable at `C:/packages/...`. That is an absolute path on
Windows and a *relative* one on Linux and macOS, so `app_dir()` resolved it against the working
directory and the assertion drifted to `/app/C:/packages/...`. They now build the fake path from a
root that is absolute on the host they run on.

Five failed because PySide6 could not import: `libGL.so.1` is not on a bare Linux box, and QtPdf
pulls it in through QtGui. Two of those already tried to guard themselves with
`pytest.importorskip`, which was not enough because the loader raises `OSError` as well as
`ImportError` for a missing shared library. They now share a `requires_pdf_renderer` marker built on
`filepreview.pdf_renderer_available()` - the same check the application uses - so a skip means the
renderer genuinely cannot run here rather than that the test is broken. The file-preview status
route test was asserting `available: True` outright; it now asserts against that same runtime check,
which is the honest claim, and keeps asserting what it is actually named for: that the route is
authenticated and does not leak the converter's path.

The last one drove the WinGet installer, which the code deliberately refuses off Windows. It is
marked Windows-only now, and a companion test pins the refusal on the other platforms so they are
not left unasserted.

Skipping the renderer everywhere would have quietly dropped Linux PDF previews from coverage, and
`requirements.txt` says in as many words that QtPdf is needed on every platform, Linux included. So
the Linux job also installs the Qt runtime libraries and sets `QT_QPA_PLATFORM=offscreen`, which is
what lets those five tests really run there instead of skipping.

Verified against all four job configurations: Linux without a database 665 passed, Linux with one
730 passed, Windows without a database 670 passed, Windows with one 735 passed, and `ruff check .`
clean on both platforms. The Linux numbers came from running the jobs' exact commands in a
python:3.12-slim container.

## Step 162 - Grok, Qwen, and GLM are pickable; the local list caught up (August 18, 2026)

The user asked for the current generation of models across vendors. Claude and GPT needed nothing:
those catalogues are fetched live from the provider and curated by tier, so new releases appear on
their own. Three vendors genuinely were not reachable, and one was frozen.

**xAI (Grok)** and **Alibaba DashScope** are new keyed providers. Both APIs are OpenAI-compatible
and both prefixes - `xai/` and `dashscope/` - are routed natively by the installed litellm, which is
where the model ids were checked rather than recalled. DashScope is what makes **GLM** reachable: it
serves the GLM family alongside Qwen, so one provider covers both, and its curation deliberately
reserves a slot for a GLM so Qwen cannot crowd it out. GLM is also now kept from OpenRouter
(`z-ai/`), along with Moonshot's Kimi.

**DeepSeek** had been a hard-coded pair of models since it was added, which silently hid everything
they shipped afterwards - `deepseek-v4-pro` and `deepseek-v4-flash` among them. It asks the provider
now, and falls back to the known pair only when the API cannot be reached.

Adding providers exposed an existing bug in Settings: the model list rendered
`order.filter(p => groups[p])` against a hard-coded array, so any provider missing from that array
had its models silently dropped from the screen. OpenRouter has been invisible there for exactly
that reason. Known providers still lead in a deliberate order, but anything else the backend reports
now follows alphabetically instead of vanishing.

The local catalogue went from 22 to 38 models, adding gpt-oss (20B/120B), Qwen3-Coder, Qwen3-VL,
GLM-4, Llama 4 Scout, Devstral, Magistral, Mistral Small 3.2, Phi-4 Reasoning, Granite 4, Gemma 3n,
MiniCPM-V, and SmolLM2. Every name and size was verified against the Ollama registry - the sizes are
summed from each model's actual manifest, not estimated, and one candidate that did not exist
(`granite4:small`) was dropped rather than guessed at.

Verified: 744 backend tests pass, including 9 new ones asserting the litellm prefixes, that curation
keeps a GLM beside a Qwen, that DeepSeek picks up models beyond the old pair and still falls back
offline, and that each new provider is registered in all four places a provider has to appear.
`ruff check .` is clean and the production UI builds.

## Step 163 - Documentation caught up with the version that exists (August 18, 2026)

Four steps of behaviour had landed without the docs following. This reconciles them.

ARCHITECTURE gained a section for the composability layer - the five configuration layers, the two
deny-only seams and where they sit relative to the built-in guards, plugin mounting and its
rollback rules, and replay/fork over the durable run log. Its startup sequence now shows plugins
mounting and model metadata warming, and the model-routing section names the eight key-gated
providers, says that catalogues are fetched from the provider rather than hard-coded, and records
why LiteLLM's metadata import never runs on the event loop.

The README documents the provider list including xAI and DashScope, the ~38-model local catalogue,
`orrery --dump-config`, and a new section on configuration layers and plugins with a worked example
of a policy hook - including the sentence that matters most, that returning `None` from a hook means
"no objection" and never "approved".

The published pages were still selling something that no longer exists: the landing page told people
to "open the latest release for your platform" when the installers were deleted with the desktop
shell, so it now leads with the checkout install and `orrery web`. Both it and the user guide list
the providers that can actually be connected today.

One real drift turned up while writing this: the `[dev]` extra in `pyproject.toml` listed only
pytest and ruff, so the install path the README recommends would have missed `pytest-timeout` and
silently run without the per-test timeouts that `pytest.ini` now depends on. Both dependency lists
agree again, and the README documents the `db` marker alongside them.

Verified: 744 backend tests pass, `ruff check .` is clean, the production UI builds, and every
relative link in the README resolves.

## Step 164 - The frontend stopped making you wait for it (August 18, 2026)

With the backend answering in about four milliseconds, the remaining delay when switching tabs was
entirely on the client, and it was two things.

Every view is its own lazily-loaded chunk, which is right for the first paint but meant each tab's
first visit paid a network round trip plus a parse. The chunks are now warmed while the browser is
idle: one at a time, each waiting for the next idle slot so the warm never competes with the tab the
user is actually looking at, in a deliberate order with Dashboards last because it is much the
largest and paying for it early is the one prefetch a person could feel. A failed warm is swallowed
- the real visit retries it.

Dashboards imported all of echarts for three chart types. `chartOption()` maps every widget onto
pie, line, or bar and nothing else, so the modular build registers exactly those plus the grid,
tooltip, and canvas renderer they need: the chunk fell from 1143KB to 566KB. The registration list
carries a comment saying that a new widget type has to be registered there too, because the failure
mode is an empty canvas rather than a loud error.

One thing measured and deliberately left alone: the Home view fires eleven API calls when it mounts.
That looked alarming while the backend floor was half a second, but they run concurrently against an
endpoint that now answers in milliseconds, so the whole burst finishes well inside a tenth of a
second. Adding a cache layer would be complexity without a measured problem. The Chat chunk is
390KB, most of it highlight.js grammars, and narrowing that set is a real option if code blocks in
uncommon languages turn out not to matter.

Verified: 744 backend tests and 38 UI tests pass, `ruff check .` is clean, and the production bundle
builds with the new chunk sizes.

## Step 165 - Vulnerable dependencies upgraded and the lockfile made true again (August 18, 2026)

The default branch had been carrying a growing Dependabot list, and the lockfile had drifted far
enough that it no longer described the application. Both were audited directly rather than read off
the alert page.

`pip-audit` found real advisories in five packages. Two of them matter more than the rest for this
codebase: **pypdf** (6.13.3, six advisories) and **pillow** (12.2.0, sixteen) are exactly the
libraries that parse documents and images a user did not write, which is the threat the untrusted-
document boundary exists for. `aiohttp`, `h2`, and `setuptools` were the others. After upgrading -
pypdf 6.16.1, pillow 12.3.0, aiohttp 3.14.3, h2 4.4.1, setuptools 84.0.0 - `pip-audit` reports no
known vulnerabilities. On the frontend, `npm audit` found two high-severity build-time transitives
(nanoid, postcss); both are fixed and it reports zero.

`requirements.lock.txt` was worse than out of date: it still pinned `pywebview` and `QtPy`, packages
deleted along with the desktop shell, and it pinned the vulnerable pypdf and pillow. They kept
reappearing in a regenerated freeze because they were still *installed* in the development
environment even though nothing depends on them any more, so they were uninstalled first and the
lock regenerated from a clean tree. Its header also lost its section symbol to an encoding slip at
some point; it reads as plain text now. The direct floor in `requirements.txt` moved to
`pypdf>=6.15.0` so a fresh install cannot resolve back to a vulnerable version.

Verified: 744 backend tests and 38 UI tests pass with the upgraded libraries - including the PDF and
Office preview tests, which are the ones that would notice a pypdf or pillow regression - `ruff
check .` is clean, and the production bundle builds.

## Step 166 - Automations has an API to talk to (August 18, 2026)

The Automations engine, its node registry, and a full CRUD layer in `backend/features/workflows.py`
have all existed for a while. What did not exist was any way to reach them: no route in the entire
API mentioned a workflow, which is why the screen renders a hard-coded node list and cannot save
anything. This is the missing surface.

Nine operations across five paths: list/create workflows, get/patch/delete one, start a run, list
runs, read one run with its durable per-node steps, and `GET /api/workflow-nodes`, which returns the
registered node catalog with each node's JSON schema. That last one is the point of the registry
pattern - the canvas can build its palette and its per-node settings form from the registry, so
adding a node class to `backend/automation/nodes.py` makes it appear in the UI with no second list
to maintain.

Ownership is enforced in the CRUD layer against `team.current_owner_id()`, and a workflow belonging
to someone else reports as absent rather than forbidden, which matches the rest of the API and does
not confirm that an id exists. Two boundary behaviours needed care. A spec that names an unknown
node type, repeats a node id, or exceeds the node cap has to reach the client as a 400 carrying the
reason, because that message is what a user can act on. A malformed id has to read as "not found"
instead of a 500 - the CRUD layer parses ids with `uuid.UUID(...)`, which raises the same
`ValueError` that spec validation does. The first draft told them apart by matching on the exception
text, which would have silently turned a validation failure into a 404 the moment a message changed;
ids are checked explicitly at the route boundary instead.

Verified: 752 backend tests pass, including 8 new ones covering token enforcement on every route,
the catalog coming from the registry rather than a fixed list, create/list/get/delete, both
validation refusals, junk ids on every route that takes one, and that a real run records durable
steps. `ruff check .` is clean.

Next: the Automations screen itself - the TODO entry now names the exact endpoints it needs.

## Step 167 - The Automations screen shows the database instead of a mockup (August 18, 2026)

Automations was a design mockup wearing the app's styling: a fixed list of three invented workflows,
an eight-item node palette written by hand, a canvas of six fake nodes posting to an imaginary Slack
webhook, and three fabricated run histories. None of it touched the engine that has been able to
execute workflows for months. With the API from Step 166 in place, the screen now renders what
actually exists.

The sidebar lists real workflows with their real enabled state, node count, and last-updated time,
and creating one writes a row. The palette is `GET /api/workflow-nodes`, so it lists the eleven
registered node types across all six categories the registry defines - add a node class to
`backend/automation/nodes.py` and it appears here with no second list to update. The canvas draws
the selected workflow's saved spec, with edges derived from the spec rather than a hard-coded list,
and the inspector shows a node's real saved configuration beside the setting names its JSON schema
accepts. Run history is real runs with real statuses and durations; expanding one fetches that run's
durable steps and shows each node's status, output, and error.

The visual design is untouched - same markup, same classes - because the point of this step was to
stop the screen lying about what it contains, not to redesign it.

It is honest about what it still cannot do. There is no canvas editing: a workflow with no nodes
says so and explains that a spec saved through the API will appear, rather than implying a drag
target that does not exist. Node positions come from the spec when present and fall back to a grid
when absent. "Run now" is disabled on a paused workflow because the API refuses that anyway, so the
button reflects the rule rather than discovering it in an error.

Verified: 752 backend tests and 38 UI tests pass, `ruff check .` is clean, the bundle builds, and an
end-to-end pass through the API - create, save a two-node spec with an edge, run it, read the run -
returned exactly the shapes this screen reads, with both nodes recorded as done.

## Step 168 - Installing Orrery is one line now (August 18, 2026)

Getting Orrery running took eight commands: clone, copy `.env`, create a virtualenv, activate it,
install, `npm install`, `npm run build`, `docker compose up`. Tools people compare this to install
with one. Most of that list turned out to be unnecessary rather than hard.

Two of the steps were already automatic and nobody had noticed: `dockerboot.provision()` has been
starting Docker Desktop and bringing up PostgreSQL on first run for a while, and `.env` is only for
overriding local development settings - the connection string lives in the OS keychain. That left
the workspace bundle as the one genuine blocker, and startup handled it by refusing to start with
instructions. The build is deterministic and needed exactly once, so Orrery now runs it: `npm ci`
(or `npm install` without a lockfile) then `npm run build`, with the output left on the console
because a silent minute looks like a hang. `--no-build` keeps the old refusal for a machine without
Node, and a packaged build never builds anything because it ships the bundle.

The whole install is now `git clone … && cd Orrery && pip install -e . && orrery`.

Testing that claim properly - deleting `ui/dist` and starting cold - immediately found a bug the
unit tests could not: on Windows, `shutil.which("npm")` can return the extensionless shell script
rather than `npm.cmd`, and `CreateProcess` refuses it with "%1 is not a valid Win32 application".
Windows asks for `npm.cmd` first now. The second cold start built the bundle and served the
workspace with no manual step at all.

Two documentation files still described the deleted Electron shell: `scripts/README.md` documented
`../desktop/electron/`, which is not in the repository at all, and `assets/README.md` called the
application icons "installer icons". Both now describe what exists. (A `desktop/` directory is still
sitting in the working tree, but it is untracked - local leftovers rather than repository content.)

Verified: 759 backend tests pass, including 7 new ones covering the present-bundle fast path, a
fresh checkout building once, `--no-build`, a frozen build never shelling out, a missing npm naming
what to install, and a failed build reporting the command that actually ran. `ruff check .` is clean,
and the cold start was exercised for real rather than mocked.

## Step 169 - A transparent activity log beside the chat (August 18, 2026)

Borrowed from DeepSeek Harness, whose organising rule is that the session log is the source of what
the model saw — "model-visible means logged". Orrery already streams a rich event vocabulary during
a turn (status steps, retrieval sources, generated files, approval requests, token usage, errors),
but the chat thread renders only the parts that belong in a conversation. The rest was invisible, so
a user watching a long turn could not tell whether it was searching documents, waiting on approval,
or stuck.

The Activity panel shows the turn's raw event stream, in order, with a timestamp relative to when
the turn started. Its most important property is that every line corresponds to an event the backend
actually sent: nothing is inferred, nothing is synthesised from the rendered answer. That is what
makes it worth trusting — if it says two sources were retrieved or an approval was requested for
`run_shell`, the stream said so. It is fed at the very top of the event handler, before the early
returns that decide what the thread renders, so the log cannot silently diverge from the wire.

Token-level events are the one exception to one-line-per-event. `delta` and `reasoning_delta` arrive
hundreds of times per turn, so they fold into a single growing "Answer · N characters" or
"Thinking · N characters" entry rather than flooding the log, and a very long turn is capped so it
cannot grow without bound.

The folding logic is a pure function in `ui/src/lib/activityLog.js` rather than component state, so
it is tested directly.

Verified: 13 new UI tests (51 total, up from 38) covering delta coalescing, thinking and answer as
separate running entries, verbatim status steps, source counts and their pluralisation, approval
request and resolution tones, error tone, named generated files, token usage, ignoring events with
nothing to say, non-mutation of the input log, the growth cap, and elapsed labels never going
negative. 759 backend tests pass, `ruff check .` is clean, and the bundle builds.

## Step 170 - The published site says what Orrery actually is (August 18, 2026)

Trimming the README to installation broke the landing page: it linked to
`github.com/zaidt156/Orrery#install-and-run`, and that section is now `## Install`. Fixing that one
anchor meant reading the whole site, which had been describing a different product for a while.

The site led with **Download**. A nav item, a hero button to `/releases/latest`, and three cards
offering "Windows releases" and "macOS previews" - all pointing at installers that were deleted with
the desktop shell months ago. The primary call to action on the front page went to packages that are
not published. That section is now **Install**, and it carries the real thing: the one-line command,
what the first run does for you, and what running it again looks like. Nav, hero, footer, and the
guide's two cross-page links were renamed together so the page is never half-renamed.

The user guide still taught the eight-command setup - virtualenv, `npm install`, `npm run build`,
`docker compose up`, `docker build` - that is now one line, and it described Orrery showing "a
friendly window with a button" when Docker is missing, which was the deleted desktop shell's dialog.
Both are corrected; the guide now says the terminal tells you.

Reading the pages properly also turned up two claims that had gone stale in Orrery's favour, which
is the direction that matters least for honesty but still made the page wrong. The front page listed
"Automation APIs and editor wiring" as planned work, but the Workflow API shipped in Step 166 and
only canvas editing is missing. And it said central approvals, fail-closed authorization, redirect
SSRF, and URL-secret handling "remain P0 work" - all closed in Steps 151-152, and `TODO.md` has had
no P0 tier since.

Planned first in `tasks/plan.md` at the user's request, then implemented in that order.

Verified: every in-page anchor on both pages resolves to a real id, both cross-page anchors resolve,
no `/releases` link survives anywhere, the install command matches `README.md` character for
character, and the landing page parses with no unclosed or mismatched tags after the section splice.

## Step 171 - DeepSeek Harness audited before importing coding authority (August 18, 2026)

DeepSeek Harness rc.7 was pinned to commit
`99f6f02fecdb7dff40c3fbc9470f5907c29f74ca` and audited as a repository, not as a feature list.
All 7,466 tracked paths were inventoried, all 49 package groups were covered, and three independent
passes followed the core/session/LLM runtime, coding tools and isolation, and product/client/
persistence/SDK surfaces through their governing instructions, English contracts, implementation,
tests, generated catalogs, examples, and shipped bundle patches. Translations, snapshots, fixtures,
lockfiles, and the 2,105-file design-history tree were used as corroboration rather than falsely
counted as separate runtime behavior.

The result is a source audit plus proposed ADR-005. Orrery will borrow the useful invariants - exact
durable model/tool evidence, canonical result versus bounded presentation, explicit coding roots,
version-safe file operations, durable jobs, read-only LSP, and bounded child-agent lineage - without
embedding Cordis or a second TypeScript backend. PostgreSQL, the OS keychain, the authenticated
loopback API, the central grant/approval boundary, guarded network access, and offline Docker remain
the authorities.

The proposed sequence has twelve reviewable slices. Exact execution evidence comes first and grants
no new filesystem/process authority; output retention, a user-selected coding root, read/search,
observed-state editing, read-only-by-default Docker commands with overlay-gated writes, compaction/
collaboration state, jobs, LSP, and subagents follow in dependency order. Host Code Mode,
self-modifying extensions, plaintext
credential files, ambient/full host access, raw telemetry, the SSRF-incomplete fetcher, E2B as a
default, and host PTYs were explicitly rejected.

This reconciliation also fixed older architecture/plan claims that Automations was backend-only and
its UI static. Authenticated CRUD/manual runs, the registered node palette, saved-spec rendering,
and durable run steps are live; canvas authoring, durable approval pause/resume, and scheduling are
the honest remaining gaps.

No runtime code was changed because ADR-005 remains Proposed for user review. Verified: the pinned
revision and 7,466-file inventory still match, the audit ledger covers all 49 package groups, every
relative link across the affected canonical/audit/decision documents resolves, and `git diff
--check` is clean.

## Step 171 - Slice 1: tool calls leave evidence before they leave effects (August 19, 2026)

Continues ADR-005's first slice, picking up work already in the tree: `backend/tools/lifecycle.py`,
the `tool_call_contexts` / `tool_lifecycle_events` tables, and the registry contract tests. What was
missing was the wiring - `run_tool()` did not accept an `execution` identity at all, so five tests
described a contract nothing implemented.

`run_tool(..., execution=…)` now records durable evidence around the existing guard sequence.
Callers that pass nothing keep exactly the old behavior, so this adds a capability without changing
any current path. Every guard that used to return a bare `{"ok": False, "error": …}` now returns a
stable structured outcome - `out_of_scope`, `unknown_tool`, `feature_disabled`,
`grant_missing_action`, `grant_missing_resource`, `grant_denied`, `validation_failed`,
`policy_denied`, `approval_required` - each carrying `retry_safe`, and each recorded as the refusal
that opened the call's record.

The ordering is the point. Admission is written only after every guard has passed, then the loop
check, then `body_started`, and only then may the body touch anything. If the admission or dispatch
record cannot be written, the call is refused as retry-safe rather than run unrecorded. If the
*outcome* cannot be written after the body already ran, the caller is told `unknown_outcome` and
explicitly not to retry - the one honest answer when an effect may have happened and cannot be
proven either way.

Two things only a real database could show, both found by running it rather than trusting the mocks:

- The first draft admitted the call at the top of `run_tool`, before the guards. That collides with
  the schema: `reject()` *creates* the call row, so a refusal after an admission violates the
  primary key and the refusal was silently swallowed by its own error handler - a call could be
  refused with no durable record of why. Admission belongs after the guards, because admitting a
  call means it was authorized.
- Evidence cascades with its parent. Deleting the conversation removed the context and its events,
  which is the retention rule ADR-005 asks for rather than an accident.

Verified: 771 backend tests pass, `ruff check .` is clean, and a live run against PostgreSQL shows a
refused call recording exactly `call_rejected` while a successful one records `call_admitted`,
`body_started`, `result`, `terminal_outcome` in sequence.

Next in Slice 1: the canonical provider request envelope, and pointing Chat, Agents, and Automations
at the new `execution` parameter so their calls actually carry lineage.

## Step 172 - The agent surface actually produces evidence now (August 19, 2026)

Step 171 built the evidence machinery but left it inert: nothing in the codebase passed `execution`,
so `run_tool()` still took the old path everywhere and `reconcile_incomplete_calls()` was never
called. This connects the first surface.

Agent runs now carry lineage into every tool call. A turn id is minted per model step - a turn being
one model request plus the tool calls it produces, which is the audit's definition - and the run id
is the parent. The identity is built from primitives rather than the `AgentRun` row, because that
row is detached by the time a tool executes and reading a detached attribute would take a real run
down for the sake of an audit record.

Startup now also closes tool calls a crash left open. That path never re-runs a body: it checks
whether `body_started` was recorded and marks the call either never-dispatched and retry-safe, or
unknown-outcome and explicitly not, which is the distinction the whole slice exists to preserve.

Fourteen test stubs that stand in for `run_tool` needed their signatures widened. That is real
churn, not incidental: those fakes assert the tool boundary's shape, so a signature change has to
pass through them rather than around them.

Verified: 772 backend tests pass, including a new one that runs a real agent to completion and then
reads the database back - the call context exists with `surface='agent'`, the right tool key, a turn
id and an argument digest, and its events are sequenced 1..n with `body_started` recorded before the
terminal outcome. `ruff check .` is clean.

Still open in Slice 1: the canonical provider request envelope and its reconstruction invariant,
which the audit calls the point of the slice, plus the Chat and Automation surfaces, which still
call `run_tool()` without an identity.

## Step 173 - The exact request a model was given is now provable (August 19, 2026)

The audit calls this the point of Slice 1: not that a request was logged somewhere, but that the
record can be *reconstructed* and shown to be the same structure the adapter received. A transcript
that cannot be checked is a claim about the past; this is evidence of it.

Capture happens at the adapter boundary inside `_stream_chat_once`, after privacy redaction and
after route selection, because that is the only place where what exists is exactly what the provider
will be handed. It deliberately does not capture HTTP wire bytes: those carry transport auth headers,
and comparing them would turn a correctness check into a secret-handling problem. Credentials are
resolved below this layer and never appear in the record.

The envelope is provider, model, effort, whether that effort was defaulted, privacy mode, system
prompt, messages, and tool catalogue. `proves()` is the invariant: rebuild from what was stored and
compare canonical-serialization digests, so key order and whitespace cannot make two different
requests look alike or one request look like two. A request too large to keep still stores its
digest, so identity remains provable even where the body does not.

Capture is opt-in per surface through a context variable, which means a surface nobody has wired
records nothing - this cannot quietly start storing request bodies for callers that never asked.
Agent runs opt in around their model step and reset in `finally`, so one turn's identity cannot leak
into the next. Chat and Automations are untouched so far and still record nothing.

Sensitive text a user intentionally sent is part of this record by design: it is owner-private, sits
in the same PostgreSQL trust domain as the conversation, and is deleted with its parent - which is
asserted rather than assumed.

One honest limit worth recording. A test that replaces `stream_chat` never reaches the capture
inside `_stream_chat_once`, so the agent-side test asserts the half the agent actually owns - that
the step declares correct lineage and that the recording does not outlive it - while the storage
half is proven directly against PostgreSQL. Writing one test that pretended to cover both would have
looked stronger and checked less.

Verified: 783 backend tests pass (11 new), both CI configurations are green, `ruff check .` is clean.
The new tests cover digest stability, eight distinct single-field changes that must each break the
proof, corrupt records proving nothing, opt-in silence, scoped reset, a failed write never breaking
the model call, a database round trip that still proves itself, and deletion with the parent.

## Step 174 - All three surfaces produce evidence, and a solo-mode bug that hid inside it (August 19, 2026)

Slice 1's evidence only covered Agents. Chat and Automations still called the registry anonymously,
so the durable record answered "what did this agent do" but not "what did this chat do". Both are
wired now, and Slice 1's surface coverage is complete.

Chat mints one turn id per turn - a turn being one user message and every model round and tool call
it causes - and passes it with the conversation into each tool call, while the request envelope is
recorded per model round. It only records when the caller supplied a conversation, so a tool loop
invoked without one keeps its old behavior rather than inventing a parent. The owner is resolved
inside the loop instead of threaded through the router, because that is where the request actually
runs and where the answer is correct in solo mode.

Automations needed a different mechanism. Workflow nodes execute through a fixed
`execute(inputs, config)` signature and cannot be handed an identity, so widening it would have
touched every node. The engine scopes an ambient identity around each node instead, reset in
`finally`; Chat and Agents pass theirs explicitly and never read it.

Wiring the third surface immediately exposed a real defect in the evidence layer itself, and the
failure mode was the good one: the tool was *refused* rather than run unrecorded. `_parent_owner()`
resolved a workflow's owner with `scalar_one_or_none()`, which returns `None` both for "no such run"
and for "found it, and the owner is NULL". A solo Orrery - the default, single-user configuration -
has NULL owners everywhere, so every automation tool call would have been refused with
`evidence_unavailable`. It reads the row and then its column now, so an absent parent and an
unowned one are different answers. A regression test covers all three surfaces, because the same
trap applied to each.

Verified: 785 backend tests pass in both CI configurations, `ruff check .` is clean. New tests cover
a workflow run leaving `surface='automation'` evidence with the right run id and tool key, and the
NULL-owner distinction including that a genuinely missing parent still reports missing. Three more
`run_tool` stubs in chat and capability tests needed widened signatures.

## Step 175 - Subscription connect survives a usage limit, and Kimi joins the providers (August 19, 2026)

The user reported that connecting a subscription account did not work. It reproduced immediately:
`POST /api/providers/openai/chatgpt-plan/connect` returned 400, "Your Codex/ChatGPT plan limit is
unavailable right now."

The underlying cause was not Orrery's. Connecting runs a real Codex request as a readiness check,
and the CLI answered: "You've hit your usage limit ... or try again at Aug 25th, 2026 10:26 PM." The
account is fine; its credits are spent until the 25th. But Orrery handled that badly twice over.

It threw away the detail the CLI had given it. "Unavailable right now" tells a user nothing about
what to do, so they debug a connection that was never broken. The message now carries the reset time
the CLI reported, and says the account is still connected.

More importantly, it refused to connect at all. A CLI that is installed, signed in, and merely out
of credits until next week is not a failed connection - and blocking it for that long is the wrong
answer, because the route works again the moment the limit clears. Connecting now succeeds on a
usage limit and returns a warning the Settings screen already knows how to display; every other
failure, including a signed-out CLI, still refuses. That distinction is the point: only the limit is
forgiven.

Separately, the model catalogues were reviewed against what each provider actually serves. Claude,
GPT, and Gemini needed no change and this is worth recording, because it is easy to "update" a list
that updates itself: those catalogues are fetched live and curated per tier, and the curators were
checked against current names - they correctly pick opus-5/sonnet-5/haiku/fable-5, the gpt-5.6
sol/terra/luna family beside o3, and gemini-3.7/3.6/3.5 beside the newest pro. Grok, Qwen, and GLM
arrived in Step 162. The genuine gap was Moonshot's Kimi, now a keyed provider with curation that
prefers the thinking variant and drops vision-only entries. DeepSeek's offline fallback, which only
runs when its own list is unreachable, no longer strands a user on the 2024 pair.

The local catalogue went from 38 to 42: DeepSeek R1 32B, Phi-4 Mini Reasoning, Cogito, and
Qwen3-Next 80B. As before, every name and size was verified against the Ollama registry, and four
candidates that do not exist there were dropped rather than guessed at.

Verified: 793 backend tests pass (8 new), `ruff check .` is clean, the bundle builds, and the
ChatGPT-plan route was connected for real against the rate-limited account.

## Step 176 - Two refusals that did not look like refusals (August 24, 2026)

A code audit of every workstream turned up two defects with the same shape, and the shape is worth
naming: a refusal that the surrounding code could not recognise as one.

`run_tool` reports a blocked call by *returning* `{"ok": false, ...}`. It does not raise — that is
deliberate, because a tool failure is data the model has to be able to read. The Automation engine,
though, only caught exceptions. So when a node's tool call was denied, gated, or out of scope, the
refusal came back looking like an ordinary result: the step was written `done`, the run finished
`done`, and the refusal text was handed to the next node as if it were the value it had asked for.
The case that matters is an approval-gated node in a headless run. It reported success.

The engine now reads the registry's contract explicitly. Only a literal `ok: false` counts, so
nodes that never speak that contract — `delay`, `if_branch`, `llm_prompt` — are untouched. A refused
node records a `failed` step and fails its run, and the step keeps the whole output rather than just
the message, so whatever the refusal carried (an approval payload included) is visible in the
run-debug view. There is still no way to *answer* that approval; that remains open, and TODO.md now
says so in those terms rather than claiming the run "fails safely" when it did not fail at all.

The second defect was the `http_request` node calling `netguard.fetch_checked` directly. The fetch
itself was hardened — every redirect hop validated, a hard byte cap — which is exactly why this was
easy to miss: the dangerous-looking part was fine. What was missing was everything the registry adds
around a call. Living outside `run_tool` meant living outside the scope allow-list, the ADR-004
deny-only hook, the approval gate's risk tiering, and the ADR-005 evidence layer. A policy plugin
written to stop Orrery reaching the network could not see it.

It is a registered tool now, and the node calls it like every other node does. The telling detail is
that `nodes.py` already imported `run_tool` and already used it for `doc_search` and `db_query`, so
this was an omission rather than a decision — which is also why the fix is four lines. Risk is
`network`, matching `web_search`: GET and HEAD read the outside world, they do not change it, so it
is inside the gate's sequence without prompting for a decision it does not warrant. Chat's allow-list
is built by naming tools explicitly, so registering this one did not widen what Chat can do.

Verified: 13 new tests, all failing first. The engine's contract is pinned by small database-free
tests so the rule holds independently of PostgreSQL, and a `db`-marked test proves the whole path —
a refused node fails its run and its step. The clearest of the network tests registers a deny-all
policy and asserts the node is stopped with `policy_denied` while a stubbed `netguard` raises if it
is reached at all: that is the property, stated as a test. 129 tests pass across the tools, security,
core, and capability suites, and `ruff check .` is clean.

One honest limit. The full local suite could not be used as the gate: several tests in
`tests/features/test_chat.py` hang on this machine, on a clean checkout as much as with these
changes, so the hang is pre-existing and unrelated. The `db`-marked test was collected but not run
locally, because Docker is not available here. CI runs both.

Next: the same audit found that Chat's `run_python`, `run_shell`, and `web_search` still call the
registry without an execution identity, so Slice 1's "all three surfaces" claim is not yet true for
the three tools Chat actually advertises.

## Step 177 - The three tools Chat actually uses were the three with no record (August 24, 2026)

Step 174 was titled "All three surfaces produce evidence" and said slice 1's surface coverage was
complete. It was not, and the gap was in the least convenient place.

Chat has five paths into the registry. Two of them - the MCP branch and the generic keyed branch,
both reached through the `orrery-tool` JSON block - passed an execution identity. The other three
did not: `run_python`, `run_shell`, and `web_search`, invoked from the ```orrery-run```,
```orrery-shell``` and ```orrery-search``` fences. Those are the ones the chat prompt actually tells
the model to use. So the durable record answered "what did this chat do" only for the path a model
rarely takes, and said nothing about sandboxed code execution or web search.

Nothing failed when this happened, which is the whole problem. `run_tool` takes a `writer=None` path
when no identity arrives and runs the tool perfectly well. An omission at a call site is invisible at
runtime and invisible in review.

So alongside the fix there is now a structural test that walks the backend's syntax tree, finds
every `run_tool(...)` call, and fails if one passes no `execution=`. It has one documented
exemption. This is a slightly unusual test - it reads source rather than behaviour - but it matches
the shape of the defect: the next branch that forgets will be caught whether or not anyone thinks to
write a behavioural test for it.

The turn identity is now minted once next to the turn id and reused by all three branches, built
through the same `_chat_execution` helper the MCP branch uses, so there is no second construction
that can drift. A caller that supplies no conversation still records nothing; that opt-in is
deliberate and has its own test.

The fourth site was the agent's post-approval resume. When a run suspends for a human decision and
then resumes, the tool executes through a different code path from the in-loop one - and that path
called the registry anonymously. The single call a person explicitly authorised was the only one
with no durable record. It carries an identity now. The run's owner is read while the row is still
attached, because the tool runs after that session closes and a detached read is exactly the failure
that would take a run down for the sake of an audit record. Resuming gets a fresh turn id rather
than borrowing the one that asked for approval: it is genuinely a later turn.

ARCHITECTURE.md gained §17a, which is overdue - the evidence layer shipped on 19 August across two
new modules and three tables and the architecture document had never mentioned it. The section
states the four load-bearing properties (evidence never grants authority; it gates the body; a
refusal is a record rather than a silence; the envelope proves itself) and, just as importantly, the
current limits: the lineage columns are declared but nothing writes them, so the ADR's "retries and
forks retain exact lineage" is not met yet, and Automations still capture no request envelope. Both
are now TODO items rather than facts buried in a log entry.

PLAN.md's Workstream 3 no longer calls itself "proposed" - it was accepted on 18 August - and it now
warns that its numbering merges several ADR slices, so the two documents cannot be cross-referenced
by number. TODO.md's "approve ADR-005" decision has been replaced by the decision that is actually
outstanding: the slice 2 retention and replay horizon. All three canonical documents are dated
today; they had been claiming 18 August while five commits from the 19th sat above them.

Verified: 6 new tests, 5 of which failed first (the sixth pins the existing opt-in silence and
passed from the start, which is the point of it). 135 tests pass across the tools, security, core,
and capability suites; `ruff check .` is clean. The same local limitation as Step 176 applies -
several `tests/features/test_chat.py` tests hang on this machine on a clean checkout, so the full
suite is not usable as the gate here and CI remains the real one.

## Step 178 - Turning a feature off now turns it off (August 24, 2026)

Admin has a switch for each product surface. Turning Agents off hid the Agents tab. That was the
entire effect. `GET /api/agents`, `POST /api/agents/{id}/runs`, the workflow routes, the dashboard
routes and the MCP routes all still answered exactly as before.

A hidden tab is not an authorization control. Anything that reaches loopback holding the session -
a script, another local process, a tool, a stale browser tab that never re-rendered - never saw the
navigation bar. The flag was a UI preference wearing the clothes of a security setting, and it had
been that way since the flags were introduced.

`require_feature(name)` is a router dependency now, on the four surfaces whose flag names that
surface exactly: Agents, Automations, Dashboards, MCP. It refuses with 403 and a message naming the
switch, so the answer says which one to flip rather than sending the user hunting.

Three decisions worth recording, because each one is a place this could have gone wrong.

The gate is not applied everywhere a flag exists. `ontology` gates *ontologies as chat context*, not
collection CRUD, and the Data screen shares that router - gating it would have turned off more than
the switch claims. `file_gen` is likewise a capability rather than a surface. Both are left alone and
noted in TODO.md, because over-enforcing a gate is its own kind of dishonesty.

Administration is never gated, and neither is the route that reports the flags. Gating either would
make "turn everything off" a permanent state: the workspace has to be able to read and change its own
configuration in order to recover it. There is a test for each, since this is the sort of thing a
later refactor would happily break.

It fails closed. `admin.feature_enabled` already returned False on an unreadable flag state, and the
dependency re-checks rather than trusting that, so an exception from the lookup cannot read as
allowed. A gate that opens when it cannot decide is not a gate.

The cross-surface callers were checked rather than assumed: the top search bar, the Settings MCP
list, and the Skills MCP list all reach these routes, and all three already catch and fall back to
empty. A 403 there reads as "this feature is off", which is what it means.

Verified: 13 new tests, all failing first. Their speed is itself the evidence - before the gate,
requesting a disabled surface reached the handler and blocked on the database, and the tests hung;
now they refuse before the handler and the file runs in three seconds. 148 tests pass across the
tools, security, core, capability, and automation suites; `ruff check .` is clean.

One mistake worth writing down, because it was mine and it cost a bisect. The new test module copied
`asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())` from the database-backed suites,
where psycopg needs it. That is an import-time global: it changed how every TestClient in the session
ran and hung `tests/security/test_session.py`, a file it has nothing to do with. Tests that never
reach a database need no policy, and the line is gone. Copying a fixture is copying its side effects.

The pre-existing local hangs remain: several orderings involving `tests/features/test_chat.py`,
`tests/test_api.py`, and `tests/test_app_startup.py` stall on a clean checkout too, so CI is still
the real gate here.

## Step 179 - The 51 frontend tests had never run anywhere (August 24, 2026)

Seven files under `ui/src` contain 51 `node:test` tests. They are real tests of real logic - the
activity log's folding, dashboard presentation, office preview, chat threading, reasoning state.
Several DEVLOG entries cite them as verification: "all 38 UI tests pass", later "51 total, up from
38".

There was no way to run them. `ui/package.json` had `dev`, `build`, `preview`, and `relink-deps` -
no `test` script and no runner configured. CI's `ui` job ran `npm ci` and `npm run build` and
nothing else. CONTRIBUTING.md's "test before you push" checklist named three commands, none of
which touched the frontend. So the tests were written, committed, counted in verification notes,
and never executed by anyone except whoever ran node by hand at the time.

`npm test` is `node --test`. The bare form is deliberate: it recursively discovers the test files
from the package root and skips `node_modules` on its own, and it works across Node versions, while
`node --test src/lib/` and `node --test src/lib src/views` both fail outright on Node 24 and the
glob form needs Node 21 or newer. CI runs it before the build, and CONTRIBUTING lists it.

All 51 pass, which is worth stating plainly: this found no bugs. The point is that from now on a
break in them is visible, and the DEVLOG's habit of citing a UI test count means something.

Not done, and now tracked instead of unmentioned: there is still no frontend lint or typecheck.
No eslint config, no `lint` script, no jsconfig or tsconfig, and no TypeScript, across roughly ten
thousand lines of JSX. That needs a new dev dependency and a lockfile change, which is a different
kind of change from wiring up a runner that was already there, so it is a TODO rather than something
smuggled into this one.

Also recorded in TODO.md: the local suite cannot be used as a single gate. Several orderings
involving `tests/features/test_chat.py`, `tests/test_api.py`, and `tests/test_app_startup.py` hang
on a clean checkout. Every file passes alone, so something leaks between them. CONTRIBUTING.md
presents `pytest -q -m "not db"` as the gate and on a developer machine it currently is not one.

## Step 180 - Strict privacy is now stronger than basic, instead of just being called that (August 24, 2026)

Settings offered three privacy modes for the cloud boundary and described strict as "Basic redaction
plus a stronger boundary; broader detection coming. Best when sharing sensitive documents."

There was no stronger boundary. `privacy.py` branched on `mode not in ("basic", "strict")` in both
of its entry points and then ran the same five regexes either way. ARCHITECTURE.md was honest about
it - it said outright that strict was "a hook for a broader detector, not a stronger detector today"
- but the Settings screen is where the choice is made, and there the promise was false. That is the
worst place for this kind of gap, because a person selects strict exactly when the content is
sensitive: the mode's whole audience is people relying on the claim.

PLAN.md allowed either fix, strengthen it or rename it. Strengthening turned out to be cheap,
because the hard part already existed. `secrets.redact_secrets` has been scrubbing key shapes,
bearer tokens, URL passwords, and secret query parameters on the web-search boundary for a while. A
key pasted into a chat is the same risk as a key in a search query, so strict now applies it, plus
an IBAN pattern and a rule for runs of 17 or more digits - the baseline card rule is anchored and
caps at 16, so a longer account or reference number sails past it untouched.

Strict is a superset of basic by construction rather than by promise: `redact_strict` calls `redact`
first and only ever adds to the result. One test asserts that on ordinary PII the two modes produce
identical output, so "stronger" can never quietly become "different".

The extra patterns will sometimes mask something harmless - a long order number, an identifier
shaped like an IBAN. That is stated in the Settings copy now rather than hidden, because it is the
trade the mode exists to make and a user choosing between two options deserves to know which way
each one errs.

Both modes cover the system prompt as well as message bodies. That was already true and is worth
restating, since project instructions and retrieved document context are assembled there.

Verified: 8 privacy tests, 4 of which failed first; the other 4 pin properties that already held
(strict is a superset, local routes stay exempt) so a future change cannot break them silently.
154 backend tests pass across the tools, security, core, capability, and automation suites, all 51
UI tests pass, `ruff check .` is clean, and the production bundle builds.

## Step 181 - Media Hub stops claiming to work (August 24, 2026)

Media Hub is a mockup. There is no feature module, no API route, no table, and no test - the audit
looked for all four and found none. The Generate button had no onClick of any kind, and the gallery
was six divs with CSS gradients in them.

That would be fine as an internal design preview. What was not fine is that it said otherwise, in
two places, in its own body text: the hero read "prompts saved to your database, files in your local
media library", and the footer repeated it as "prompts + settings saved to your database · files in
your local media library". Both are false. And the `media` feature flag defaulted to on, so every
fresh install showed the screen in the navigation with those sentences on it.

The design is worth keeping - it is a real artifact of how the feature should look. So the screen
stays and stops lying instead. There is a preview banner above the hero, the Generate button is
rendered disabled with a title saying generation is not built, the hero now says the screen is a
preview and points at what Chat genuinely can do today, and the footer states the same list as
*planned* and notes the tiles are placeholder art. The flag defaults off, with a comment saying why,
so the surface is opt-in until it exists.

A test pins the default, and a companion test asserts the surfaces that do work still default on -
because "turn the broken one off" is exactly the kind of fix that gets over-applied later.

Chat's own media path is unaffected and is worth naming, since the honest copy now points at it: a
model-authored sanitized SVG, and sandbox-computed PNG/GIF/WAV/MP3/MP4/WebM through matplotlib,
Pillow, and ffmpeg. That is a real capability; it just is not this screen.

Verified: 5 capability tests pass including the two new ones, and the production bundle builds.

## Step 182 - The test suite could always run; nothing was ever able to say so (August 25, 2026)

With PostgreSQL started, the full backend suite passes: 836 tests in 62 seconds. Before today it had
never been run to completion on this machine, and yesterday's entries recorded that as "pre-existing
local hangs" involving a leak between test files. That diagnosis was wrong, and the correction is
worth more than the fix.

There were three separate causes, each masquerading as the same symptom.

**Configured is not reachable.** The `db` marker gate skipped when no database was *configured*. But
`.env` still names one after `docker compose down`, so every marked test believed a database existed
and blocked on connect until the per-test timeout killed the session - the exact failure the gate's
own comment says it exists to prevent. It now asks the only question that matters, with one short
TCP connect cached for the session: does anything answer. 80 marked tests skip in 2.8 seconds
instead of hanging.

**A missing marker.** `tests/features/test_team_failclosed.py` had no `db` marker. Seven of its eight
tests patch `get_sessionmaker` to raise and genuinely need no database - which is why nobody noticed -
but the eighth queries a real migrated, empty team table. Only that one is marked, so the seven P0
fail-closed abuse cases stay in the cross-platform CI job where they belong.

**Bindings, not modules.** The first attempt at a fail-fast fixture patched
`backend.core.database.get_sessionmaker` and changed nothing at all, because almost every module
does `from backend.core.database import get_sessionmaker` and binds the function into its own
namespace at import. Patching the source leaves all those bindings pointing at the real connector.
The fixture now rebinds the name wherever it actually lives. Worth remembering as a general trap:
patching a module is not patching its importers.

That left one test still hanging, and it turned out not to be a test problem at all.
`tests/security/test_session.py::test_header_auth_still_works` calls `GET /api/health`, which calls
`database.check_connection()`, which caught every exception but waited indefinitely for one. So with
PostgreSQL down the endpoint whose entire job is to report a broken database was itself disabled by
a broken database - and the sidebar indicator that polls it spun rather than turning red. A health
probe that cannot finish is not a health probe. It is bounded by `HEALTH_TIMEOUT_SECONDS` now and
reports `database: error`, which is the honest answer and the fast one.

The result is that CONTRIBUTING.md's promise is finally true. `pytest -q -m "not db"` completes on a
machine with no Docker at all: 756 passed, 1 skipped, 62 seconds. It used to stall at 14 per cent.

Verified: 836 pass with a database (`ORRERY_REQUIRE_DB=1`), 756 pass with none, `ruff check .` is
clean. Yesterday's database-marked test for the refused Automation node - written but never executed
- passes against real PostgreSQL, so that fix is now proven end to end rather than by unit test
alone.
