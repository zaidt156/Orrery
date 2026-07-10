"""Live connection check: aggregation, isolation, scrubbing, inclusion rules (no real probes)."""
import asyncio

import pytest

from backend.features import connectivity


@pytest.fixture(autouse=True)
def clean_slate(monkeypatch):
    """Nothing configured, database reachable — each test opts specific checks in."""
    connectivity._last = None
    monkeypatch.setattr(connectivity.secrets, "get_provider_key", lambda p: None)
    monkeypatch.setattr(connectivity.secrets, "get_secret", lambda k: None)
    monkeypatch.setattr(connectivity.local_models, "_ollama_command", lambda: None)

    async def no_customs():
        return []

    async def db_ok(force=False):
        return True

    monkeypatch.setattr(connectivity.catalog, "list_custom_models", no_customs)
    monkeypatch.setattr(connectivity.database, "check_connection", db_ok)


@pytest.mark.anyio
async def test_database_only_when_nothing_else_is_configured():
    result = await connectivity.check_all()
    assert result["ok"] is True
    assert [c["id"] for c in result["checks"]] == ["database"]
    check = result["checks"][0]
    assert check["ok"] is True and isinstance(check["ms"], int) and check["ms"] >= 0


@pytest.mark.anyio
async def test_one_failing_provider_turns_overall_red_but_stays_isolated(monkeypatch):
    monkeypatch.setattr(connectivity.secrets, "get_provider_key", lambda p: "k" if p == "openai" else None)

    async def failing_probe(provider):
        return False, "authentication failed"

    monkeypatch.setattr(connectivity.ai, "probe_provider", failing_probe)

    result = await connectivity.check_all()

    assert result["ok"] is False
    by_id = {c["id"]: c for c in result["checks"]}
    assert by_id["database"]["ok"] is True          # siblings unaffected
    assert by_id["openai"]["ok"] is False
    assert "authentication failed" in by_id["openai"]["detail"]


@pytest.mark.anyio
async def test_raising_probe_is_contained_and_secret_scrubbed(monkeypatch):
    monkeypatch.setattr(connectivity.secrets, "get_provider_key", lambda p: "k" if p == "openai" else None)

    async def exploding_probe(provider):
        raise RuntimeError("boom sk-proj-SUPERSECRET123 leaked")

    monkeypatch.setattr(connectivity.ai, "probe_provider", exploding_probe)

    result = await connectivity.check_all()

    check = next(c for c in result["checks"] if c["id"] == "openai")
    assert check["ok"] is False
    assert "SUPERSECRET123" not in check["detail"]
    assert "Traceback" not in check["detail"]


@pytest.mark.anyio
async def test_stored_plan_connection_is_probed(monkeypatch):
    monkeypatch.setattr(
        connectivity.secrets, "get_secret",
        lambda k: "connected" if k == connectivity.accounts._CLAUDE_PLAN_KEY else None,
    )
    monkeypatch.setattr(
        connectivity.accounts, "claude_plan_mode_status",
        lambda force=False: {"configured": True, "message": "Claude plan ready"},
    )

    result = await connectivity.check_all()

    by_id = {c["id"]: c for c in result["checks"]}
    assert by_id["claude_plan"]["ok"] is True
    assert "ready" in by_id["claude_plan"]["detail"].lower()


@pytest.mark.anyio
async def test_ollama_included_only_when_installed(monkeypatch):
    monkeypatch.setattr(connectivity.local_models, "_ollama_command", lambda: "ollama")

    async def stopped():
        return {"installed": True, "running": False, "version": None, "models": []}

    monkeypatch.setattr(connectivity.local_models, "status", stopped)

    result = await connectivity.check_all()

    by_id = {c["id"]: c for c in result["checks"]}
    assert by_id["ollama"]["ok"] is False
    assert result["ok"] is False


@pytest.mark.anyio
async def test_result_reused_within_a_few_seconds(monkeypatch):
    calls = {"n": 0}

    async def counting_db(force=False):
        calls["n"] += 1
        return True

    monkeypatch.setattr(connectivity.database, "check_connection", counting_db)

    first = await connectivity.check_all()
    second = await connectivity.check_all()

    assert calls["n"] == 1
    assert second is first


@pytest.mark.anyio
async def test_slow_probe_times_out_and_checks_run_concurrently(monkeypatch):
    monkeypatch.setattr(connectivity, "_TIMEOUT", 0.05)
    monkeypatch.setattr(
        connectivity.secrets, "get_provider_key",
        lambda p: "k" if p in ("openai", "anthropic") else None,
    )

    async def sleepy_probe(provider):
        await asyncio.sleep(5)
        return True, "never"

    monkeypatch.setattr(connectivity.ai, "probe_provider", sleepy_probe)

    loop = asyncio.get_event_loop()
    start = loop.time()
    result = await connectivity.check_all()
    elapsed = loop.time() - start

    assert elapsed < 1.0  # two sleepy probes bounded by one shared timeout window (concurrent)
    for provider in ("openai", "anthropic"):
        check = next(c for c in result["checks"] if c["id"] == provider)
        assert check["ok"] is False and "time" in check["detail"].lower()
