# Orrery

A **local-first desktop AI workspace**. Bring your own model accounts, API keys, and your own
PostgreSQL database; Orrery is the framework that ties them together. Nothing
leaves your machine except calls to the model providers you configure.

Eight tabs, all orbiting the one thing at the centre — your database: **Chat ·
Data · Dashboards · Automations · Agents · Media Hub · Local Models · Settings**.

- **Documentation map:** [`docs/README.md`](docs/README.md)
- **What it is and why:** [`docs/planning/ORRERY_PLAN.md`](docs/planning/ORRERY_PLAN.md)
- **Step-by-step history:** [`docs/history/DEVLOG.md`](docs/history/DEVLOG.md)
- **Architecture / security / roadmap / conventions:**
  [`.claude/skills/orrery-development/`](.claude/skills/orrery-development/)
- **Interface mockup (design reference):** [`docs/design/orrery_mockup.html`](docs/design/orrery_mockup.html)

## Stack

All logic is Python; JavaScript only paints the screen.

| Concern | Tool |
|---|---|
| Desktop window | pywebview |
| Backend / API | FastAPI + uvicorn (localhost only) |
| Model access | litellm for API-key providers + official local CLI account routes |
| Database | PostgreSQL via SQLAlchemy + psycopg |
| Vector search | pgvector |
| Job queue + scheduler | Procrastinate (Postgres-native; no Redis/Celery) |
| Secrets / accounts | keyring (OS keychain), never returned raw to the UI |
| Frontend | React + Vite (plain JS) |

## Developer setup (Windows)

> This project lives under **OneDrive**, which corrupts `node_modules` and Python
> venvs by syncing them mid-write. The scripts below keep those folders **outside**
> OneDrive (in `%LOCALAPPDATA%\orrery`) via directory junctions. **Re-run
> `npm run relink-deps` after every `npm install`.**

Prerequisites: Python 3.12, Node 20+, and Docker Desktop.

```powershell
# 1. Local database (Postgres + pgvector)
copy .env.example .env
docker compose up -d

# 2. Python backend (creates .venv outside OneDrive, then installs)
powershell -ExecutionPolicy Bypass -File scripts\setup\setup-venv.ps1
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Frontend
cd ui
npm install
npm run relink-deps      # move node_modules out of OneDrive (after EVERY install)
npm run build            # or `npm run dev` for hot reload (set ORRERY_DEV=1)
cd ..

# 4. Run Orrery
python app.py
```

`python app.py` connects to the database, runs migrations (enabling `pgvector`),
starts the FastAPI server plus the background worker, and opens the desktop
window. On first run it offers to save your connection string in the OS keychain.

## Accounts & Keys

Open **Settings -> Accounts** to choose how Orrery reaches models:

- Add API keys for OpenAI, Anthropic, Google, Mistral, and DeepSeek. They are stored in your OS keychain and the UI only sees masked previews.
- Use Ollama locally with no key.
- Connect a Claude plan through an installed, signed-in Claude Code CLI.
- Connect a Codex/ChatGPT plan through an installed, signed-in OpenAI Codex CLI. Orrery launches the official CLI in a temporary read-only, ephemeral run and never copies its login token.
- Use the Gemini CLI row only for currently supported enterprise/API-key accounts. Google moved consumer free, Google AI Pro, and Google AI Ultra users to Antigravity CLI on June 18, 2026.
- Add Qwen, Kimi, GLM, OpenRouter, Together, Groq, or another OpenAI-compatible service through **Add a custom model**.

Claude plan setup:

1. Open **Settings -> Accounts**.
2. If Claude Code is missing or outdated, approve **Install CLI** / **Update CLI**. Orrery installs only the fixed official WinGet package `Anthropic.ClaudeCode`.
3. If it is not signed in, click **Sign in** and finish `claude auth login` in the opened console.
4. Refresh status, then click **Connect**. Orrery verifies a safe no-tools/no-session request first.
5. In Chat, choose an **adaptive thinking** Claude plan route or the fast Haiku route. The per-chat effort selector is passed to Claude Code when the installed CLI supports it.

Codex / ChatGPT plan setup:

1. Open **Settings -> Accounts**.
2. If Codex is missing or outdated, approve **Install CLI** / **Update CLI**. Orrery installs only the fixed official WinGet package `OpenAI.Codex`.
3. If Codex is not signed in, click **Sign in** and finish the official ChatGPT login in the opened console.
4. Refresh status, acknowledge the local CLI notice, then click **Connect**.
5. Orrery runs a small read-only readiness check before saving the local connected marker.
6. In Chat, choose the best-available reasoning route, **GPT-5.5 reasoning**, or the fast **GPT-5.4 mini reasoning** route.

Orrery prefers the official WinGet Codex installation over stale npm or editor-extension shims. Older compatible CLIs use GPT-5.4 mini for the default route; GPT-5.5 requires a current Codex release.

Google CLI setup:

1. Consumer free, Google AI Pro, and Google AI Ultra users must use Antigravity after June 18, 2026. Orrery does not yet connect Antigravity because Google has not published a stable restricted headless interface for this integration.
2. Eligible enterprise/API-key Gemini CLI users can install and sign in to the official Gemini CLI.
3. Open **Settings -> Accounts**, acknowledge the notice, and connect the Google CLI route.

Orrery does not store vendor OAuth/session tokens, browser cookies, or web-session data. Each local flag only remembers that you approved the official CLI route on this machine.

## Settings

Settings is organized into responsive categories: **General**, **Accounts**, **Models**, **Usage**, **Integrations**, and **Feedback**. On smaller screens the category bar scrolls horizontally and account actions stack so every control remains reachable.

Use **Settings -> General** to enable an optional company header. You can upload a PNG, JPEG, WebP, or GIF logo up to 1 MB, then add a company name, tagline, and short details. Branding remains hidden until **Show branding header** is enabled and **Save branding** is clicked. Uploaded logos are stored as local application settings; remote image URLs and SVG uploads are rejected.

If a connected Claude plan reaches its provider session limit, Orrery shows Claude Code's reset message when one is supplied. Wait for that reset or switch to an API-key, Codex, or local model; reconnecting Claude does not bypass provider plan limits.

## Chat controls

Chat replies render as GitHub-flavored Markdown with headings, lists, tables, links, inline code, and fenced code blocks. Orrery also repairs common unfenced code output in the UI so commands, JSON, SQL, logs, config, and common programming languages still appear as copyable code blocks when a model forgets the fences.

- Press **Enter** to send, or **Shift+Enter** for a new line.
- Use the icon controls and their hover tooltips to copy, edit, resubmit, rewrite, or regenerate messages.
- When you ask for a file, Chat shows only the requested file type — **PDF**, **Word**, **Excel**, **PowerPoint**, **CSV**, **Markdown**, **text**, **HTML**, **JSON**, **charts/images**, and more — then a short summary with **Preview** and **Download**. The model writes Python that builds the file with open-source libraries (python-docx, openpyxl, python-pptx, reportlab, matplotlib, pandas, Pillow, …); that code runs in an **isolated, network-less Docker sandbox** (non-root, read-only root filesystem, CPU/memory/PID/time caps, all Linux capabilities dropped) and only the resulting files come back. If the sandbox is unavailable, Orrery falls back to building common documents from a structured spec with no code execution. Spreadsheet/CSV cells neutralize formula-like values. See [`docs/FILE_GENERATION_ARCHITECTURE.md`](docs/FILE_GENERATION_ARCHITECTURE.md).
- Use the per-chat **context** selector to choose **128K**, **256K**, or **1M** approximate tokens. New and upgraded chats default to **1M**. Orrery keeps the newest complete turns and reserves 25% for the reply; saved messages are never deleted. The selected model may enforce a smaller native limit.
- Ask to create an image, illustration, diagram, poster, icon, logo, visual, or infographic, or start with `/image`. Chat asks the selected text model for SVG code, validates it against a strict vector-only allowlist, and displays the safe result with an SVG download. If a model keeps returning invalid SVG, Orrery falls back to a safe built-in SVG preview. The only place Orrery ever runs model-written code is the **file-generation sandbox** described above (isolated, no network, least-privilege); it never executes model-written code in the app process, and the SVG path stays declarative vector markup only.

## Local Models

Open **Local Models** to set up private on-device chat:

1. Approve **Install Ollama**. Orrery installs only the fixed official WinGet package `Ollama.Ollama`.
2. Start the local Ollama service if it is not already running.
3. Download one of the reviewed one-click models. Progress streams in the tab.
4. The downloaded model is added to Chat automatically. Use **Chat** to open Chat with that model selected.
5. Installed models can be shown/hidden in Chat or removed from disk.

Orrery currently offers Qwen 3 4B, Gemma 3 4B, DeepSeek R1 8B, and Llama 3.2 3B as one-click starting points. Model downloads come from Ollama's local service and can be several gigabytes.

## Security

Orrery handles dangerous things at once — your model accounts/API keys, direct
database access, autonomous agents, and running model-written code for file generation.
The security standard is non-negotiable and wins over convenience: see
[`security.md`](.claude/skills/orrery-development/references/security.md). Secrets live
only in the OS keychain (never in files, logs, or the repo); model-written code runs only
in the isolated sandbox; and the local API is bound to localhost behind a per-session token.

## License

Licensed under the **Apache License 2.0** — see [`LICENSE`](LICENSE). Copyright 2026 Muhammad Zaid.
