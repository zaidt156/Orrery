<div align="center">

<img src="assets/orrery-logo.svg" alt="Orrery" width="440">

### A local-first AI workspace — runs on your machine, opens in your browser

Orrery ties your own AI accounts and your own PostgreSQL database together into one local workspace:
chat with connected models, retrieve your documents, build dashboards from your data, run bounded
agents, and generate real files. Automations and Media remain visible work in progress; the exact
implemented surface is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md).

![Version](https://img.shields.io/badge/version-0.2.1-E5A93F)
![License](https://img.shields.io/badge/License-Apache_2.0-F2B14E)
![Windows](https://img.shields.io/badge/Windows-supported-9DB9F0?logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12+-9DB9F0?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-Vite-9DB9F0?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-localhost-0B1020?logo=fastapi&logoColor=009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-0B1020?logo=postgresql&logoColor=4169E1)
![PRs welcome](https://img.shields.io/badge/PRs-welcome-5BC489)

</div>

## Status

Orrery is open source and under active development; the current line is **v0.2.1**. It runs
locally and serves its workspace to your browser, so there is no shell to install and no
platform-specific window: Windows, macOS, and Linux all run the same way from a checkout. Windows
remains the most-tested target.

The whole design rests on two things you bring: **your own model accounts or API keys**, and **your
own PostgreSQL database**. Orrery is the framework between them. When you pick a cloud model, only the
prompt and context that request needs is sent to that provider. Orrery has no hosted account,
telemetry, or phone-home service. Credentials stay in the OS keychain — including secrets embedded
in dataset import URLs, which are stripped into the keychain and shown only in redacted form.

## What Orrery Does

Orrery is organized as a set of workspace tabs. Each keeps the same local, private-by-default rules.

- **Chat** — talk to any connected model with streaming responses, a model picker, effort modes, and
  context-window controls. With the relevant feature gates and consent, Chat can search the web or
  documents, query connected data, generate files, run sandboxed code, call approved MCP tools, and
  refresh an existing dashboard. Starting Agents or Automations and creating dashboards from Chat are
  still planned. Point it at your document collections to answer from your own material.
- **Data** — connect local or remote PostgreSQL databases, browse tables read-only, and build
  document collections for retrieval (RAG) using pgvector plus PostgreSQL full-text search. Untrusted
  document text is kept separate from system instructions.
- **Ontology** — reusable knowledge structures that give the model stronger, relevance-gated context
  control across conversations.
- **Dashboards** — describe the dashboard you want and pick a model; the model writes the SQL and
  chooses the charts, and Orrery saves it as a spec. Refreshes re-run the saved queries against your
  live data with no additional model cost. The AI is the designer, not the renderer.
- **Automations** — the backend has fixed-recipe workflow storage, execution nodes, and durable run
  records. The product API, schedule tick, and live editor/debug UI are not connected end to end yet.
- **Agents** — goal-driven workers run manually or on a schedule through a durable, scoped engine.
  Tool use passes through grant enforcement; runs support approval pauses, cancellation, budget
  limits, scheduled ticks, and crash-safe resume from an immutable step trace. API, Slack, and Gmail
  receivers plus learning/LIFE consumption remain unfinished.
- **Media Hub** — currently a static product screen. Chat can create media artifacts, but the provider
  adapters and saved local media-library path are still planned.
- **Projects** — durable project context: a chat hierarchy plus reusable instructions and files that
  related conversations share.
- **Skills** — reusable instruction playbooks that guide chat, file generation, research, coding,
  images, spreadsheets, presentations, and sandboxed work.
- **Local Models** — install Ollama and pull models with one-click helpers where available, and keep
  prompts and responses entirely on your machine.
- **Settings & Admin** — Accounts & Keys (stored in the OS keychain), model providers, MCP servers,
  defaults, and small-team feature toggles with an approval flow for team-created skills and tools.

### File generation

Orrery builds real files, not just text about them. It generates PDFs, Word documents, spreadsheets,
PowerPoint decks, CSV files, charts, HTML/web pages, small self-contained web apps, audio, video,
SVG/image outputs, and archives. Generated documents are the user's own deliverables — they carry no
Orrery branding inside the file. Office files can be previewed faithfully (via LibreOffice or the
bundled PDF renderer), and heavier or code-driven artifacts are produced in the locked-down sandbox
and validated before they are attached.

### Reasoning and memory

- **Reasoning trace** — a live activity panel shows what Orrery is doing (planning, searching,
  running code, building a file). Where a model connection exposes raw thinking tokens, they stream
  into their own collapsible block; where a connection does not (some first-party CLI plans), the
  panel says so honestly and shows Orrery's structured trace instead.
- **Life Memory** — an optional durable memory the app can learn over time, kept in a file in your
  user-data directory. Any AI-proposed change is a diff you approve before it is written; edits are
  atomic and reversible.

## Architecture

The repository has four canonical project documents:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — what the executable system does today.
- [`PLAN.md`](PLAN.md) — product direction, sequencing, and architectural decisions.
- [`TODO.md`](TODO.md) — unfinished, actionable work only.
- [`docs/history/DEVLOG.md`](docs/history/DEVLOG.md) — append-only history of completed work.

| Layer | Technology |
|---|---|
| Delivery | Local FastAPI server; the workspace opens in your own browser |
| Backend API | Python 3.12, FastAPI, Uvicorn |
| Frontend | React + Vite |
| Database | PostgreSQL + pgvector |
| Queue / jobs | Procrastinate, backed by PostgreSQL |
| Model routing | LiteLLM, official provider CLIs where supported, Ollama for local models |
| Secrets | Operating-system keychain through `keyring` |
| File sandbox | Docker container with no network, resource limits, read-only root, and mounted output folder |

Orrery is a modular monolith with sidecars, not microservices. The backend modules run as one local
application, while risky or heavy capabilities such as sandboxed file generation, local model runtimes,
and provider CLIs stay isolated as local sidecar processes. The worker already stores durable Workflow
run records and runs scheduled Agents with restart-safe state; the Automation product API, schedule
tick, and live UI are still unfinished.

## Install And Run

Orrery runs on your own machine and opens in your own browser. There is no installer and no bundled
window: `orrery web` starts the local backend, then hands the workspace to whichever browser you
already use.

### Prerequisites

1. Python 3.12 or newer.
2. Node.js 20 or newer, to build the workspace bundle once.
3. Docker Desktop, for the included PostgreSQL database and the file-generation sandbox.
4. Optional: Ollama for local models, plus provider API keys or official provider CLIs.

### Setup

```bash
git clone https://github.com/zaidt156/Orrery.git
cd Orrery

# Local settings. Never commit .env.
cp .env.example .env                 # Windows: copy .env.example .env

# Python environment and the `orrery` command.
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .

# The workspace bundle that FastAPI serves.
cd ui && npm install && npm run build && cd ..

# Local PostgreSQL + pgvector, and the sandbox image.
docker compose up -d
docker build -t orrery-sandbox:latest sandbox
```

### Start

```bash
orrery web
```

Orrery binds to `127.0.0.1`, prints the URL, and opens your browser at it. `orrery web --no-browser`
starts the backend without opening one, which is what you want over SSH or in a second terminal;
paste the printed URL yourself.

That URL carries a single-use launch code. The page trades it for an httpOnly session cookie and
strips it from the address bar, so the credential never settles into history or a bookmark. Requests
afterwards are authenticated by that cookie and checked against the origin the browser actually used
— which is what stops another process on your machine from driving the API.

## Development Mode

Vite hot reload against the same Python backend:

```bash
# In .env:
# ORRERY_DEV=1

# Terminal 1
cd ui && npm run dev

# Terminal 2
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
orrery web
```

For production-style local testing set `ORRERY_DEV=0`, run `npm run build`, and start `orrery web`
again. `python app.py` remains equivalent to `orrery web`.

## Model Setup

Open `Settings -> Accounts & Keys` inside Orrery.

- OpenAI, Anthropic, Google, and compatible providers can use API keys where supported.
- Ollama models run locally and do not require an API key.
- Claude, ChatGPT/Codex, and Gemini CLI routes are optional account-plan routes where the official
  first-party CLI supports non-interactive local execution. Orrery does not use unofficial browser
  cookies, hidden web APIs, or session scraping.
- API keys and database URLs are stored in the operating-system keychain. They are not written to
  `.env`, PostgreSQL, logs, or the repository.

Provider subscriptions and provider API billing are not always the same product. If a provider does
not officially allow subscription spend through a third-party app, Orrery keeps that route disabled
or uses only the supported first-party CLI path with warnings.

## Data And RAG

Orrery uses PostgreSQL as the main data layer. You can:

- Use the included local Docker database.
- Connect your own PostgreSQL server.
- Browse connected data safely.
- Upload documents into collections.
- Use pgvector and PostgreSQL full-text search for hybrid retrieval.
- Use retrieved context in chat while keeping untrusted document text separated from system
  instructions.
- Build dashboards directly from connected data sources; end-to-end Automations remain planned.

## File Generation And Sandbox

Rich file generation and scanned-PDF OCR use a locked-down Docker sandbox. Build the image once:

```powershell
docker build -t orrery-sandbox:latest sandbox
```

The sandbox has no network, a read-only root filesystem, separate read-only input/code mounts,
dropped Linux capabilities, and memory/CPU/PID/open-file/time limits. Only its scratch and output
folders are writable. Model-written code and PDF OCR never run inside the Orrery process. Rebuild
this image after pulling updates that change `sandbox/Dockerfile`; Orrery rejects stale image
versions instead of silently running without current protections or OCR support.

If the sandbox image is missing, normal chat and searchable-text PDFs still work, but scanned-PDF OCR
and code-execution-based file generation are limited until the image is built.

## Security

Orrery is designed around clear local boundaries:

- Secrets stay in the OS keychain.
- The API binds to localhost. The browser is authenticated by a single-use launch code traded
  for an httpOnly session cookie, with an origin check on every cookie-authenticated request.
- Cloud models receive only the request context you choose to send through that model route.
- Local Ollama models keep inference on your machine.
- User files, RAG chunks, and model outputs are treated as untrusted input.
- Generated code runs only in Docker sandbox mode.
- Database URLs and provider errors are redacted before display/logging.

Read [`SECURITY.md`](SECURITY.md) for vulnerability reporting.

## Portable Packages

A portable package bundles a frozen Python runtime so a machine without Python installed can still
run Orrery. Both build scripts validate their own output:

```powershell
.\scripts\build-windows-onedir.ps1   # -> release\Orrery-Windows.zip
```

```bash
./scripts/build-macos-app.sh         # -> release/Orrery-macOS.zip
```

Each bundles the built UI, skills, sandbox Dockerfile, compose file, and launcher scripts, and each
asserts the QtPdf preview renderer is present. Neither ships a browser engine any more — the
workspace opens in yours.

Nothing builds these automatically today. The three native release workflows were removed with the
desktop shell; CI runs the tests and the UI build on Linux, macOS, and Windows instead.

## Test And Verify

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
ruff check .

cd ui && npm run build
```

## Contributing

Contributions, feedback, and ideas are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), and [`SECURITY.md`](SECURITY.md) before opening issues
or pull requests.

## License

Orrery is licensed under the [Apache License 2.0](LICENSE).
