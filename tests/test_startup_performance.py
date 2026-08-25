"""Regressions for the two defects that made loading a tab take minutes.

Measured before the fix: the first request for the 1.1MB Dashboards chunk took 239s, because
`GET /api/models` imported litellm (~5s of pure CPU) directly on the event loop while the browser
was still fetching chunks; and every content-hashed asset was revalidated on every load at
200-385ms each, because the `Cache-Control` its own docstring promised was never set.
"""
import asyncio

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.providers import ai

TOKEN = "secret-token"


def _client():
    return TestClient(create_app(TOKEN))


def test_model_context_window_is_never_computed_on_the_event_loop(monkeypatch):
    """The litellm import behind this call costs seconds; on the loop it stalls every other
    request. Anything running in a worker thread has no running loop, which is what we assert."""
    ran_on_event_loop = []

    def spy(model_id):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return 128_000  # good: a worker thread, so the loop stayed free
        ran_on_event_loop.append(model_id)
        return 128_000

    async def fake_list():
        return [{"id": "openai/gpt-4o"}, {"id": "anthropic/claude-opus-4"}]

    monkeypatch.setattr(ai, "model_context_window", spy)
    monkeypatch.setattr(ai, "list_available_models", fake_list)

    r = _client().get("/api/models", headers={"X-Orrery-Token": TOKEN})

    assert r.status_code == 200
    assert ran_on_event_loop == [], f"blocked the event loop for: {ran_on_event_loop}"
    assert [m["context_window"] for m in r.json()["models"]] == [128_000, 128_000]


def test_warm_litellm_exists_so_startup_can_pay_the_import_cost():
    """app.py starts this in a background thread at boot; losing it silently moves a multi-second
    import back onto the user's first request."""
    assert callable(ai.warm_litellm)


def test_hashed_assets_are_cached_forever_and_index_html_is_never_cached(tmp_path, monkeypatch):
    import backend.api as api_module

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Orrery</title>", encoding="utf-8")
    (dist / "assets" / "Dashboards-abc123.js").write_text("export const a = 1;", encoding="utf-8")
    monkeypatch.setattr(api_module, "_UI_DIST", dist)

    client = TestClient(create_app(TOKEN))

    asset = client.get("/assets/Dashboards-abc123.js")
    assert asset.status_code == 200
    assert asset.headers["Cache-Control"] == "public, max-age=31536000, immutable"

    index = client.get("/")
    assert index.status_code == 200
    assert "no-store" in index.headers["Cache-Control"]


def test_idle_loop_really_waits_instead_of_spinning(monkeypatch):
    """Regression: main()'s idle loop used to wait on `_ready`, which is already set by the time
    it runs. Waiting on a set Event returns instantly, so the main thread span at full tilt and
    starved the backend thread's event loop through the GIL - every request, static chunks
    included, paid about 530ms for it."""
    import app as orrery_app

    waited = []

    class _CountingEvent:
        def wait(self, timeout=None):
            waited.append(timeout)
            return len(waited) >= 3  # "stopped" on the third wait, so the loop ends

    monkeypatch.setattr(orrery_app, "_stopped", _CountingEvent())
    monkeypatch.setattr(orrery_app, "_boot_error", [])

    # If this ever waits on a set Event again, it never terminates and the suite timeout names it.
    orrery_app._idle_until_stopped(poll=0.01)

    assert waited == [0.01, 0.01, 0.01]


def test_ready_event_is_set_while_running_so_it_can_never_be_the_idle_wait():
    """The property that made the old loop spin: _ready is set once the backend is serving."""
    import app as orrery_app

    assert not orrery_app._stopped.is_set()
    orrery_app._ready.set()
    try:
        assert orrery_app._ready.wait(timeout=5) is True  # returns instantly - never idle on this
    finally:
        orrery_app._ready.clear()


def test_startup_warms_local_context_windows_not_just_litellm(monkeypatch):
    """A chat's window is clamped with `min()`, and a `min()` only narrows. If nothing has asked
    Ollama what a local model serves before the first conversation is created, that conversation is
    pinned to the 32K default for good — so the warm thread has to cover this too, not just the
    import cost."""
    called = []
    monkeypatch.setattr(ai, "warm_litellm", lambda: called.append("litellm"))
    monkeypatch.setattr(ai, "warm_ollama_context", lambda: called.append("ollama"))

    ai.warm_model_metadata()

    assert called == ["litellm", "ollama"]


def test_warming_local_context_windows_is_silent_when_ollama_is_absent(monkeypatch):
    """Not running Ollama is the normal case for most users, not an error to report."""
    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(ai.httpx, "get", refuse)
    ai.warm_ollama_context()  # must not raise
