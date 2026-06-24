# Scripts

`setup/` contains developer-machine setup helpers:

- `setup-venv.ps1` creates the Python environment outside OneDrive and links it into the project.
- `relink-node-modules.ps1` moves frontend dependencies outside OneDrive after `npm install`.

Run scripts from the project root so the documented paths remain consistent.
