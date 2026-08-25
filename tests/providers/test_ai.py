import pytest

from backend.providers import accounts, ai, catalog


def test_model_provider_mapping():
    assert ai.model_provider("openai/gpt-5.5") == "openai"
    assert ai.model_provider("anthropic/claude-opus-4-8") == "anthropic"
    assert ai.model_provider("gemini/gemini-2.5-pro") == "google"
    assert ai.model_provider("ollama/llama3") == "ollama"
    assert ai.model_provider("claude_plan/default") == "claude_plan"
    assert ai.model_provider("gpt-4o") == "openai"
    assert ai.model_provider("claude-x") == "anthropic"


def test_model_provider_custom_and_new_prefixes():
    assert ai.model_provider("custom/abc123") == "custom"
    assert ai.model_provider("mistral/mistral-large-latest") == "mistral"
    assert ai.model_provider("deepseek/deepseek-reasoner") == "deepseek"


def test_claude_plan_single_entry_reports_full_1m_window():
    # 1M-capable plan models expose the whole window from one entry; Haiku / the generic route don't
    assert ai.model_context_window("claude_plan/opus") == 1_000_000
    assert ai.model_context_window("claude_plan/sonnet") == 1_000_000
    assert ai.model_context_window("claude_plan/fable") == 1_000_000
    assert ai.model_context_window("claude_plan/haiku") == 200_000
    assert ai.model_context_window("claude_plan/default") == 200_000


def test_plan_long_context_model_switches_on_large_window():
    # window > 200K → run the "[1m]" sibling (long-context CLI mode); at/under 200K stays standard
    assert ai.plan_long_context_model("claude_plan/opus", 1_000_000) == "claude_plan/opus-1m"
    assert ai.plan_long_context_model("claude_plan/opus", 262_144) == "claude_plan/opus-1m"
    assert ai.plan_long_context_model("claude_plan/opus", 200_000) == "claude_plan/opus"
    assert ai.plan_long_context_model("claude_plan/sonnet", 500_000) == "claude_plan/sonnet-1m"
    # no 1M sibling, non-plan model, already-1m, and missing window are all no-ops
    assert ai.plan_long_context_model("claude_plan/haiku", 1_000_000) == "claude_plan/haiku"
    assert ai.plan_long_context_model("anthropic/claude-opus-4-8", 1_000_000) == "anthropic/claude-opus-4-8"
    assert ai.plan_long_context_model("claude_plan/opus-1m", 1_000_000) == "claude_plan/opus-1m"
    assert ai.plan_long_context_model("claude_plan/opus", None) == "claude_plan/opus"


def test_claude_plan_picker_hides_1m_variants(monkeypatch):
    # the "-1m" models are internal now (reached via the slider), not separate menu entries
    from backend.providers import accounts
    monkeypatch.setattr(accounts, "_stored_claude_plan", lambda: True)
    monkeypatch.setattr(accounts, "claude_plan_mode_status", lambda: {"configured": True})
    ids = [m["id"] for m in accounts.claude_plan_models()]
    assert "claude_plan/opus" in ids
    assert not any(i.endswith("-1m") for i in ids)


def test_model_provider_cli_plans():
    assert ai.model_provider("chatgpt_plan/default") == "chatgpt_plan"
    assert ai.model_provider("gemini_plan/default") == "gemini_plan"


def test_curate_mistral_keeps_chat_drops_noise():
    items = [
        {"id": f"mistral/{m}", "label": m, "provider": "mistral"}
        for m in [
            "mistral-large-latest", "magistral-medium-latest", "ministral-8b-latest",
            "mistral-embed", "mistral-moderation-latest", "mistral-large-2411",
        ]
    ]
    cur = ai._curate_mistral(items)
    labels = [c["label"] for c in cur]
    assert len(cur) <= 4
    assert "mistral-large-latest" in labels
    assert any("magistral" in l for l in labels)  # reasoning family included
    assert "mistral-embed" not in labels and "mistral-moderation-latest" not in labels
    assert "mistral-large-2411" not in labels  # dated snapshot dropped in favour of -latest


def test_clean_openai_filters_noise():
    ids = [
        "gpt-5.5", "gpt-4o", "o4-mini",
        "gpt-4o-2024-08-06", "gpt-4o-mini-2024-07-18",  # dated snapshots
        "gpt-3.5-turbo", "text-embedding-3-small", "whisper-1",  # legacy / non-chat
    ]
    out = ai._clean_openai(ids)
    assert {"gpt-5.5", "gpt-4o", "o4-mini"} <= set(out)
    assert "gpt-4o-2024-08-06" not in out
    assert "gpt-3.5-turbo" not in out
    assert "text-embedding-3-small" not in out and "whisper-1" not in out


def test_curate_openai_max4_with_reasoning():
    items = [
        {"id": f"openai/{label}", "label": label, "provider": "openai"}
        for label in ["gpt-5.5", "gpt-5.5-pro", "gpt-5.4-mini", "gpt-5.4", "o4-mini", "o3", "gpt-4o"]
    ]
    cur = ai._curate_openai(items)
    labels = [c["label"] for c in cur]
    assert len(cur) <= 4
    assert "gpt-5.5" in labels  # latest flagship
    assert any(l.startswith("o") for l in labels)  # a reasoning model is included
    assert any("mini" in l or "nano" in l for l in labels)  # a fast model is included


def test_curate_anthropic_latest_per_tier():
    items = [
        {"id": f"anthropic/{m}", "label": m, "provider": "anthropic"}
        for m in ["claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5", "claude-fable-5"]
    ]
    ids = [c["id"] for c in ai._curate_anthropic(items)]
    assert "anthropic/claude-opus-4-8" in ids  # latest opus
    assert "anthropic/claude-opus-4-7" not in ids  # not the older one
    assert len(ids) <= 4


def test_sanitize_never_leaks_a_key():
    msg = ai._sanitize(Exception("Incorrect API key provided: sk-proj-TOPSECRET12345. Check it."))
    assert "TOPSECRET12345" not in msg
    assert "sk-proj" not in msg


def test_sanitize_scrubs_google_style_key():
    # a non-auth-classified error that still embeds a Google key must be scrubbed in the fallback
    msg = ai._sanitize(ValueError("upstream 500 at request with AIzaSyTOPSECRETkey9999 attached"))
    assert "AIzaSyTOPSECRETkey9999" not in msg


def test_sanitize_quota_is_friendly():
    msg = ai._sanitize(Exception("RateLimitError - you exceeded your current quota, check billing"))
    assert "credit" in msg.lower()


def test_provider_limit_normalization_covers_api_429_but_not_context_errors():
    limited = ai._provider_limit_error("openai/gpt-5.5", Exception("HTTP 429: too many requests"))
    assert isinstance(limited, ai.ProviderLimitError)
    assert limited.provider == "openai"
    assert ai._provider_limit_error(
        "openai/gpt-5.5", Exception("maximum context length limit exceeded")
    ) is None


@pytest.mark.anyio
async def test_stream_chat_falls_back_to_enabled_provider_on_plan_limit(monkeypatch):
    calls = []

    async def limited_claude(*_args, **_kwargs):
        calls.append("claude")
        raise accounts.ClaudePlanUnavailable(
            "Claude plan: You've hit your monthly spend limit - raise it in Settings."
        )
        yield  # pragma: no cover - makes this an async generator

    async def working_chatgpt(*_args, **_kwargs):
        calls.append("chatgpt")
        yield "fallback answer"

    async def active_models():
        return [
            {"id": "claude_plan/opus", "label": "Claude Opus", "provider": "claude_plan"},
            {"id": "chatgpt_plan/default", "label": "ChatGPT", "provider": "chatgpt_plan"},
        ]

    monkeypatch.setattr(accounts, "stream_claude_plan", limited_claude)
    monkeypatch.setattr(accounts, "stream_chatgpt_plan", working_chatgpt)
    monkeypatch.setattr(accounts, "chatgpt_plan_mode_status", lambda: {"configured": True, "available": True})
    monkeypatch.setattr(catalog, "list_active", active_models)

    result = [
        delta
        async for delta in ai.stream_chat(
            "claude_plan/opus",
            [{"role": "user", "content": "create a song file"}],
        )
    ]

    assert result == ["fallback answer"]
    assert calls == ["claude", "chatgpt"]


@pytest.mark.anyio
async def test_stream_chat_does_not_fallback_after_any_output(monkeypatch):
    calls = []

    async def partial_claude(*_args, **_kwargs):
        calls.append("claude")
        yield "partial answer"
        raise accounts.ClaudePlanUnavailable("You've hit your session limit - resets at 01:10.")

    async def unexpected_chatgpt(*_args, **_kwargs):
        calls.append("chatgpt")
        yield "duplicate answer"

    async def active_models():
        return [
            {"id": "claude_plan/opus", "label": "Claude Opus", "provider": "claude_plan"},
            {"id": "chatgpt_plan/default", "label": "ChatGPT", "provider": "chatgpt_plan"},
        ]

    monkeypatch.setattr(accounts, "stream_claude_plan", partial_claude)
    monkeypatch.setattr(accounts, "stream_chatgpt_plan", unexpected_chatgpt)
    monkeypatch.setattr(accounts, "chatgpt_plan_mode_status", lambda: {"configured": True, "available": True})
    monkeypatch.setattr(catalog, "list_active", active_models)

    seen = []
    with pytest.raises(ai.ProviderLimitError, match="session limit"):
        async for delta in ai.stream_chat("claude_plan/opus", [{"role": "user", "content": "hello"}]):
            seen.append(delta)

    assert seen == ["partial answer"]
    assert calls == ["claude"]


@pytest.mark.anyio
async def test_stream_chat_preserves_limit_failure_without_available_fallback(monkeypatch):
    async def limited_claude(*_args, **_kwargs):
        raise accounts.ClaudePlanUnavailable("You've hit your monthly spend limit.")
        yield

    async def active_models():
        return [
            {"id": "claude_plan/opus", "label": "Claude Opus", "provider": "claude_plan"},
            {"id": "openai/gpt-5.5", "label": "GPT", "provider": "openai"},
        ]

    monkeypatch.setattr(accounts, "stream_claude_plan", limited_claude)
    monkeypatch.setattr(catalog, "list_active", active_models)
    monkeypatch.setattr(ai.secrets, "get_provider_key", lambda _provider: None)

    with pytest.raises(ai.ProviderLimitError, match="monthly spend limit"):
        async for _ in ai.stream_chat("claude_plan/opus", [{"role": "user", "content": "hello"}]):
            pass


@pytest.mark.anyio
async def test_stream_chat_retries_only_one_fallback_provider(monkeypatch):
    calls = []

    async def limited_claude(*_args, **_kwargs):
        calls.append("claude")
        raise accounts.ClaudePlanUnavailable("You've hit your monthly spend limit.")
        yield

    async def limited_chatgpt(*_args, **_kwargs):
        calls.append("chatgpt")
        raise accounts.CliRouteUnavailable("Rate limit reached by ChatGPT plan.")
        yield

    async def unexpected_gemini(*_args, **_kwargs):
        calls.append("gemini")
        yield "third route"

    async def active_models():
        return [
            {"id": "claude_plan/opus", "label": "Claude Opus", "provider": "claude_plan"},
            {"id": "chatgpt_plan/default", "label": "ChatGPT", "provider": "chatgpt_plan"},
            {"id": "gemini_plan/default", "label": "Gemini", "provider": "gemini_plan"},
        ]

    monkeypatch.setattr(accounts, "stream_claude_plan", limited_claude)
    monkeypatch.setattr(accounts, "stream_chatgpt_plan", limited_chatgpt)
    monkeypatch.setattr(accounts, "stream_gemini_plan", unexpected_gemini)
    monkeypatch.setattr(accounts, "chatgpt_plan_mode_status", lambda: {"configured": True, "available": True})
    monkeypatch.setattr(accounts, "gemini_plan_mode_status", lambda: {"configured": True, "available": True})
    monkeypatch.setattr(catalog, "list_active", active_models)

    with pytest.raises(ai.ProviderLimitError, match="Rate limit"):
        async for _ in ai.stream_chat("claude_plan/opus", [{"role": "user", "content": "hello"}]):
            pass

    assert calls == ["claude", "chatgpt"]


@pytest.mark.anyio
async def test_stream_chat_does_not_cross_provider_for_media_input(monkeypatch):
    calls = []

    async def limited_claude(*_args, **_kwargs):
        calls.append("claude")
        raise accounts.ClaudePlanUnavailable("You've hit your monthly spend limit.")
        yield

    async def unexpected_chatgpt(*_args, **_kwargs):
        calls.append("chatgpt")
        yield "fallback"

    async def active_models():
        return [
            {"id": "claude_plan/opus", "label": "Claude Opus", "provider": "claude_plan"},
            {"id": "chatgpt_plan/default", "label": "ChatGPT", "provider": "chatgpt_plan"},
        ]

    monkeypatch.setattr(accounts, "stream_claude_plan", limited_claude)
    monkeypatch.setattr(accounts, "stream_chatgpt_plan", unexpected_chatgpt)
    monkeypatch.setattr(accounts, "chatgpt_plan_mode_status", lambda: {"configured": True, "available": True})
    monkeypatch.setattr(catalog, "list_active", active_models)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }]

    with pytest.raises(ai.ProviderLimitError, match="monthly spend limit"):
        async for _ in ai.stream_chat("claude_plan/opus", messages):
            pass

    assert calls == ["claude"]


@pytest.mark.anyio
async def test_stream_chat_skips_fallback_that_cannot_fit_the_input(monkeypatch):
    calls = []

    async def limited_claude(*_args, **_kwargs):
        calls.append("claude")
        raise accounts.ClaudePlanUnavailable("You've hit your monthly spend limit.")
        yield

    async def undersized_chatgpt(*_args, **_kwargs):
        calls.append("chatgpt")
        yield "truncated fallback"

    async def active_models():
        return [
            {"id": "claude_plan/opus", "label": "Claude Opus", "provider": "claude_plan"},
            {"id": "chatgpt_plan/default", "label": "ChatGPT", "provider": "chatgpt_plan"},
        ]

    monkeypatch.setattr(accounts, "stream_claude_plan", limited_claude)
    monkeypatch.setattr(accounts, "stream_chatgpt_plan", undersized_chatgpt)
    monkeypatch.setattr(accounts, "chatgpt_plan_mode_status", lambda: {"configured": True, "available": True})
    monkeypatch.setattr(catalog, "list_active", active_models)
    monkeypatch.setattr(ai, "model_context_window", lambda _model: 1_024)

    with pytest.raises(ai.ProviderLimitError, match="monthly spend limit"):
        async for _ in ai.stream_chat("claude_plan/opus", [{"role": "user", "content": "hello"}]):
            pass

    assert calls == ["claude"]


# --- context windows: the number history is trimmed against --------------------------------------
#
# `model_context_window` is not a label. It is the budget `_limit_messages` cuts the conversation
# down to, so every wrong number here quietly costs the user context or loudly costs them the
# request. These pin the failure modes that were actually shipping.

class _StaleLitellm:
    """litellm as it really behaves for a model newer than its database: a miss, not an error."""

    def get_model_info(self, model_id):
        raise Exception(f"This model isn't mapped yet: {model_id}")


def test_a_known_models_window_beats_a_stale_litellm_lookup(monkeypatch):
    """These all reported 131,072 before the table — Gemini 3.7 Flash ran as an eighth of itself,
    and nothing in the app said so."""
    monkeypatch.setattr(ai, "_load_litellm", _StaleLitellm)

    assert ai.model_context_window("gemini/gemini-3.7-flash") == 1_048_576
    assert ai.model_context_window("moonshot/kimi-k3") == 1_048_576
    assert ai.model_context_window("deepseek/deepseek-v4-pro") == 1_000_000
    assert ai.model_context_window("openai/gpt-5.6") == 1_050_000
    assert ai.model_context_window("openai/gpt-5.4-mini") == 400_000


def test_grok_4_6_is_half_of_grok_4_3(monkeypatch):
    """Newest is not longest. Any scheme that read the window off a version number gets this
    backwards, and overstating it is the failure the provider rejects."""
    monkeypatch.setattr(ai, "_load_litellm", _StaleLitellm)

    assert ai.model_context_window("xai/grok-4.6") == 500_000
    assert ai.model_context_window("xai/grok-4.3") == 1_000_000


def test_opus_4_8_is_500k_on_the_api_and_1m_in_claude_code(monkeypatch):
    """The one model whose window depends on the surface it is reached through. Claiming 1M for a
    direct API call turns a silent truncation into a rejected request."""
    monkeypatch.setattr(ai, "_load_litellm", _StaleLitellm)

    assert ai.model_context_window("anthropic/claude-opus-4-8") == 500_000
    assert ai.model_context_window("claude_plan/opus") == 1_000_000


def test_chatgpt_plan_reports_the_window_of_the_model_codex_runs():
    """Pinned per-plan at 272,000, this stayed wrong for every Codex release after it was written —
    plan users were trimmed to a quarter of their context. It now follows the manifest's pin."""
    assert ai.model_context_window("chatgpt_plan/gpt-5.6") == 1_050_000
    assert ai.model_context_window("chatgpt_plan/gpt-5.6-terra") == 1_050_000
    assert ai.model_context_window("chatgpt_plan/gpt-5.5-mini") == 400_000  # its flag pins 5.4-mini
    assert ai.model_context_window("chatgpt_plan/default") == 1_050_000     # auto → the pinned model


def test_an_unknown_model_still_falls_back_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(ai, "_load_litellm", _StaleLitellm)
    assert ai.model_context_window("openai/gpt-9-unannounced") == 131_072


def test_litellm_still_answers_for_anything_the_table_does_not_list(monkeypatch):
    """The table is an override for what litellm gets wrong, not a replacement for it."""
    class Known:
        def get_model_info(self, _model_id):
            return {"max_input_tokens": 199_999}

    monkeypatch.setattr(ai, "_load_litellm", Known)
    assert ai.model_context_window("openai/gpt-4o-fictional") == 199_999


def test_a_local_model_reports_what_ollama_actually_serves(monkeypatch):
    """Every local model reported 32,768 whatever it was. Ollama knows the real number for the
    weights on disk, so ask it rather than assume."""
    monkeypatch.setattr(ai, "_ollama_context", {"qwen3.8-27b:q4_K_M": 262_144})
    assert ai.model_context_window("ollama/qwen3.8-27b:q4_K_M") == 262_144


def test_a_local_model_is_never_given_its_architectures_ceiling(monkeypatch):
    """Llama 4 Scout's 10M is what the architecture permits, not what a laptop serves, and the KV
    cache for a wrong guess comes out of the user's RAM. Unknown stays conservative here."""
    monkeypatch.setattr(ai, "_ollama_context", {})
    monkeypatch.setattr(ai, "_probe_ollama_context", lambda _name: None)
    assert ai.model_context_window("ollama/llama4-scout") == 32_768


def test_ollama_is_told_the_context_size_instead_of_defaulting_to_2048(monkeypatch):
    """Ollama's own default is 2048 tokens and it truncates above that silently — so a local model
    ran at 2K however much history Orrery had assembled, and however large a window the UI offered.
    The request now carries the real size, clamped to what the model serves."""
    monkeypatch.setattr(ai, "_ollama_context", {"llama4-scout": 131_072})

    assert ai._ollama_num_ctx("ollama/llama4-scout", 65_536) == 65_536
    assert ai._ollama_num_ctx("ollama/llama4-scout", 1_000_000) == 131_072  # clamped to what it serves
    assert ai._ollama_num_ctx("ollama/llama4-scout", 512) == 2_048          # never below Ollama's own
    assert ai._ollama_num_ctx("ollama/llama4-scout", None) is None          # nothing chosen → unchanged
