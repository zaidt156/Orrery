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
2. Node.js 20 or newer — Orrery builds its workspace bundle itself, once, on first run.
3. Docker Desktop — Orrery starts it and provisions PostgreSQL itself, on first run.
4. Optional: Ollama for local models, plus provider API keys or official provider CLIs.

### Install and run

```bash
git clone https://github.com/zaidt156/Orrery.git && cd Orrery && pip install -e . && orrery
```

That is the whole thing. The first run does the setup that used to be a list of commands:

- builds the workspace bundle with npm (about a minute, once — later starts skip it)
- starts Docker Desktop if it is installed but not running, brings up PostgreSQL with pgvector,
  and saves the connection string to your OS keychain
- opens your browser on the workspace

No `.env` is required: it is for overriding local development settings, and the connection string
lives in the keychain rather than on disk. Use a virtual environment if you prefer
(`python -m venv .venv` and activate it before `pip install -e .`).

Two optional extras, neither needed to start:

```bash
docker build -t orrery-sandbox:latest sandbox   # sandboxed code execution and file generation
cp .env.example .env                            # only to override local dev settings
```

### Start it again later

```bash
orrery
```

Orrery binds to `127.0.0.1`, prints the URL, and opens your browser at it. `orrery --no-browser`
starts the backend without opening one, which is what you want over SSH or in a second terminal;
paste the printed URL yourself. `orrery --no-build` refuses to build the bundle instead of building
it, for a machine without Node. `orrery --dump-config` prints every setting, its value, and which
layer supplied it, then exits without starting anything.

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

- API keys are supported for OpenAI, Anthropic (Claude), Google, Mistral, DeepSeek, xAI (Grok),
  Alibaba DashScope (which serves both Qwen and GLM), and OpenRouter. Anything else that speaks an
  OpenAI-compatible API can be added as a custom model with its own base URL.
- Each provider's model list is fetched from the provider itself and curated to the newest few per
  tier, so new releases appear without an Orrery update.
- Ollama models run locally and do not require an API key. Settings ships a catalogue of ~38
  open-weight models across four size tiers, and any other name from the Ollama library can be
  pulled directly.
- Claude, ChatGPT/Codex, and Gemini CLI routes are optional account-plan routes where the official
  first-party CLI supports non-interactive local execution. Orrery does not use unofficial browser
  cookies, hidden web APIs, or session scraping.
- API keys and database URLs are stored in the operating-system keychain. They are not written to
  `.env`, PostgreSQL, logs, or the repository.

Provider subscriptions and provider API billing are not always the same product. If a provider does
not officially allow subscription spend through a third-party app, Orrery keeps that route disabled
or uses only the supported first-party CLI path with warnings.

## Configuration And Plugins

Settings resolve through five layers. Later layers win:

1. built-in defaults
2. `orrery.toml` beside the project (or the path in `ORRERY_PROFILE`) — a profile you can commit
3. `config.toml` in your per-user data directory — survives reinstalling the app
4. `.env`
5. real environment variables

```toml
# orrery.toml
[orrery]
rag_top_k = 8
sandbox_timeout_seconds = 90
```

`orrery --dump-config` shows the resolved value of every setting and the layer it came from, with
anything credential-shaped redacted so the output is safe to paste into an issue. Secrets are never
read from these files: provider keys and the database URL live in the OS keychain.

A configuration layer can also mount local plugins:

```toml
[orrery]
plugins = ["mycompany.orrery_policy"]
```

A plugin is an importable Python module you have installed yourself — nothing is downloaded. It
must define `setup(ctx)`, and the context it receives can register two kinds of policy hook: one
that runs before any tool executes, and one that runs before each step of an agent run. **Hooks can
only refuse.** They run after every built-in check, so a hook can stop an action but can never
approve one that Orrery's own scope, grant, or approval rules already refused. A plugin that fails
to import stops startup rather than leaving you running without the policy you asked for.

```python
def setup(ctx):
    async def no_shell_after_hours(call):
        if call.risk == "destructive":
            return "Destructive tools are disabled by company policy."
        return None                       # None means "no objection", not "approved"

    ctx.register_pre_execute("after-hours", no_shell_after_hours)
```

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
python -m pytest tests/ -q            # needs the local PostgreSQL running
python -m pytest tests/ -q -m "not db"  # ...or skip the tests that need it
ruff check .

cd ui && npm run build
```

Tests marked `db` write to real tables. Without a database they skip with a reason rather than
stalling on a connection timeout; CI runs the whole suite against a pgvector service on Linux and
the `not db` subset on macOS and Windows.

## Contributing

Contributions, feedback, and ideas are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), and [`SECURITY.md`](SECURITY.md) before opening issues
or pull requests.

## License

Orrery is licensed under the [Apache License 2.0](LICENSE).
