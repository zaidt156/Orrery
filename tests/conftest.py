import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from backend.providers import accounts
from backend.security import secrets


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    """Back the keychain with an in-memory dict so tests never touch the real one."""
    accounts.clear_status_cache()
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(secrets.keyring, "get_password", lambda s, n: store.get((s, n)))
    monkeypatch.setattr(secrets.keyring, "set_password", lambda s, n, v: store.__setitem__((s, n), v))
    monkeypatch.setattr(secrets.keyring, "delete_password", lambda s, n: store.pop((s, n), None))
    monkeypatch.setattr(accounts, "_safe_cli_flags_ready", lambda: (True, None))
    monkeypatch.setattr(accounts, "_run_claude_auth_status", lambda: (False, None, "Claude Code is unavailable in tests."))
    monkeypatch.setattr(accounts, "_command_version", lambda _cmd: None)
    monkeypatch.setattr(accounts, "_verify_claude_ready", lambda: None)
    monkeypatch.setattr(accounts, "_verify_codex_ready", lambda: None)
    return store


@pytest.fixture
def anyio_backend():
    return "asyncio"
