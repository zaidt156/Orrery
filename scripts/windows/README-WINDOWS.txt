Orrery Windows Preview
======================

Supported platform:
- Windows 10/11 for now.

Included in this folder:
- Orrery.exe
- _internal\  (required PyInstaller onedir runtime; do not move or delete it)
- setup-orrery.bat
- run-orrery.bat
- docker-compose.yml for the optional included PostgreSQL database
- sandbox\Dockerfile for sandboxed file generation

First-run security warning (important):
Because this preview build is not code-signed yet, Windows SmartScreen shows a blue
"Windows protected your PC" box the first time you run setup-orrery.bat or Orrery.exe.
This is expected for any new, unsigned app - it is NOT a virus warning about Orrery.
To run it:
  1. In the blue box, click "More info".
  2. Click the "Run anyway" button that appears.
You only need to do this once per file. If your browser warned while downloading the .zip,
choose "Keep". A code-signed release (which removes this prompt) is planned.

Quick start:
1. Extract the full Orrery-Windows.zip folder.
2. Do not copy Orrery.exe out by itself.
3. Double-click setup-orrery.bat.
4. Choose one setup option:
   - included Docker PostgreSQL database
   - your own PostgreSQL database URL
   - sandbox image only
   - start Orrery only
5. After setup, use run-orrery.bat for normal launches.

Requirements:
- PostgreSQL with pgvector, either your own server or the included Docker Compose database.
- Docker Desktop if you want the included PostgreSQL database or sandboxed file generation.
- The desktop web runtime is bundled in the package through Qt WebEngine.

Default included database URL:
postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery

PowerShell note:
PowerShell does not run current-folder programs by name only. Use:
.\setup-orrery.bat
.\run-orrery.bat
.\Orrery.exe

Security notes:
- Provider API keys stay in the Windows keychain.
- The app binds to localhost and uses a per-session token.
- The included Docker database is for local preview/dev use. Use your own PostgreSQL server for real data.
- Sandboxed file generation runs in Docker with no network access.
