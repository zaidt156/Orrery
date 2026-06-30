# Scripts

`setup/` contains developer-machine setup helpers:

- `setup-venv.ps1` creates the Python environment outside OneDrive and links it into the project.
- `relink-node-modules.ps1` moves frontend dependencies outside OneDrive after `npm install`.

Release helpers:

- `build-windows-onedir.ps1` builds the frontend, creates the PyInstaller onedir package, validates
  the required `_internal` runtime files, and writes `release/Orrery-Windows.zip`.

Run scripts from the project root so the documented paths remain consistent.
