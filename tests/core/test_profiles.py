"""Layered configuration and its provenance (ADR-004).

Isolation matters here: every test points the profile, home, and env-file layers at a tmp_path, so
none of this reads the developer's real configuration.
"""
import pytest

from backend.core import profiles
from backend.core.config import Settings


@pytest.fixture(autouse=True)
def _isolated_layers(tmp_path, monkeypatch):
    monkeypatch.setenv("ORRERY_PROFILE", str(tmp_path / "orrery.toml"))
    monkeypatch.setenv("ORRERY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ORRERY_ENV_FILE", str(tmp_path / ".env"))
    (tmp_path / "data").mkdir()
    for name in ("RAG_TOP_K", "API_PORT", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_a_missing_layer_is_simply_absent(_isolated_layers):
    assert profiles.merged_file_values() == {}
    assert Settings().rag_top_k == 5


def test_profile_file_overrides_the_default(_isolated_layers):
    (_isolated_layers / "orrery.toml").write_text("[orrery]\nrag_top_k = 42\n", encoding="utf-8")

    assert Settings().rag_top_k == 42


def test_a_flat_table_works_too(_isolated_layers):
    (_isolated_layers / "orrery.toml").write_text("rag_top_k = 11\n", encoding="utf-8")

    assert Settings().rag_top_k == 11


def test_home_layer_beats_the_profile_layer(_isolated_layers):
    (_isolated_layers / "orrery.toml").write_text("[orrery]\nrag_top_k = 42\n", encoding="utf-8")
    (_isolated_layers / "data" / "config.toml").write_text(
        "[orrery]\nrag_top_k = 99\n", encoding="utf-8")

    assert Settings().rag_top_k == 99


def test_environment_beats_every_file_layer(_isolated_layers, monkeypatch):
    (_isolated_layers / "orrery.toml").write_text("[orrery]\nrag_top_k = 42\n", encoding="utf-8")
    (_isolated_layers / "data" / "config.toml").write_text(
        "[orrery]\nrag_top_k = 99\n", encoding="utf-8")
    monkeypatch.setenv("RAG_TOP_K", "7")

    assert Settings().rag_top_k == 7


def test_unknown_keys_in_a_layer_are_ignored_not_fatal(_isolated_layers):
    (_isolated_layers / "orrery.toml").write_text(
        "[orrery]\nrag_top_k = 3\nnot_a_setting = 'ignored'\n", encoding="utf-8")

    assert Settings().rag_top_k == 3


def test_malformed_toml_is_reported_not_silently_dropped(_isolated_layers):
    (_isolated_layers / "orrery.toml").write_text("this is not toml = = =\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid TOML"):
        profiles.merged_file_values()


def test_dump_names_the_layer_each_value_came_from(_isolated_layers):
    (_isolated_layers / "orrery.toml").write_text("[orrery]\nrag_top_k = 42\n", encoding="utf-8")

    rows = {r["setting"]: r for r in profiles.dump(Settings())}

    assert rows["rag_top_k"]["source"] == "profile"
    assert rows["rag_top_k"]["value"] == 42
    assert rows["api_host"]["source"] == "defaults"


def test_dump_redacts_anything_credential_shaped(_isolated_layers, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://orrery:hunter2@127.0.0.1:5432/orrery")

    rows = {r["setting"]: r for r in profiles.dump(Settings())}
    rendered = profiles.render(Settings())

    assert "hunter2" not in str(rows["database_url"]["value"])
    assert "hunter2" not in rendered
    assert rows["database_url"]["source"] == "environment"


def test_render_lists_every_setting_and_where_the_files_are(_isolated_layers):
    rendered = profiles.render(Settings())

    for name in Settings.model_fields:
        assert name in rendered
    assert "profile file" in rendered and "home file" in rendered and "env file" in rendered
