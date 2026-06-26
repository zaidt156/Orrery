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
