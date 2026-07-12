# Scripts

`setup/` contains developer-machine setup helpers:

- `setup-venv.ps1` creates the Python environment outside OneDrive and links it into the project.
- `relink-node-modules.ps1` moves frontend dependencies outside OneDrive after `npm install`.

Release helpers:

- `../desktop/electron/` contains the Electron migration shell. It starts `app.py --backend-only`,
  waits for the local API, loads the existing React UI, and provides native file-save/update bridges.
- `build-windows-onedir.ps1` builds the frontend, creates the PyInstaller onedir package, validates
  the required `_internal` runtime files, runs the frozen desktop-runtime probe, and writes
  `release/Orrery-Windows.zip`.
- `build-macos-app.sh` builds the frontend, creates the PyInstaller `.app` bundle, runs the frozen
  desktop-runtime/resource probe, copies macOS setup helpers, and writes `release/Orrery-macOS.zip`.
- `windows/` contains the batch files and Windows notes copied into the release package:
  `setup-orrery.bat`, `run-orrery.bat`, and `README-WINDOWS.txt`.
- `macos/` contains the command files and macOS notes copied into the release package:
  `setup-orrery.command`, `run-orrery.command`, and `README-MACOS.txt`.

Stress and scale checks:

- `.venv/Scripts/python scripts/stress_100_file_lifecycle.py --allow-configured-database`
  creates 100 disposable files across all 20 FileGen formats inside the real locked-down Docker
  sandbox, then validates storage, previews, mixed-format project indexing, retrieval, isolation,
  deletion, limits, and cleanup. It requires `orrery-sandbox:latest`, explicitly refuses non-local
  databases, never calls an AI provider, and deletes only the UUID-scoped rows from its current run.
- `.venv/Scripts/python scripts/stress_ontology_rag.py` creates 300 disposable text files across
  three ontologies and verifies ingestion, search, chat gathering, attribution, isolation, timing,
  and cleanup against the local Postgres/pgvector database.

Run scripts from the project root so the documented paths remain consistent.
