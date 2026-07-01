# Orrery Electron Shell

This is the migration path from `pywebview`/Qt packaging to an Electron desktop shell.

The React UI is unchanged. Electron starts the existing Python/FastAPI backend with
`app.py --backend-only`, waits for `/api/health`, then loads the normal Orrery URL with the
session token.

## Development

From the repo root:

```powershell
cd ui
npm run build

cd ..\desktop\electron
npm install
npm run dev
```

Use `ORRERY_PYTHON` if the Python executable is not at `.venv\Scripts\python.exe`.

## Current Scope

- Native desktop window through Electron.
- Existing React app, FastAPI backend, Postgres database, and Docker sandbox remain unchanged.
- Existing UI file-save calls keep working through a compatibility bridge:
  `window.pywebview.api.save_file(...)`.
- Native auto-update scaffolding is present through `electron-updater`, but real automatic
  install/update requires signed packaged builds and release metadata.

