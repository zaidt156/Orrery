"""Desktop startup decisions that must stay reliable in packaged backend mode."""

from __future__ import annotations

import app


def test_backend_only_provisions_local_database_even_if_hidden_console_looks_interactive(monkeypatch):
    saved: list[str] = []

    class HiddenConsole:
        @staticmethod
        def isatty() -> bool:
            return True

    local_url = app.database.normalize_url(
        "postgresql://orrery:orrery_dev_password@127.0.0.1:5432/orrery"
    )
    monkeypatch.setattr(app.sys, "argv", ["OrreryBackend.exe", "--backend-only"])
    monkeypatch.setattr(app.sys, "stdin", HiddenConsole())
    monkeypatch.setattr(app.database, "resolve_database_url", lambda: local_url)
    monkeypatch.setattr(app.database, "save_database_url", saved.append)

    calls: list[tuple[str | None, bool]] = []

    def should_ensure(url: str | None, *, stdin_isatty: bool) -> bool:
        calls.append((url, stdin_isatty))
        return True

    from backend.core import dockerboot

    monkeypatch.setattr(dockerboot, "should_ensure_local", should_ensure)
    monkeypatch.setattr(dockerboot, "provision", lambda: dockerboot.DEFAULT_URL)

    assert app.ensure_connection() == dockerboot.DEFAULT_URL
    assert calls == [(local_url, False)]
    assert saved == [dockerboot.DEFAULT_URL]
