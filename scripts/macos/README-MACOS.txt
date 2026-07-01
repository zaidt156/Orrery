Orrery macOS Preview
====================

Supported platform:
- macOS preview package. The GitHub-built artifact follows the architecture of the macOS runner
  that produced it; Apple Silicon is the priority target.

Included in this folder:
- Orrery.app
- setup-orrery.command
- run-orrery.command
- docker-compose.yml for the optional included PostgreSQL database
- sandbox/Dockerfile for sandboxed file generation

Quick start:
1. Extract the full Orrery-macOS.zip folder.
2. Double-click setup-orrery.command, or run it from Terminal:
   ./setup-orrery.command
3. Choose one setup option:
   - included Docker PostgreSQL database
   - your own PostgreSQL database URL
   - sandbox image only
   - start Orrery only
4. After setup, use run-orrery.command for normal launches.

Requirements:
- macOS 13 or newer is the intended baseline for preview builds.
- PostgreSQL with pgvector, either your own server or the included Docker Compose database.
- Docker Desktop if you want the included PostgreSQL database or sandboxed file generation.

Default included database URL:
postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery

Unsigned preview note:
This preview is not notarized yet. If macOS blocks it, right-click Orrery.app and choose Open, or
remove quarantine from the extracted folder only if you trust the downloaded release:
  xattr -dr com.apple.quarantine Orrery.app setup-orrery.command run-orrery.command

Security notes:
- Provider API keys stay in the operating-system keychain.
- The app binds to localhost and uses a per-session token.
- The included Docker database is for local preview/dev use. Use your own PostgreSQL server for real data.
- Sandboxed file generation runs in Docker with no network access.
