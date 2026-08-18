"""The `orrery` console script is now the whole delivery mechanism.

There is no native shell left, so these argument decisions are the difference between "the app
starts" and "the app does not". The build and service modes are exercised too because the
packaging scripts and the frozen executables still invoke them by flag.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import app


@pytest.fixture
def calls(monkeypatch):
    """Record which mode cli() picked without starting a database, server, or browser."""
    seen: dict[str, object] = {}
    monkeypatch.setattr(app, "main", lambda open_browser=True: seen.update(mode="web", open_browser=open_browser))
    monkeypatch.setattr(app, "run_backend_only", lambda: seen.update(mode="backend-only"))
    monkeypatch.setattr(app, "_packaging_probe", lambda: seen.update(mode="probe"))
    return seen


def test_no_arguments_starts_the_web_app_and_opens_a_browser(calls):
    app.cli([])
    assert calls == {"mode": "web", "open_browser": True}


def test_web_subcommand_is_the_same_as_no_arguments(calls):
    app.cli(["web"])
    assert calls == {"mode": "web", "open_browser": True}


def test_no_browser_starts_the_app_without_opening_one(calls):
    app.cli(["web", "--no-browser"])
    assert calls == {"mode": "web", "open_browser": False}


def test_backend_only_still_reachable_for_the_packaged_service(calls):
    app.cli(["--backend-only"])
    assert calls == {"mode": "backend-only"}


def test_packaging_probe_still_reachable_for_release_builds(calls):
    app.cli(["--packaging-probe"])
    assert calls == {"mode": "probe"}


def test_help_prints_usage_without_starting_anything(calls, capsys):
    app.cli(["--help"])
    assert "orrery [web]" in capsys.readouterr().out
    assert calls == {}


def test_unknown_argument_fails_instead_of_silently_starting(calls, capsys):
    with pytest.raises(SystemExit) as exit_info:
        app.cli(["--serve-to-the-internet"])
    assert exit_info.value.code == 2
    assert "--serve-to-the-internet" in capsys.readouterr().err
    assert calls == {}


def test_console_script_points_at_the_entry_point_that_exists():
    """A typo here is invisible until `pip install` produces an `orrery` that cannot run."""
    pyproject = tomllib.loads(Path(app.__file__).with_name("pyproject.toml").read_text(encoding="utf-8"))
    module, _, function = pyproject["project"]["scripts"]["orrery"].partition(":")
    assert module == "app"
    assert callable(getattr(app, function))


def test_missing_workspace_bundle_fails_loudly_rather_than_serving_a_blank_page(monkeypatch, tmp_path):
    monkeypatch.setattr(app.settings, "orrery_dev", False)
    monkeypatch.setattr(app, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    with pytest.raises(SystemExit, match="bundle is missing"):
        app._require_ui_bundle()


def test_present_workspace_bundle_passes(monkeypatch, tmp_path):
    index = tmp_path / "ui" / "dist" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(app.settings, "orrery_dev", False)
    monkeypatch.setattr(app, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    app._require_ui_bundle()
