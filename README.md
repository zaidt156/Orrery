<div align="center">

<img src="assets/orrery-logo.svg" alt="Orrery" width="440">

### A local-first AI workspace — runs on your machine, opens in your browser

Orrery ties your own AI accounts and your own PostgreSQL database together into one local
workspace. It runs entirely on your machine and has no hosted account, telemetry, or phone-home
service; credentials stay in your OS keychain.

![Version](https://img.shields.io/badge/version-0.2.1-E5A93F)
![License](https://img.shields.io/badge/License-Apache_2.0-F2B14E)
![Windows](https://img.shields.io/badge/Windows-supported-9DB9F0?logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12+-9DB9F0?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-Vite-9DB9F0?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-localhost-0B1020?logo=fastapi&logoColor=009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-0B1020?logo=postgresql&logoColor=4169E1)
![PRs welcome](https://img.shields.io/badge/PRs-welcome-5BC489)

</div>

## Install

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

Orrery binds to `127.0.0.1`, prints the URL, and opens your browser at it.

| Flag | What it does |
|---|---|
| `--no-browser` | start the backend without opening a browser; paste the printed URL yourself |
| `--no-build` | never build the workspace bundle; fail if it is missing (a machine without Node) |
| `--dump-config` | print every setting, its value, and the layer it came from, then exit |

That URL carries a single-use launch code. The page trades it for an httpOnly session cookie and
strips it from the address bar, so the credential never settles into history or a bookmark.

### Connect a model

Open `Settings → Accounts & Keys` inside Orrery and add an API key, connect a Claude/ChatGPT/Gemini
plan through its official CLI, or pull a local model with Ollama. Nothing is preconfigured: you
bring the accounts, and only the prompt and context a request needs is sent to that provider.

## Documentation

| Document | Contents |
|---|---|
| [User guide](https://zaidt156.github.io/Orrery/guide.html) | What each part of the workspace does |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The architecture as implemented — data, retrieval, sandboxing, security boundaries |
| [`PLAN.md`](PLAN.md) | Product direction and sequencing |
| [`TODO.md`](TODO.md) | Unfinished work only |
| [`DEVLOG`](docs/history/DEVLOG.md) | Append-only history of completed work |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to build, test, and open a pull request |
| [`SECURITY.md`](SECURITY.md) | How to report a vulnerability |

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
