from backend.providers import ai


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
