<div align="center">

<img src="assets/orrery-logo.svg" alt="Orrery" width="440">

### A local desktop AI workspace for models, files, data, projects, and automation

Orrery lets you connect your own AI providers, local models, PostgreSQL data, project context,
documents, skills, and workflow tools in one Windows desktop app.

![License](https://img.shields.io/badge/License-Apache_2.0-F2B14E)
![Windows](https://img.shields.io/badge/Windows-supported-9DB9F0?logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12+-9DB9F0?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-Vite-9DB9F0?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-localhost-0B1020?logo=fastapi&logoColor=009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-0B1020?logo=postgresql&logoColor=4169E1)
![PRs welcome](https://img.shields.io/badge/PRs-welcome-5BC489)

</div>

## Status

Orrery is open source and under active development. Windows is the supported target right now.
macOS and Linux are planned, but the current release packaging, installer notes, and testing path are
Windows-focused. An Electron shell is now being added as the production desktop direction while the
existing PyInstaller shell remains available during migration.

The app is built for people who want AI help across documents, databases, local models, dashboards,
automations, projects, and structured workflows while keeping control of their data. When you choose
a cloud model, only the selected prompt/context needed for that request is sent to that provider.
Your app state, files, database connection details, generated files, and credentials stay in your
environment.

## What Orrery Supports

- Chat with multiple model routes: API-key providers, official CLI/account routes, custom
  OpenAI-compatible endpoints, and local Ollama models.
- Accounts & Keys: add provider API keys, connect supported first-party CLI plans, and manage active
  models without exposing secrets in the UI.
- Local models through Ollama, including one-click install/pull helpers where available.
- File upload, search, and retrieval-augmented generation (RAG) with PostgreSQL and pgvector.
- A data layer for local or active PostgreSQL connections, so dashboards and automations can be built
  from connected data sources.
- Projects with chat hierarchy and reusable context.
- Ontologies and reusable knowledge structures for stronger context control.
- Effort modes and context-window controls, including high-limit options for deeper work.
- Sandboxed file generation for PDFs, Word documents, spreadsheets, PowerPoint decks, CSV files,
  charts, HTML/web pages, audio, video/MP4/WebM, SVG/image-style outputs, archives, and other
  requested artifacts.
- Skills: reusable instruction playbooks that guide chat, file generation, research, coding, images,
  projects, spreadsheets, presentations, and sandboxed work.
- Admin controls for small teams, including feature toggles and approval flow for team-created
  skills/tools.
- Reasoning trace summaries that show what Orrery is doing without exposing raw private chain of
  thought.

## Architecture

| Layer | Technology |
|---|---|
| Desktop shell | Electron migration shell; PyInstaller/Qt WebEngine release path remains during transition |
| Backend API | Python 3.12, FastAPI, Uvicorn |
| Frontend | React + Vite |
| Database | PostgreSQL + pgvector |
| Queue / jobs | Procrastinate, backed by PostgreSQL |
| Model routing | LiteLLM, official provider CLIs where supported, Ollama for local models |
| Secrets | Operating-system keychain through `keyring` |
| File sandbox | Docker container with no network, resource limits, read-only root, and mounted output folder |

Orrery is a modular monolith with sidecars, not microservices. The backend modules run as one local
application, while risky or heavy capabilities such as sandboxed file generation, local model runtimes,
and provider CLIs stay isolated as local sidecar processes.

## Download A Desktop Build

When a release is published, download the desktop package from the
[GitHub Releases page](https://github.com/zaidt156/Orrery/releases):

- `Orrery-Windows.zip`: recommended package with `Orrery.exe`, database compose file, sandbox
  Dockerfile, `setup-orrery.bat`, `run-orrery.bat`, Windows notes, and the required PyInstaller
  `_internal` runtime folder.
- `Orrery-macOS.zip`: macOS preview package with `Orrery.app`, database compose file, sandbox
  Dockerfile, `setup-orrery.command`, `run-orrery.command`, and macOS notes.

The first public builds are preview builds. If a release asset is not attached yet, run Orrery from
source using the steps below or ask a maintainer to publish a tagged release.

### Windows Release Prerequisites

Install these before running the released `.exe`:

1. Windows 10/11.
2. Docker Desktop, if you want the included PostgreSQL container or sandboxed file generation.
3. PostgreSQL with pgvector. The release zip includes `docker-compose.yml` for a local pgvector
   database.
4. Optional: Ollama for local models.
5. Optional: first-party provider CLIs for account-plan routes, such as Claude Code, Codex CLI, or
   Gemini CLI. These routes are advanced and opt-in. Orrery launches the official CLI and does not
   scrape browser sessions or copy provider tokens.

The Windows desktop web runtime is bundled with the package through Qt WebEngine; you should not need
to install Microsoft Edge WebView2 separately for the Orrery window.

### Run The Windows Release

From the extracted `Orrery-Windows.zip` folder:

On first launch, `setup-orrery.bat` runs a **prerequisite check**: it reports whether Docker Desktop
is installed and running (and Ollama, if you want local models), and offers to open the Docker
download page if it is missing — so you can install what you need before continuing. Docker is
required only for the bundled PostgreSQL database and the file-generation sandbox; if you bring your
own PostgreSQL (menu option 2) you can proceed without it.

```powershell
# First-run setup menu: choose included Docker PostgreSQL, your own database,
# sandbox-only setup, or start-only.
.\setup-orrery.bat

# Normal launch after setup.
.\run-orrery.bat
```

Do not copy `Orrery.exe` out by itself. The Windows build is a PyInstaller `onedir` app and requires
the `_internal` folder beside the executable. If you run the executable directly from PowerShell, use
`.\Orrery.exe`; PowerShell does not run current-folder programs by name only.

On first launch, `setup-orrery.bat` can write the database URL into the extracted package's `.env`
file. For the included Docker database, it uses:

```text
postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery
```

You can also point Orrery at your own local, LAN, or cloud PostgreSQL server as long as pgvector is
available and the connection string is reachable from your machine.

### macOS Release Prerequisites

Install these before running the macOS preview package:

1. macOS 13 or newer is the intended baseline for preview builds.
2. Docker Desktop, if you want the included PostgreSQL container or sandboxed file generation.
3. PostgreSQL with pgvector. The release zip includes `docker-compose.yml` for a local pgvector
   database.
4. Optional: Ollama for local models.
5. Optional: first-party provider CLIs for account-plan routes.

### Run The macOS Release

From the extracted `Orrery-macOS.zip` folder:

Like the Windows package, `setup-orrery.command` runs a **prerequisite check** on first launch —
reporting Docker Desktop (and optional Ollama) status and offering to open the Docker download page
if it is missing — before showing the setup menu.

```bash
# First-run setup menu: choose included Docker PostgreSQL, your own database,
# sandbox-only setup, or start-only.
./setup-orrery.command

# Normal launch after setup.
./run-orrery.command
```

**Pick the build for your Mac.** The DMG is published per-architecture:
`Orrery-<version>-mac-arm64.dmg` for Apple Silicon (M1/M2/M3/M4) and `Orrery-<version>-mac-x64.dmg`
for Intel Macs. Installing the wrong one is the most common "it won't launch" cause — an Apple
Silicon build will not run on an Intel Mac and vice versa. To check your Mac:  → About This Mac.

**"Orrery is damaged and can't be opened."** The preview isn't code-signed/notarized yet, so macOS
quarantines it after download. This does not mean the app is actually damaged. Fix it by removing the
quarantine flag (only for a release you trust):

```bash
# after dragging Orrery to /Applications from the DMG:
xattr -dr com.apple.quarantine /Applications/Orrery.app
```

For the portable `.zip` (non-DMG) package, right-click `Orrery.app` and choose Open, or clear
quarantine on the extracted folder:

```bash
xattr -dr com.apple.quarantine Orrery.app setup-orrery.command run-orrery.command
```

A signed, notarized build (which removes these steps entirely) is planned; it requires a paid Apple
Developer ID certificate.

## Run From Source On Windows

### Prerequisites

Install:

1. Git.
2. Python 3.12 or newer.
3. Node.js 20 or newer.
4. Docker Desktop.
5. PostgreSQL + pgvector, or use the included Docker Compose database.
6. Optional: Ollama for local models.
7. Optional: provider API keys or official provider CLIs for the models you want to use.

### Setup

```powershell
git clone https://github.com/zaidt156/Orrery.git
cd Orrery

# Local development settings. Never commit .env.
copy .env.example .env

# Start local PostgreSQL + pgvector.
docker compose up -d

# Build the sandbox image used by file generation.
docker build -t orrery-sandbox:latest sandbox

# Python environment.
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# Frontend production build served by FastAPI.
cd ui
npm install
npm run build
cd ..

# Launch Orrery.
python app.py
```

The app opens a desktop window. The backend API is bound to localhost and protected by a fresh
per-session token.

### Development Mode

Use Vite hot reload while keeping the Python backend and desktop shell:

```powershell
# In .env:
# ORRERY_DEV=1

# Terminal 1
cd ui
npm run dev

# Terminal 2
.\.venv\Scripts\Activate.ps1
python app.py
```

For production-style local testing, set `ORRERY_DEV=0`, run `npm run build`, and start `python app.py`.

### Electron Shell Preview

The Electron shell keeps the same React UI and starts the Python backend in `--backend-only` mode:

```powershell
cd ui
npm run build
cd ..\desktop\electron
npm install
npm run dev
```

This is the production desktop direction. The current PyInstaller/Qt release path remains available
until Electron Builder packaging, signing, and update publishing are complete.

## Run From Source On macOS

Install Git, Python 3.12, Node.js 20, Docker Desktop, and PostgreSQL with pgvector, or use the
included Docker Compose database.

```bash
git clone https://github.com/zaidt156/Orrery.git
cd Orrery

# Local development settings. Never commit .env.
cp .env.example .env

# Start local PostgreSQL + pgvector.
docker compose up -d

# Build the sandbox image used by file generation.
docker build -t orrery-sandbox:latest sandbox

# Python environment.
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# Frontend production build served by FastAPI.
cd ui
npm install
npm run build
cd ..

# Launch Orrery.
python app.py
```

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
- Build dashboards and automations from connected data sources as those features mature.

## File Generation And Sandbox

Rich file generation uses a locked-down Docker sandbox. Build the image once:

```powershell
docker build -t orrery-sandbox:latest sandbox
```

The sandbox has no network, a read-only root filesystem, dropped Linux capabilities, memory/CPU/PID
limits, and a per-run output folder. Model-written code never runs inside the Orrery process. Rebuild
this image after pulling updates that change `sandbox/Dockerfile`, especially for audio/video support.

If the sandbox image is missing, normal chat still works, but code-execution-based file generation is
limited until the image is built.

## Security

Orrery is designed around clear local boundaries:

- Secrets stay in the OS keychain.
- The API binds to localhost and requires a per-session token.
- Cloud models receive only the request context you choose to send through that model route.
- Local Ollama models keep inference on your machine.
- User files, RAG chunks, and model outputs are treated as untrusted input.
- Generated code runs only in Docker sandbox mode.
- Database URLs and provider errors are redacted before display/logging.

Read [`SECURITY.md`](SECURITY.md) for vulnerability reporting.

## Build Desktop Releases

Maintainers can build release assets with GitHub Actions.

1. Push the changes to GitHub.
2. Create and push a version tag:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

3. The release workflows build and publish platform zips:
   - `Build Windows Release` -> `Orrery-Windows.zip`
   - `Build macOS Release` -> `Orrery-macOS.zip`

4. On version tags, the workflows attach the zips to the GitHub Release automatically.

You can also run the workflows manually from GitHub Actions. Manual runs upload zips as workflow
artifacts but do not create a public release unless the run is from a version tag.

To reproduce the same package locally on Windows:

```powershell
.\scripts\build-windows-onedir.ps1
```

The script validates that `Orrery.exe`, `_internal\python312.dll`, the built UI, bundled skills,
Docker compose file, sandbox Dockerfile, launcher, and Windows notes are all present before creating
`release\Orrery-Windows.zip`. Do not publish `dist\Orrery\Orrery.exe` by itself.

To reproduce the macOS package on macOS:

```bash
./scripts/build-macos-app.sh
```

The script validates that `Orrery.app`, the built UI, bundled skills, Docker compose file, sandbox
Dockerfile, launcher, and macOS notes are all present before creating `release/Orrery-macOS.zip`.

Electron packaging lives under `desktop/electron`. Its first phase is a development shell and update
surface; signed installers and automatic update publishing come next.

## Test And Verify

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest

cd ui
npm run build
```

## Contributing

Contributions, feedback, and ideas are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), and [`SECURITY.md`](SECURITY.md) before opening issues
or pull requests.

## License

Orrery is licensed under the [Apache License 2.0](LICENSE).
