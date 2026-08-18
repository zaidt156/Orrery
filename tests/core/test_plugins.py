"""Plugin mounting (ADR-004).

A plugin is local code the user deliberately installed. These tests hold the line on what mounting
one is allowed to do: register deny-only hooks, reversibly, and nothing else. Nothing is fetched.
"""
import sys
import textwrap

import pytest

from backend import tools as tool_registry
from backend.core import plugins
from backend.tools import hooks


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    plugins.unmount_all()
    hooks._clear()
    yield
    plugins.unmount_all()
    hooks._clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _write_plugin(tmp_path, monkeypatch, name: str, body: str) -> str:
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(name, None)
    return name


def test_mounting_runs_setup_and_records_the_plugin(tmp_path, monkeypatch):
    name = _write_plugin(tmp_path, monkeypatch, "orrery_plugin_ok", """
        mounted = []

        def setup(ctx):
            mounted.append(ctx.name)
    """)

    plugins.mount(name)

    assert plugins.mounted() == [name]
    assert sys.modules[name].mounted == [name]


@pytest.mark.anyio
async def test_a_plugin_hook_actually_denies(tmp_path, monkeypatch):
    name = _write_plugin(tmp_path, monkeypatch, "orrery_plugin_deny", """
        def setup(ctx):
            async def refuse(call):
                return "refused by policy"
            ctx.register_pre_execute("refuse-everything", refuse)
    """)

    plugins.mount(name)
    objection = await hooks.deny_reason_for_tool(hooks.ToolCall(key="web_search"))

    assert objection is not None
    assert objection[0] == f"{name}:refuse-everything"
    assert objection[1] == "refused by policy"


@pytest.mark.anyio
async def test_a_plugin_cannot_grant_what_the_guards_refuse(tmp_path, monkeypatch):
    """The whole safety argument: a permissive plugin does not widen anything."""
    name = _write_plugin(tmp_path, monkeypatch, "orrery_plugin_permissive", """
        def setup(ctx):
            async def allow(call):
                return None
            ctx.register_pre_execute("allow-everything", allow)
    """)

    plugins.mount(name)
    result = await tool_registry.run_tool("web_search", {"query": "x"}, allowed=set())

    assert result["ok"] is False
    assert "allow-list" in result["error"]


def test_unmounting_reverses_every_registration(tmp_path, monkeypatch):
    name = _write_plugin(tmp_path, monkeypatch, "orrery_plugin_reversible", """
        def setup(ctx):
            async def refuse(call):
                return "no"
            ctx.register_pre_execute("a", refuse)
            ctx.register_pre_step("b", refuse)
    """)

    plugins.mount(name)
    assert len(hooks._pre_execute) == 1 and len(hooks._pre_step) == 1

    plugins.unmount_all()

    assert hooks._pre_execute == [] and hooks._pre_step == []
    assert plugins.mounted() == []


def test_a_plugin_without_setup_is_refused(tmp_path, monkeypatch):
    name = _write_plugin(tmp_path, monkeypatch, "orrery_plugin_nosetup", """
        answer = 42
    """)

    with pytest.raises(plugins.PluginError, match="no setup"):
        plugins.mount(name)


def test_a_plugin_that_fails_during_setup_leaves_nothing_behind(tmp_path, monkeypatch):
    """Half a policy is not a policy: a failed mount must not leave its earlier hooks attached."""
    name = _write_plugin(tmp_path, monkeypatch, "orrery_plugin_halfway", """
        def setup(ctx):
            async def refuse(call):
                return "no"
            ctx.register_pre_execute("registered-before-the-failure", refuse)
            raise RuntimeError("boom")
    """)

    with pytest.raises(plugins.PluginError, match="failed during setup"):
        plugins.mount(name)

    assert hooks._pre_execute == []
    assert plugins.mounted() == []


def test_an_unimportable_plugin_is_a_loud_failure():
    with pytest.raises(plugins.PluginError, match="Could not import"):
        plugins.mount("orrery_plugin_that_does_not_exist")


def test_a_plugin_name_is_a_module_path_never_something_to_fetch():
    for hostile in ("https://example.com/evil.py", "../../etc/passwd", "pkg:mod", ""):
        with pytest.raises(plugins.PluginError):
            plugins.mount(hostile)


def test_mount_all_reads_the_declared_list(tmp_path, monkeypatch):
    name = _write_plugin(tmp_path, monkeypatch, "orrery_plugin_declared", """
        def setup(ctx):
            pass
    """)

    assert plugins.mount_all([name]) == [name]


def test_mount_all_with_nothing_declared_does_nothing():
    assert plugins.mount_all([]) == []
    assert plugins.mounted() == []
