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
    monkeypatch.setattr(app, "main", lambda open_browser=True, auto_build=True: seen.update(
        mode="web", open_browser=open_browser, auto_build=auto_build))
    monkeypatch.setattr(app, "run_backend_only", lambda: seen.update(mode="backend-only"))
    monkeypatch.setattr(app, "_packaging_probe", lambda: seen.update(mode="probe"))
    return seen


def test_no_arguments_starts_the_web_app_and_opens_a_browser(calls):
    app.cli([])
    assert calls == {"mode": "web", "open_browser": True, "auto_build": True}


def test_web_subcommand_is_the_same_as_no_arguments(calls):
    app.cli(["web"])
    assert calls == {"mode": "web", "open_browser": True, "auto_build": True}


def test_no_browser_starts_the_app_without_opening_one(calls):
    app.cli(["web", "--no-browser"])
    assert calls == {"mode": "web", "open_browser": False, "auto_build": True}


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


def test_missing_bundle_with_no_checkout_to_build_from_fails_loudly(monkeypatch, tmp_path):
    """No ui/package.json means this is not a checkout - there is nothing to build, so say so."""
    monkeypatch.setattr(app.settings, "orrery_dev", False)
    monkeypatch.setattr(app, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(app.paths, "project_root", lambda: tmp_path)
    with pytest.raises(SystemExit, match="bundle is missing"):
        app._ensure_ui_bundle()


def test_present_workspace_bundle_passes(monkeypatch, tmp_path):
    index = tmp_path / "ui" / "dist" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(app.settings, "orrery_dev", False)
    monkeypatch.setattr(app, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(app.paths, "project_root", lambda: tmp_path)
    app._ensure_ui_bundle()


def test_dump_config_prints_the_resolved_tree_without_starting_anything(calls, capsys):
    """`--dump-config` is a diagnostic: it must never boot a database, server, or browser."""
    app.cli(["--dump-config"])

    out = capsys.readouterr().out
    assert calls == {}
    assert "Orrery configuration" in out
    assert "api_port" in out
    assert "profile file" in out


def test_dump_config_is_not_treated_as_an_unknown_argument(calls, capsys):
    app.cli(["web", "--dump-config"])

    assert calls == {}
    assert "Unrecognized argument" not in capsys.readouterr().err


def _empty_bundle(monkeypatch, tmp_path):
    """Point the bundle check at an empty tree so it behaves like a fresh checkout."""
    monkeypatch.setattr(app, "resource_path", lambda *p: tmp_path.joinpath(*p))
    monkeypatch.setattr(app.paths, "project_root", lambda: tmp_path)
    (tmp_path / "ui").mkdir(exist_ok=True)
    return tmp_path


def test_present_bundle_never_shells_out(monkeypatch, tmp_path):
    """The common case must not cost a subprocess, or every start pays for the first one."""
    root = _empty_bundle(monkeypatch, tmp_path)
    (root / "ui" / "dist").mkdir(parents=True)
    (root / "ui" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(app, "_build_ui_bundle", lambda _dir: pytest.fail("should not build"))

    app._ensure_ui_bundle()


def test_a_fresh_checkout_builds_the_bundle_once(monkeypatch, tmp_path):
    root = _empty_bundle(monkeypatch, tmp_path)
    (root / "ui" / "package.json").write_text("{}", encoding="utf-8")
    built = []

    def fake_build(ui_dir):
        built.append(ui_dir)
        (root / "ui" / "dist").mkdir(parents=True)
        (root / "ui" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")

    monkeypatch.setattr(app, "_build_ui_bundle", fake_build)

    app._ensure_ui_bundle()

    assert built == [root / "ui"]


def test_no_build_refuses_instead_of_building(monkeypatch, tmp_path):
    root = _empty_bundle(monkeypatch, tmp_path)
    (root / "ui" / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app, "_build_ui_bundle", lambda _dir: pytest.fail("should not build"))

    with pytest.raises(SystemExit, match="workspace bundle is missing"):
        app._ensure_ui_bundle(auto_build=False)


def test_a_packaged_build_never_tries_to_build(monkeypatch, tmp_path):
    """A frozen app ships its bundle and has no checkout, npm, or network to build with."""
    root = _empty_bundle(monkeypatch, tmp_path)
    (root / "ui" / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app, "_build_ui_bundle", lambda _dir: pytest.fail("should not build"))

    with pytest.raises(SystemExit, match="workspace bundle is missing"):
        app._ensure_ui_bundle()


def test_missing_npm_says_what_to_install(monkeypatch, tmp_path):
    root = _empty_bundle(monkeypatch, tmp_path)
    monkeypatch.setattr("backend.core.proc.find_executable", lambda _n: None)

    with pytest.raises(SystemExit, match="Node.js"):
        app._build_ui_bundle(root / "ui")


def test_a_failed_build_reports_the_step_that_failed(monkeypatch, tmp_path):
    root = _empty_bundle(monkeypatch, tmp_path)
    (root / "ui" / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("backend.core.proc.find_executable", lambda _n: "npm")

    class _Failed:
        returncode = 1

    monkeypatch.setattr("backend.core.proc.run", lambda *a, **k: _Failed())

    with pytest.raises(SystemExit, match="npm ci"):
        app._build_ui_bundle(root / "ui")


def test_no_build_flag_is_accepted_and_passed_through(calls):
    app.cli(["web", "--no-build"])

    assert calls == {"mode": "web", "open_browser": True, "auto_build": False}
