"""Sandbox readiness caching — the per-turn `docker image inspect` should not re-run every call."""
from backend.features import sandbox


def _reset():
    sandbox._ready_cache = None


def test_image_ready_caches_the_probe(monkeypatch):
    _reset()
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return True

    monkeypatch.setattr(sandbox, "_probe_image_ready", fake_probe)

    assert sandbox.image_ready() is True
    assert sandbox.image_ready() is True
    assert sandbox.image_ready() is True
    assert calls["n"] == 1  # probed once, then served from cache


def test_image_ready_refresh_forces_reprobe(monkeypatch):
    _reset()
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return True

    monkeypatch.setattr(sandbox, "_probe_image_ready", fake_probe)

    assert sandbox.image_ready() is True
    assert sandbox.image_ready(refresh=True) is True
    assert calls["n"] == 2  # refresh bypasses the cache


def test_image_ready_negative_result_is_cached_too(monkeypatch):
    _reset()
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return False

    monkeypatch.setattr(sandbox, "_probe_image_ready", fake_probe)

    assert sandbox.image_ready() is False
    assert sandbox.image_ready() is False
    assert calls["n"] == 1  # a missing image is also cached (re-checked sooner via a shorter TTL)
