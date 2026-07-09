import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from backend.features import admin, team
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

    async def default_flags():
        return {name: default for name, (_label, default) in admin.FEATURES.items()}

    async def solo_team_mode():
        return False

    async def solo_current_user():
        return team.SOLO_USER

    async def solo_is_admin():
        return True

    monkeypatch.setattr(admin, "get_flags", default_flags)
    monkeypatch.setattr(team, "team_mode", solo_team_mode)
    monkeypatch.setattr(team, "current_user", solo_current_user)
    monkeypatch.setattr(team, "is_admin", solo_is_admin)
    return store


@pytest.fixture
def anyio_backend():
    return "asyncio"
