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
