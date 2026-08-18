"""Grok, Qwen/GLM, and a DeepSeek list that is no longer frozen in place.

Every model id here is routed by litellm's prefix for that provider, so the prefixes are asserted
rather than assumed - a wrong prefix is a request that fails at the provider, not at import.
"""
import httpx
import pytest

from backend.providers import ai


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _stub(monkeypatch, payload, expect_host=None):
    """Answer any models-list GET with `payload`, and record the URL that was called."""
    seen = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            seen["url"] = url
            seen["headers"] = headers or {}
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return seen


@pytest.mark.anyio
async def test_xai_models_carry_the_litellm_prefix(monkeypatch):
    seen = _stub(monkeypatch, {"data": [{"id": "grok-4.6"}, {"id": "grok-3-mini"}]})

    out = await ai._fetch_xai("secret")

    assert seen["url"].startswith("https://api.x.ai/")
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert {m["id"] for m in out} == {"xai/grok-4.6", "xai/grok-3-mini"}
    assert all(m["provider"] == "xai" for m in out)


@pytest.mark.anyio
async def test_dashscope_models_carry_the_litellm_prefix(monkeypatch):
    seen = _stub(monkeypatch, {"data": [{"id": "qwen-max"}, {"id": "glm-5.2"}]})

    out = await ai._fetch_dashscope("secret")

    assert "dashscope" in seen["url"]
    assert {m["id"] for m in out} == {"dashscope/qwen-max", "dashscope/glm-5.2"}
    assert all(m["provider"] == "dashscope" for m in out)


def test_xai_curation_prefers_reasoning_and_caps_the_list():
    items = [
        {"id": f"xai/{m}", "label": m, "provider": "xai"}
        for m in ("grok-4.6", "grok-4.5", "grok-4-1-fast-reasoning",
                  "grok-4-1-fast-non-reasoning", "grok-3", "grok-2-vision")
    ]

    picked = ai._curate_xai(items)

    assert len(picked) <= 4
    assert "grok-4.6" in [p["label"] for p in picked]
    assert all("vision" not in p["label"] for p in picked)


def test_dashscope_curation_keeps_a_glm_and_a_qwen():
    items = [
        {"id": f"dashscope/{m}", "label": m, "provider": "dashscope"}
        for m in ("qwen-max", "qwen-turbo", "qwen-coder", "glm-5.2", "qwen-plus")
    ]

    labels = [p["label"] for p in ai._curate_dashscope(items)]

    assert "qwen-max" in labels
    assert "glm-5.2" in labels
    assert len(labels) <= 4


@pytest.mark.anyio
async def test_deepseek_now_asks_the_provider(monkeypatch):
    _stub(monkeypatch, {"data": [{"id": "deepseek-chat"}, {"id": "deepseek-v4-pro"},
                                 {"id": "deepseek-reasoner"}]})

    out = await ai._fetch_deepseek("secret")
    ids = {m["id"] for m in out}

    assert "deepseek/deepseek-v4-pro" in ids, "a model shipped after the old hard-coded pair"
    assert "deepseek/deepseek-chat" in ids
    reasoner = next(m for m in out if m["id"].endswith("deepseek-reasoner"))
    assert "reasoning" in reasoner["label"]


@pytest.mark.anyio
async def test_deepseek_falls_back_to_known_models_when_the_api_is_unreachable(monkeypatch):
    class _Boom:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)

    out = await ai._fetch_deepseek("secret")

    assert {m["id"] for m in out} == {"deepseek/deepseek-chat", "deepseek/deepseek-reasoner"}


def test_new_providers_are_registered_everywhere_they_must_be():
    """A provider missing from any one of these is a model the user can key but never route."""
    for name in ("xai", "dashscope"):
        assert name in ai.PROVIDERS, f"{name} missing from the provider list"
        assert name in ai._KEYED, f"{name} would never be discovered"
        assert name in ai._DISCOVERY, f"{name} has no fetch/curate pair"
        assert ai._PREFIX_TO_PROVIDER[name] == name, f"{name} would not map back from a model id"


def test_provider_of_a_model_id_resolves_for_the_new_prefixes():
    assert ai.model_provider("xai/grok-4.6") == "xai"
    assert ai.model_provider("dashscope/qwen-max") == "dashscope"


def test_openrouter_keeps_glm_and_kimi_families():
    assert "z-ai/" in ai._OPENROUTER_KEEP   # GLM
    assert "moonshotai/" in ai._OPENROUTER_KEEP
