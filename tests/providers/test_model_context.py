"""The context-window table: the numbers Orrery trims history against.

This is not cosmetic metadata. `model_context_window` is the budget `_limit_messages` trims to, so
a number that is too small silently throws away the user's earlier turns and a number that is too
big gets the request rejected by the provider. Both are bugs; only one of them is visible.

litellm's model database is the reason this file exists. It lags new releases by months, and its
miss path is silent: an unknown id fell through to a flat 131,072 (32,768 for local), so a 1M-context
model quietly ran as an eighth of itself. These tests pin the real windows for the models Orrery
actually offers, and pin the ordering rule that keeps a curated number ahead of a stale lookup.

Every figure here comes from the model list the user supplied on 25 August 2026. When a vendor
states a native window and an extended one, the native figure is the one recorded — see the module
docstring for why that asymmetry is deliberate.
"""
import pytest

from backend.providers import model_context


# --- normalisation: the same model, spelled the many ways vendors spell it -------------------------

@pytest.mark.parametrize("model_id, expected", [
    ("openai/gpt-5.6", "gpt56"),
    ("gpt-5.6", "gpt56"),
    ("anthropic/claude-opus-4-8", "claudeopus48"),
    ("anthropic/claude-opus-4.8", "claudeopus48"),      # dot or dash, same model
    ("openrouter/meta-llama/llama-4-scout", "llama4scout"),
    ("ollama/llama4-scout:latest", "llama4scout"),       # ollama tags are not part of the name
    ("ollama/qwen3.8-27b:q4_K_M", "qwen3827b"),
    ("GEMINI/Gemini-3.7-Flash", "gemini37flash"),
])
def test_ids_normalise_to_one_comparable_name(model_id, expected):
    assert model_context.normalize(model_id) == expected


# --- the windows themselves -----------------------------------------------------------------------

@pytest.mark.parametrize("model_id, window", [
    # OpenAI — the 5.x flagships share one window; mini/nano are a quarter of it
    ("openai/gpt-5.6", 1_050_000),
    ("openai/gpt-5.6-terra", 1_050_000),
    ("openai/gpt-5.6-luna", 1_050_000),
    ("openai/gpt-5.5", 1_050_000),
    ("openai/gpt-5.4-pro", 1_050_000),
    ("openai/gpt-5.4-mini", 400_000),
    ("openai/gpt-5.4-nano", 400_000),
    ("openai/gpt-oss-120b", 131_072),

    # Anthropic — Opus 4.8 is the one model whose window differs by surface (see the split test)
    ("anthropic/claude-opus-5", 1_000_000),
    ("anthropic/claude-sonnet-5", 1_000_000),
    ("anthropic/claude-fable-5", 1_000_000),
    ("anthropic/claude-opus-4-8", 500_000),
    ("anthropic/claude-haiku-4-5", 200_000),

    # Google
    ("gemini/gemini-3.7-flash", 1_048_576),
    ("gemini/gemini-3.1-pro-preview", 1_048_576),
    ("gemini/gemini-2.5-flash-lite", 1_048_576),
    ("ollama/gemma4-31b", 262_144),
    ("ollama/gemma4-e2b", 131_072),

    # xAI — 4.6 and 4.5 are HALF of 4.3, which is the trap a version sort would fall into
    ("xai/grok-4.6", 500_000),
    ("xai/grok-4.5", 500_000),
    ("xai/grok-4.3", 1_000_000),
    ("xai/grok-4.20-reasoning", 1_000_000),

    # Meta
    ("openrouter/meta-llama/llama-4-scout", 10_000_000),
    ("openrouter/meta-llama/llama-4-maverick", 1_000_000),

    # The open-weight frontier
    ("deepseek/deepseek-v4-pro", 1_000_000),
    ("deepseek/deepseek-v4-flash", 1_000_000),
    ("moonshot/kimi-k3", 1_048_576),
    ("dashscope/qwen3.8-max", 1_000_000),
    ("dashscope/glm-5.2", 1_000_000),
    ("dashscope/glm-5.3", 1_000_000),
    ("openrouter/minimax/minimax-m3", 1_000_000),

    # Mistral and Cohere both quote 256K as 262,144
    ("mistral/mistral-medium-3.5", 262_144),
    ("mistral/mistral-small-4", 262_144),
    ("mistral/ministral-3-8b", 262_144),
    ("openrouter/cohere/command-a", 262_144),
    ("openrouter/cohere/command-r", 131_072),

    ("openrouter/ox-alpha", 1_048_576),
])
def test_known_models_report_their_real_window(model_id, window):
    assert model_context.lookup(model_id) == window


def test_a_longer_prefix_wins_over_a_shorter_one():
    """`gpt-5.4-mini` matches both `gpt54` and `gpt54mini`. The specific entry has to win, or every
    small model inherits its flagship's window and the request is rejected at 400K."""
    assert model_context.lookup("openai/gpt-5.4") == 1_050_000
    assert model_context.lookup("openai/gpt-5.4-mini") == 400_000
    assert model_context.lookup("ollama/gemma4-31b") == 262_144
    assert model_context.lookup("ollama/gemma4-e4b") == 131_072


def test_an_unknown_model_is_a_miss_not_a_guess():
    """A miss must be None so the caller can try litellm. Inventing a number here would be worse
    than the fallback it replaced."""
    assert model_context.lookup("openai/some-unreleased-thing") is None
    assert model_context.lookup("") is None
    assert model_context.lookup(None) is None


def test_no_entry_shadows_another():
    """A key that is a prefix of another key is fine (longest wins), but two keys that normalise to
    the same string would make one of them unreachable and the shadowing would be silent."""
    keys = list(model_context.WINDOWS)
    assert len(keys) == len(set(keys))
    for key in keys:
        assert key == model_context.normalize(key), f"{key!r} is not in normalised form"
