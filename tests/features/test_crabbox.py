from types import SimpleNamespace

import pytest

from backend.features import crabbox


@pytest.mark.anyio
async def test_crabbox_status_missing_cli_reports_unavailable(monkeypatch):
    async def fake_get_setting(_key, default=None):
        return default

    monkeypatch.setattr(crabbox.appconfig, "get_setting", fake_get_setting)
    monkeypatch.setattr(crabbox.shutil, "which", lambda _name: None)

    status = await crabbox.status()

    assert status["installed"] is False
    assert status["configured"] is False
    assert "not found" in status["doctor"]["error"].lower()


@pytest.mark.anyio
async def test_crabbox_status_parses_doctor_json_and_redacts(monkeypatch):
    async def fake_get_setting(_key, default=None):
        return {
            **crabbox.default_settings(),
            "enabled": True,
            "cli_path": "crabbox",
            "provider": "ssh",
            "target": "windows",
        }

    async def fake_run(argv, *, timeout, cwd=None):
        if argv[1] == "--version":
            return SimpleNamespace(returncode=0, stdout="crabbox 1.2.3", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout='{"ok":true,"checks":[{"status":"ok","message":"Bearer sk-secret-token"}]}',
            stderr="",
        )

    monkeypatch.setattr(crabbox.appconfig, "get_setting", fake_get_setting)
    monkeypatch.setattr(crabbox.shutil, "which", lambda _name: "crabbox")
    monkeypatch.setattr(crabbox, "_run", fake_run)

    status = await crabbox.status()

    assert status["configured"] is True
    assert status["version"] == "crabbox 1.2.3"
    payload = str(status["doctor"]["json"])
    assert "sk-secret-token" not in payload
    assert "[redacted]" in payload


@pytest.mark.anyio
async def test_crabbox_run_refuses_when_disabled(monkeypatch):
    async def fake_get_settings():
        return crabbox.CrabboxSettings(enabled=False)

    monkeypatch.setattr(crabbox, "get_settings", fake_get_settings)

    with pytest.raises(RuntimeError, match="disabled"):
        await crabbox.run_command(command=["echo", "hi"])
