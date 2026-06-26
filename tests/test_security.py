"""Security boundary tests: secret masking/redaction and the cloud privacy boundary."""

import pytest

from backend.security import privacy, secrets


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
