"""Security boundary tests: secret masking/redaction and the cloud privacy boundary."""

import pytest

from backend.security import netguard, privacy, secrets


def test_netguard_rejects_credentials_fragment_and_oversize():
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("https://user:pass@api.example.com/v1")
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("https://api.example.com/v1#frag")
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("https://api.example.com/" + "a" * 600)
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("ftp://api.example.com/v1")


def test_netguard_blocks_metadata_ip_allows_loopback():
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("http://169.254.169.254/latest/meta-data")  # link-local metadata
    assert netguard.validate_model_base_url("http://127.0.0.1:11434/v1")  # local model server is fine


def test_mask_key_does_not_expose_full_value():
    key = "sk-test-abcdefghijklmnopqrstuvwxyz"
    masked = secrets.mask_key(key)
    assert key not in masked
    assert masked.startswith("sk-tes")
    assert masked.endswith("wxyz")


def test_redact_secrets_scrubs_keys_tokens_and_url_passwords():
    out = secrets.redact_secrets(
        "key sk-abcdefgh12345, AIzaSyABCDEFGH123, Bearer abcdefgh.tok, "
        "postgres://u:p4ss@h:5432/db, https://x/v1?api_key=zzzzzzzz"
    )
    assert "sk-abcdefgh12345" not in out
    assert "AIzaSyABCDEFGH123" not in out
    assert "p4ss" not in out
    assert "api_key=zzzzzzzz" not in out
    assert "[redacted]" in out


def test_secret_name_validation_rejects_bad_names():
    with pytest.raises(ValueError):
        secrets.get_secret("bad name!")
    with pytest.raises(ValueError):
        secrets.set_secret("nope/slash", "x")


def test_redacts_email_for_cloud_but_not_local():
    assert privacy.redact_for_model("email me at a@example.com", is_local=False) == "email me at [email]"
    text = "email me at a@example.com"
    assert privacy.redact_for_model(text, is_local=True) == text


def test_privacy_boundary_masks_cloud_messages_only():
    msgs = [{"role": "user", "content": "card 4111 1111 1111 1111 and a@b.com"}]
    # local: untouched
    assert privacy.prepare_messages_for_model(msgs, is_local=True) == msgs
    # off: untouched
    assert privacy.prepare_messages_for_model(msgs, is_local=False, mode="off") == msgs
    # basic: masked
    out = privacy.prepare_messages_for_model(msgs, is_local=False, mode="basic")
    assert "a@b.com" not in out[0]["content"]
    assert "[email]" in out[0]["content"]


def test_privacy_boundary_handles_multimodal_blocks():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "mail a@b.com"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}]
    out = privacy.prepare_messages_for_model(msgs, is_local=False, mode="basic")
    assert out[0]["content"][0]["text"] == "mail [email]"
    assert out[0]["content"][1] == msgs[0]["content"][1]  # non-text block untouched


def test_privacy_boundary_redacts_system_prompt_context_too():
    messages = [{"role": "user", "content": "hello from user@example.com"}]
    system_prompt = "# TRUSTED CONTEXT\nProject owner: owner@example.com"

    prepared, prepared_system = privacy.prepare_request_for_model(
        messages, system_prompt, is_local=False, mode="basic"
    )

    assert prepared[0]["content"] == "hello from [email]"
    assert prepared_system == "# TRUSTED CONTEXT\nProject owner: [email]"


def test_privacy_boundary_honors_off_for_every_prompt_layer():
    messages = [{"role": "user", "content": "hello from user@example.com"}]
    system_prompt = "# TRUSTED CONTEXT\nProject owner: owner@example.com"

    prepared, prepared_system = privacy.prepare_request_for_model(
        messages, system_prompt, is_local=False, mode="off"
    )

    assert prepared is messages
    assert prepared_system is system_prompt
