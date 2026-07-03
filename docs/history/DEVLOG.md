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
