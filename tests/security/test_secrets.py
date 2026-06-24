from backend.security import secrets


def test_provider_key_roundtrip_and_masking():
    raw = "sk-proj-ABCDEFGH1234WXYZ"
    secrets.set_provider_key("openai", raw)
    status = secrets.provider_key_status("openai")
    assert status["configured"] is True
    # The preview must never reveal the full key.
    assert raw not in status["preview"]
    assert "••" in status["preview"]
    # The raw key is only retrievable through the internal getter (used at call time).
    assert secrets.get_provider_key("openai") == raw


def test_status_when_unset():
    assert secrets.provider_key_status("anthropic") == {"configured": False, "preview": None}


def test_clear_key():
    secrets.set_provider_key("openai", "sk-test")
    secrets.clear_provider_key("openai")
    assert secrets.provider_key_status("openai")["configured"] is False


def test_redact_url_masks_password():
    red = secrets.redact_url("postgresql+psycopg://user:secretpw@host:5432/db")
    assert "secretpw" not in red
    assert "****" in red


def test_mask_short_key():
    assert secrets.mask_key("abc") == "••••"
