from __future__ import annotations

import re

# Lightweight PII screening for content bound for a CLOUD model (security.md §10).
# A regex baseline for the common cases; a fuller detector (e.g. Presidio) is a
# future upgrade. Local models are exempt — nothing leaves the machine for them.
_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[card]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b"), "[phone]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
]


def redact(text: str) -> str:
    """Mask common personal data (emails, cards, SSNs, phones, IPs)."""
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_for_model(text: str, is_local: bool) -> str:
    """Redact before a cloud model; leave untouched for a local model."""
    return text if is_local else redact(text)


# Strict-only patterns. These are deliberately more aggressive than the baseline and will
# sometimes mask something harmless — a long order number, an identifier that happens to look like
# an IBAN. That trade is the whole point of the mode: a user selects strict when the content is
# sensitive enough that a false positive costs less than a leak.
_STRICT_PATTERNS = [
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "[iban]"),
    # The baseline card rule stops at 16 digits and is anchored, so a longer account or reference
    # number passes straight through it.
    (re.compile(r"\b\d{17,}\b"), "[number]"),
]


def redact_strict(text: str) -> str:
    """Everything `redact` masks, plus credential-shaped values and long financial identifiers.

    Strict is a superset of basic by construction: it runs `redact` first and only ever adds. The
    secret scrubber is the one already trusted on the web-search boundary, so a key pasted into a
    chat is treated the same way whichever boundary it is about to cross.
    """
    from backend.security.secrets import redact_secrets

    value = redact_secrets(redact(text))
    for pattern, repl in _STRICT_PATTERNS:
        value = pattern.sub(repl, value)
    return value


# Privacy modes for the cloud boundary: "off" sends text as-is, "basic" applies the regex
# redaction above, and "strict" adds credential and financial-identifier scrubbing on top.
PRIVACY_MODES = ("off", "basic", "strict")


def _redactor_for(mode: str):
    """The one place a mode becomes a function. Anything not basic/strict never gets here."""
    return redact_strict if mode == "strict" else redact


def prepare_messages_for_model(messages: list[dict], *, is_local: bool, mode: str = "basic") -> list[dict]:
    """The single privacy boundary every cloud-bound call passes through. Local models and
    mode 'off' are untouched; otherwise PII is masked in each message's text content."""
    if is_local or mode not in ("basic", "strict"):
        return messages
    scrub = _redactor_for(mode)
    prepared: list[dict] = []
    for message in messages:
        content = message.get("content")
        copied = dict(message)
        if isinstance(content, str):
            copied["content"] = scrub(content)
        elif isinstance(content, list):
            blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    block = {**block, "text": scrub(block.get("text", ""))}
                blocks.append(block)
            copied["content"] = blocks
        prepared.append(copied)
    return prepared


def prepare_request_for_model(
    messages: list[dict],
    system_prompt: str | None,
    *,
    is_local: bool,
    mode: str = "basic",
) -> tuple[list[dict], str | None]:
    """Apply one privacy policy to every text layer crossing the provider boundary.

    Trusted project context and untrusted RAG context are both assembled into the system prompt,
    so redacting only message bodies leaves those layers exposed. Keeping this operation at the
    final provider boundary also makes the user's off/basic/strict selection consistent.
    """
    if is_local or mode not in ("basic", "strict"):
        return messages, system_prompt
    scrub = _redactor_for(mode)
    return prepare_messages_for_model(messages, is_local=False, mode=mode), (
        scrub(system_prompt) if system_prompt is not None else None
    )
