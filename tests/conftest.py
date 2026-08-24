import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from backend.core.config import settings
from backend.features import admin, team
from backend.providers import accounts
from backend.security import secrets

# Tests marked `db` talk to a real PostgreSQL. A developer without `docker compose up -d` should
# get an honest skip rather than a connection timeout, but CI must never quietly skip the very
# coverage it spun a database up to provide - so ORRERY_REQUIRE_DB=1 turns the skip into a failure.
#
# Configured is not the same as reachable, and conflating the two is what made the suite unusable
# on a developer machine: `.env` still names a database after `docker compose down`, so every db
# test believed one existed and blocked on connect instead of skipping. The check below asks the
# only question that matters - does something answer - once per session, cheaply.
_DATABASE_URL = os.environ.get("DATABASE_URL") or settings.database_url
_DATABASE_REQUIRED = os.environ.get("ORRERY_REQUIRE_DB") == "1"
_PROBE_TIMEOUT_SECONDS = 1.5


def _database_answers(url: str | None) -> bool:
    """One short TCP connect. Not a health check - just 'is anything listening there'."""
    if not url:
        return False
    import socket
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        host, port = parts.hostname or "127.0.0.1", parts.port or 5432
    except ValueError:
        return False
    probe = socket.socket()
    probe.settimeout(_PROBE_TIMEOUT_SECONDS)
    try:
        probe.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


_DATABASE_AVAILABLE = _database_answers(_DATABASE_URL)


@pytest.fixture(autouse=True)
def _database_required(request):
    if request.node.get_closest_marker("db") is None or _DATABASE_AVAILABLE:
        return
    if _DATABASE_REQUIRED:
        pytest.fail(
            f"ORRERY_REQUIRE_DB=1 but nothing answered at {_DATABASE_URL or '<unset>'}. "
            "Start the PostgreSQL this job provides."
        )
    if _DATABASE_URL:
        pytest.skip(
            "a database is configured but nothing is listening - start it with "
            "`docker compose up -d`"
        )
    pytest.skip("no PostgreSQL configured - start one with `docker compose up -d`, or set DATABASE_URL")


@pytest.fixture(autouse=True)
def _unreachable_database_fails_fast(request, monkeypatch):
    """With no database listening, reaching for one must name the test instead of hanging it.

    pytest.ini's own rule is that a hung test has to name itself. An UNMARKED test that quietly
    depends on PostgreSQL broke that: it blocked on connect until the per-test timeout killed the
    whole session, and the traceback pointed at the event loop rather than at the test. Turning that
    into an immediate, explicit error is what makes `pytest -m "not db"` usable without Docker - and
    it is also how a missing `db` marker gets found, which is exactly how the marker below was.

    Marked tests never get here: they have already skipped. When a database IS reachable this
    fixture does nothing at all.
    """
    if _DATABASE_AVAILABLE or request.node.get_closest_marker("db") is not None:
        return
    from backend.core import database

    def _no_database(*_args, **_kwargs):
        raise RuntimeError(
            f"This test reached PostgreSQL, but nothing is listening at "
            f"{_DATABASE_URL or '<unset>'}. Start it with `docker compose up -d`, or mark the test "
            f"`@pytest.mark.db` if it genuinely needs a database."
        )

    monkeypatch.setattr(database, "get_sessionmaker", _no_database)
    # Most modules do `from backend.core.database import get_sessionmaker`, which binds the function
    # into their own namespace at import. Patching only the source module leaves every one of those
    # bindings pointing at the real connector, which is why the first version of this fixture
    # changed nothing. Rebind wherever the name actually lives.
    for module in list(sys.modules.values()):
        if module is None or not getattr(module, "__name__", "").startswith("backend."):
            continue
        if getattr(module, "get_sessionmaker", None) is not None:
            monkeypatch.setattr(module, "get_sessionmaker", _no_database, raising=False)


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
