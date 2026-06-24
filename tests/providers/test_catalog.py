from backend.providers import catalog
from backend.security import secrets


def test_custom_model_id_format():
    assert catalog.custom_model_id("abc") == "custom/abc"


def test_custom_key_uses_keychain_namespace(fake_keyring):
    # the raw key lives in the keychain under a custom:<id> namespace, never in the DB
    secrets.set_provider_key("custom:xyz", "sk-secret-CUSTOM")
    assert catalog.custom_model_key("xyz") == "sk-secret-CUSTOM"
    stored = list(fake_keyring.values())
    assert "sk-secret-CUSTOM" in stored
    # and it is reachable only via the namespaced name
    assert catalog.custom_model_key("other") is None
