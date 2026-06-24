import os

import pytest

from backend.features import local_models


def test_validate_local_model_name_is_constrained():
    assert local_models._validate_model_name("qwen3:4b", curated_only=True) == "qwen3:4b"
    with pytest.raises(ValueError):
        local_models._validate_model_name("../../bad model")
    with pytest.raises(ValueError):
        local_models._validate_model_name("unknown:latest", curated_only=True)


def test_local_install_requires_consent():
    with pytest.raises(ValueError, match="Confirm"):
        local_models.install(False)


@pytest.mark.skipif(os.name != "nt", reason="WinGet installation is Windows-only")
def test_local_install_uses_fixed_ollama_package(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return type("Result", (), {"returncode": 0, "stdout": "Installed", "stderr": ""})()

    monkeypatch.setattr(local_models.shutil, "which", lambda name: "winget.exe" if name == "winget" else None)
    monkeypatch.setattr(local_models.subprocess, "run", fake_run)

    local_models.install(True)

    assert captured["args"][captured["args"].index("--id") + 1] == "Ollama.Ollama"
    assert "--silent" in captured["args"]


@pytest.mark.anyio
async def test_local_status_marks_curated_installed_and_active(monkeypatch):
    monkeypatch.setattr(local_models, "_ollama_command", lambda: "ollama.exe")

    async def fake_info():
        return True, "1.0.0", [{"name": "qwen3:4b", "size": 100}]

    async def fake_active():
        return {"ollama/qwen3:4b"}

    monkeypatch.setattr(local_models, "_server_info", fake_info)
    monkeypatch.setattr(local_models.catalog, "active_ids", fake_active)

    result = await local_models.status()
    qwen = next(item for item in result["curated"] if item["name"] == "qwen3:4b")

    assert result["running"] is True
    assert qwen["installed"] is True
    assert qwen["active"] is True


@pytest.mark.anyio
async def test_pull_rejects_unreviewed_model_before_network_call():
    events = [event async for event in local_models.pull("../../unsafe")]

    assert events == [{"error": "Invalid Ollama model name."}]
