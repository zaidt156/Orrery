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
    ids = {m["id"] for m in out}

    # the offline list is the known-good set, not whatever the last successful call returned
    assert ids == {f"deepseek/{name}" for name in ai._DEEPSEEK_FALLBACK}
    assert "deepseek/deepseek-chat" in ids


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


def test_openrouter_keeps_the_open_weight_frontier_families():
    """OpenRouter is the only route Orrery has to these, so a family missing from this tuple is
    a family the user simply cannot reach — silently, since nothing reports a filtered model."""
    assert "z-ai/" in ai._OPENROUTER_KEEP        # GLM
    assert "moonshotai/" in ai._OPENROUTER_KEEP  # Kimi
    assert "minimax/" in ai._OPENROUTER_KEEP     # MiniMax M3 has no direct provider here
    assert "meta-llama/" in ai._OPENROUTER_KEEP  # Llama 4


@pytest.mark.anyio
async def test_moonshot_models_carry_the_litellm_prefix(monkeypatch):
    seen = _stub(monkeypatch, {"data": [{"id": "kimi-k2-thinking"}, {"id": "kimi-k2-turbo"}]})

    out = await ai._fetch_moonshot("secret")

    assert "moonshot" in seen["url"]
    assert {m["id"] for m in out} == {"moonshot/kimi-k2-thinking", "moonshot/kimi-k2-turbo"}
    assert all(m["provider"] == "moonshot" for m in out)


def test_moonshot_curation_prefers_thinking_and_drops_vision():
    items = [
        {"id": f"moonshot/{m}", "label": m, "provider": "moonshot"}
        for m in ("kimi-k2-thinking", "kimi-k2-turbo", "kimi-k1-vision", "moonshot-v1-8k")
    ]

    labels = [m["label"] for m in ai._curate_moonshot(items)]

    assert "kimi-k2-thinking" in labels
    assert all("vision" not in label for label in labels)
    assert len(labels) <= 4


def test_moonshot_is_registered_everywhere_a_provider_must_be():
    assert "moonshot" in ai.PROVIDERS
    assert "moonshot" in ai._KEYED
    assert "moonshot" in ai._DISCOVERY
    assert ai.model_provider("moonshot/kimi-k2-thinking") == "moonshot"


def test_the_deepseek_offline_fallback_names_the_current_generation():
    """The fallback only runs when DeepSeek's own list is unreachable, so it should not strand a
    user on models from two generations ago."""
    assert "deepseek-v4-pro" in ai._DEEPSEEK_FALLBACK
    assert "deepseek-chat" in ai._DEEPSEEK_FALLBACK


# --- version ranking, and the catalogue the user actually sees --------------------------------------

def test_a_two_digit_minor_version_does_not_outrank_a_larger_one():
    """`_ver` scored the minor as hundredths, so "4.20" read as 4.20 and "4.6" as 4.06 — and Grok
    4.20 outranked Grok 4.6, which is the newer model. Version strings are decimals: 4.20 is 4.2."""
    assert ai._ver("grok-4.6") > ai._ver("grok-4.20-reasoning")
    assert ai._ver("grok-4.5") > ai._ver("grok-4.20-multi-agent")
    assert ai._ver("grok-4.3") > ai._ver("grok-4.20-reasoning")
    # and the orderings that were already right stay right
    assert ai._ver("gpt-5.6") > ai._ver("gpt-5.5") > ai._ver("gpt-5.4")
    assert ai._ver("gemini-3.7-flash") > ai._ver("gemini-3.1-pro")
    assert ai._ver("claude-opus-5") > ai._ver("claude-opus-4-8") > ai._ver("claude-opus-4-6")
    assert ai._ver("kimi-k3") > ai._ver("kimi-k2.7-code")


def test_xai_curation_offers_the_current_flagship_first():
    """With the ranking fixed, the four slots go to the newest four rather than to two variants of
    an older release."""
    items = [
        {"id": f"xai/{m}", "label": m, "provider": "xai"}
        for m in ("grok-4.6", "grok-4.5", "grok-4.3",
                  "grok-4.20-reasoning", "grok-4.20-multi-agent")
    ]

    labels = [p["label"] for p in ai._curate_xai(items)]

    assert labels[0] == "grok-4.6"
    assert "grok-4.3" in labels, "the 1M-context Grok was pushed out by two older variants"


@pytest.mark.anyio
async def test_the_settings_catalogue_is_not_capped_to_four_per_provider(monkeypatch):
    """Curation exists to decide what gets switched ON automatically when a key is first added.
    It was also gating what the user is allowed to turn on at all, so nine current OpenAI models
    became four and the rest were unreachable — no setting, anywhere, could get them back.
    """
    from backend.providers import catalog

    openai_models = [
        {"id": f"openai/{m}", "label": m, "provider": "openai"}
        for m in ("gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.5-pro",
                  "gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano")
    ]

    async def fetch(_key):
        return openai_models

    monkeypatch.setattr(ai, "_KEYED", ("openai",))
    monkeypatch.setattr(ai, "_DISCOVERY", {"openai": (fetch, ai._curate_openai)})
    monkeypatch.setattr(ai.secrets, "get_provider_key", lambda _p: "sk-test")
    monkeypatch.setattr(ai, "_cli_plan_models", list)

    async def no_ollama():
        return []

    monkeypatch.setattr(ai, "_fetch_ollama", no_ollama)
    ai.clear_model_cache()

    async def no_customs():
        return []

    async def no_active():
        return set()

    async def refreshed(_models):
        return None

    monkeypatch.setattr(catalog, "list_custom_models", no_customs)
    monkeypatch.setattr(catalog, "active_ids", no_active)
    monkeypatch.setattr(catalog, "refresh_active_metadata", refreshed)

    offered = {m["label"] for m in await ai.list_catalog()}

    assert offered == {m["label"] for m in openai_models}, "models the user cannot reach at all"


@pytest.mark.anyio
async def test_auto_activation_still_picks_only_a_few(monkeypatch):
    """The other half: turning a key on must not switch on everything the provider serves."""
    openai_models = [
        {"id": f"openai/{m}", "label": m, "provider": "openai"}
        for m in ("gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4-mini", "o4-mini")
    ]

    async def fetch(_key):
        return openai_models

    monkeypatch.setattr(ai, "_DISCOVERY", {"openai": (fetch, ai._curate_openai)})
    monkeypatch.setattr(ai.secrets, "get_provider_key", lambda _p: "sk-test")
    ai.clear_model_cache()

    assert len(await ai.provider_models("openai")) <= 4
