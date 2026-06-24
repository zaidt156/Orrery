# Backend

The backend is grouped by ownership:

| Path | Responsibility |
|---|---|
| `api.py` | FastAPI routes, local-session authentication, and response hardening |
| `core/` | Configuration, database access, models, migrations, app settings, and the job queue |
| `providers/` | Model accounts, model routing, provider discovery, and custom-model catalog |
| `features/` | Chat, trusted file exports, data connections, RAG, usage limits, and feedback |
| `security/` | Keychain access, privacy redaction, and outbound URL validation |

Add a module to the package that owns its behavior. Shared security and database
helpers should be imported from their existing package rather than duplicated.
