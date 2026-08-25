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

1. [Git](https://git-scm.com/downloads) — used to download Orrery and to update it later.
2. [Python 3.12 or newer](https://www.python.org/downloads/). On Windows, tick
   **"Add python.exe to PATH"** in the installer; without it the commands below are not found.
3. [Node.js 20 or newer](https://nodejs.org/) — Orrery builds its workspace bundle itself, once, on
   first run.
4. [Docker Desktop](https://www.docker.com/products/docker-desktop/) — Orrery starts it and
   provisions PostgreSQL itself, on first run.
5. Optional: Ollama for local models, plus provider API keys or official provider CLIs.

Install each from the links above, accepting the defaults, then restart your computer if any
installer asks you to.

### Never used a terminal?

A terminal is a window where you type commands. You need one to run the line below.

- **Windows** — press `Win`, type `PowerShell`, press Enter.
- **macOS** — press `Cmd + Space`, type `Terminal`, press Enter.
- **Linux** — press `Ctrl + Alt + T`.

Copy the command, paste it into that window (right-click pastes on Windows), and press Enter.

### Install and run

```bash
git clone https://github.com/zaidt156/Orrery.git && cd Orrery && pip install -e . && orrery
```

That is the whole thing — one line, pasted once. It downloads Orrery into a folder named `Orrery`
inside whatever folder your terminal was in, installs it, and starts it.

The first run does the setup that used to be a list of commands:

- builds the workspace bundle with npm (about a minute, once — later starts skip it)
- starts Docker Desktop if it is installed but not running, brings up PostgreSQL with pgvector,
  and saves the connection string to your OS keychain
- opens your browser on the workspace

No `.env` is required: it is for overriding local development settings, and the connection string
lives in the keychain rather than on disk. Use a virtual environment if you prefer
(`python -m venv .venv` and activate it before `pip install -e .`).

**If a command is "not found":** on Windows try `py -m pip install -e .` instead of `pip install -e .`,
and close and reopen the terminal after installing anything — a new terminal is what picks up a newly
installed program.

**If you would rather not install Git:** use the green **Code** button on
[the repository page](https://github.com/zaidt156/Orrery), choose **Download ZIP**, unzip it, then
open a terminal in the unzipped folder and run `pip install -e . && orrery`. Updating later means
downloading a fresh ZIP, which is why Git is the easier path.

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
