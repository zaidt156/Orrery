from backend.security import privacy


def test_redact_masks_common_pii():
    text = "Email a@b.com, call 415-555-1234, ip 10.0.0.4, ssn 123-45-6789"
    red = privacy.redact(text)
    assert "a@b.com" not in red and "[email]" in red
    assert "415-555-1234" not in red and "[phone]" in red
    assert "10.0.0.4" not in red and "[ip]" in red
    assert "123-45-6789" not in red and "[ssn]" in red


def test_redact_for_model_local_is_exempt():
    text = "reach me at a@b.com"
    assert privacy.redact_for_model(text, is_local=True) == text  # local model: nothing leaves the machine
    assert "[email]" in privacy.redact_for_model(text, is_local=False)  # cloud model: screened


# --- strict must be materially stronger than basic ------------------------------------------
#
# The two modes ran the same five regexes, while Settings described strict as "Basic redaction plus
# a stronger boundary". A mode that promises more protection and applies none is worse than not
# offering it, because a user picks it precisely when the content is sensitive.

_SECRET_TEXT = "deploy with OPENAI_API_KEY=sk-proj-QZ2h8Lm4Np7Rt5Xv9Wc3Bd6Fg1Jk0Ya and retry"
_IBAN_TEXT = "wire it to GB33BUKB20201555555555 tomorrow"
_ACCOUNT_TEXT = "the account reference is 4471029938475610293 on file"


def test_strict_removes_an_api_key_that_basic_lets_through():
    """A pasted key crossing the cloud boundary is the case strict exists for."""
    basic = privacy.prepare_messages_for_model(
        [{"role": "user", "content": _SECRET_TEXT}], is_local=False, mode="basic")
    strict = privacy.prepare_messages_for_model(
        [{"role": "user", "content": _SECRET_TEXT}], is_local=False, mode="strict")

    assert "sk-proj-QZ2h8Lm4Np7Rt5Xv9Wc3Bd6Fg1Jk0Ya" not in strict[0]["content"]
    assert strict[0]["content"] != basic[0]["content"], "strict must differ from basic"


def test_strict_masks_an_iban():
    out = privacy.prepare_messages_for_model(
        [{"role": "user", "content": _IBAN_TEXT}], is_local=False, mode="strict")

    assert "GB33BUKB20201555555555" not in out[0]["content"]


def test_strict_masks_a_long_account_number_basic_would_miss():
    """Basic's card pattern stops at 16 digits; a 19-digit reference sails past it."""
    basic = privacy.prepare_messages_for_model(
        [{"role": "user", "content": _ACCOUNT_TEXT}], is_local=False, mode="basic")
    strict = privacy.prepare_messages_for_model(
        [{"role": "user", "content": _ACCOUNT_TEXT}], is_local=False, mode="strict")

    assert "4471029938475610293" in basic[0]["content"], "basic is unchanged by this work"
    assert "4471029938475610293" not in strict[0]["content"]


def test_strict_still_does_everything_basic_does():
    """Stronger means a superset, never a different set."""
    text = "mail bob@example.com or call 555-123-4567 from 10.0.0.4"
    basic = privacy.prepare_messages_for_model(
        [{"role": "user", "content": text}], is_local=False, mode="basic")[0]["content"]
    strict = privacy.prepare_messages_for_model(
        [{"role": "user", "content": text}], is_local=False, mode="strict")[0]["content"]

    assert basic == strict, "on ordinary PII the two modes should agree"
    assert "[email]" in strict and "[phone]" in strict and "[ip]" in strict


def test_strict_applies_to_the_system_prompt_too():
    """Project and retrieved context ride in the system prompt; strict has to cover them."""
    _, system = privacy.prepare_request_for_model(
        [], _SECRET_TEXT, is_local=False, mode="strict")

    assert "sk-proj-QZ2h8Lm4Np7Rt5Xv9Wc3Bd6Fg1Jk0Ya" not in system


def test_a_local_model_is_still_exempt_under_strict():
    """Nothing leaves the machine for a local model, so nothing is redacted for one."""
    out = privacy.prepare_messages_for_model(
        [{"role": "user", "content": _SECRET_TEXT}], is_local=True, mode="strict")

    assert out[0]["content"] == _SECRET_TEXT
