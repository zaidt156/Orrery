<div align="center">

<img src="assets/orrery-logo.svg" alt="Orrery" width="440">

### A local-first desktop AI workspace

Bring your own model accounts / API keys and your own PostgreSQL database — Orrery ties them together
into one private workspace that runs on your machine.

![License](https://img.shields.io/badge/License-Apache_2.0-F2B14E)
![Python](https://img.shields.io/badge/Python-3.12+-9DB9F0?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-Vite-9DB9F0?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0B1020?logo=fastapi&logoColor=009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-0B1020?logo=postgresql&logoColor=4169E1)
![PRs welcome](https://img.shields.io/badge/PRs-welcome-5BC489)

</div>

Nothing leaves your computer except the calls to the model providers you choose. Your data sits at the
centre, with focused tabs around it: **Chat · Data · Dashboards · Automations · Agents · Media Hub ·
Local Models · Settings**.

## Built with

| Layer | Technology |
|---|---|
| Backend | **Python 3.12** · FastAPI · SQLAlchemy + psycopg · Procrastinate (job queue) |
| Frontend | **React + Vite** (JavaScript) |
| Database | **PostgreSQL** + pgvector |
| Desktop shell | pywebview |
| Models | litellm (API providers) · official CLI plans · Ollama (local) |
| File sandbox | Docker (isolated code execution) |

## Features

- **Chat** with frontier or local models — streaming responses, adaptive reasoning, and full Markdown.
- **File generation** — ask for a PDF, Word document, Excel sheet, PowerPoint, CSV, chart, or image and
  get a real, downloadable file. Generation runs in an isolated sandbox.
- **Data** — connect a PostgreSQL database and browse it safely.
- **Dashboards, Automations & Agents** — turn your data and models into live views, scheduled
  workflows, and scoped assistants.
- **Local Models** — run private on-device models through Ollama, no API key required.
- **Bring your own everything** — your models, your database, your machine.

## Getting started

**Prerequisites:** Python 3.12+, Node.js 20+, and Docker Desktop.

```bash
# 1) Start a local PostgreSQL (pgvector) database.
#    Create a .env file with LOCAL-ONLY values (never commit it):
#      POSTGRES_USER=orrery
#      POSTGRES_PASSWORD=choose_a_local_password
#      POSTGRES_DB=orrery
#      POSTGRES_PORT=5432
#      DATABASE_URL=postgresql+psycopg://orrery:choose_a_local_password@127.0.0.1:5432/orrery
docker compose up -d

# 2) Backend
python -m venv .venv
#   Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

# 3) Frontend
cd ui && npm install && npm run build && cd ..

# 4) Run
python app.py
```

On first launch Orrery connects to your database, applies migrations, and opens the desktop window.
Set up model access in **Settings → Accounts**.

> Optional: on Windows, if the project lives in a synced folder, the helpers in `scripts/setup/`
> keep `node_modules` and the virtual environment out of the sync path.

## Models & keys

In **Settings → Accounts** you can add API keys for major providers, connect supported CLI-based
plans, add any OpenAI-compatible endpoint, or run local models with Ollama. **API keys are stored in
your operating system's keychain** — never in files, logs, or this repository — and the interface
only ever shows a masked preview.

For ChatGPT-plan access, the default model is automatic: Orrery lets the official Codex CLI choose
the newest GPT model that the installed CLI and signed-in account can use. If the local CLI is too
old, Settings shows an update action; if a pinned GPT model is rejected by Codex, Orrery retries the
same request through the automatic default route instead of failing immediately.

## Security

Orrery is built local-first and security-first:

- **Secrets stay in your OS keychain** — never written to disk, logs, or source control.
- **The app runs locally** — its API is bound to localhost and protected by a per-session token.
- **Model-written code is sandboxed** — code used to generate files runs in an isolated, network-less
  environment with strict resource limits, never in the app process.
- **Database access is read-only and parameterized.**

See [`SECURITY.md`](SECURITY.md) to report a vulnerability.

## Contributing

Contributions are welcome! Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development
setup and pull-request workflow, and our [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Open an issue
with the provided templates for bugs and feature requests; report security issues privately via
[`SECURITY.md`](SECURITY.md).

## License

Licensed under the [Apache License 2.0](LICENSE).

