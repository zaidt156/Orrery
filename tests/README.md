# Tests

The test tree mirrors the backend:

- `core/` covers configuration and infrastructure assumptions.
- `providers/` covers model routes, account CLIs, and the model catalog.
- `features/` covers chat, trusted file exports, data, and RAG.
- `security/` covers secrets, privacy redaction, and network guards.
- `test_api.py` covers the local HTTP boundary.
- `conftest.py` provides shared isolated keychain fixtures.

Run everything from the project root with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
