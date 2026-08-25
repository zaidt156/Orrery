import pytest

from backend.providers import catalog
from backend.security import secrets


def test_custom_model_id_format():
    assert catalog.custom_model_id("abc") == "custom/abc"


@pytest.mark.anyio
async def test_add_custom_model_rejects_empty_label():
    with pytest.raises(ValueError):
        await catalog.add_custom_model("", "https://api.example.com/v1", "gpt-x", None)


@pytest.mark.anyio
async def test_add_custom_model_rejects_bad_model_name():
    with pytest.raises(ValueError):
        await catalog.add_custom_model("My model", "https://api.example.com/v1", "bad model name!", None)


@pytest.mark.anyio
async def test_add_custom_model_rejects_unsafe_url():
    # netguard raises UnsafeUrlError (a ValueError) before anything is stored
    with pytest.raises(ValueError):
        await catalog.add_custom_model("Meta", "http://169.254.169.254/v1", "gpt-x", None)


def test_custom_key_uses_keychain_namespace(fake_keyring):
    # the raw key lives in the keychain under a custom:<id> namespace, never in the DB
    secrets.set_provider_key("custom:xyz", "sk-secret-CUSTOM")
    assert catalog.custom_model_key("xyz") == "sk-secret-CUSTOM"
    stored = list(fake_keyring.values())
    assert "sk-secret-CUSTOM" in stored
    # and it is reachable only via the namespaced name
    assert catalog.custom_model_key("other") is None


# --- plan variants must offer the current flagship ----------------------------------------------
#
# The subscription/plan path does not fetch models live: it reads a curated list from
# `model_manifest.json` (with baked-in defaults behind it). That list drifts silently as providers
# ship new flagships, and a user on a Claude or ChatGPT plan simply never sees the new model.

def test_claude_plan_offers_the_current_opus():
    """Opus 5 is the current Opus. The plan list pointed its opus slot at 4.8."""
    from backend.providers import manifest

    flags = {flag for _id, _label, flag in manifest.variants("claude_plan") if flag}
    opus = {f for f in flags if "opus" in f}

    assert any(f.startswith("claude-opus-5") for f in opus), (
        f"no Opus 5 among the Claude plan variants: {sorted(opus)}"
    )


def test_claude_plan_opus_slot_is_not_a_superseded_version():
    """The generic `opus` and `opus-1m` slots should mean 'the current Opus', not a pinned old one."""
    from backend.providers import manifest

    by_id = {vid: flag for vid, _label, flag in manifest.variants("claude_plan")}

    assert by_id.get("claude_plan/opus") == "claude-opus-5"
    assert by_id.get("claude_plan/opus-1m") == "claude-opus-5[1m]"


def test_every_claude_plan_label_matches_its_model():
    """A label naming one version while the flag pins another is how this drifted unnoticed."""
    from backend.providers import manifest

    mismatched = []
    for _vid, label, flag in manifest.variants("claude_plan"):
        if not flag:
            continue
        base = flag.split("[", 1)[0]          # claude-opus-5[1m] -> claude-opus-5
        family = base.removeprefix("claude-")  # opus-5, sonnet-5, haiku-4-5, fable-5
        tier, _, version = family.partition("-")
        spoken = version.replace("-", ".")     # 4-5 -> 4.5
        assert tier in label.lower(), f"{label!r} does not name its tier {tier!r}"
        if spoken and spoken not in label:
            mismatched.append((label, flag))

    assert not mismatched, f"labels naming a different version than they pin: {mismatched}"
