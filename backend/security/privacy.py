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


# Privacy modes for the cloud boundary: "off" sends text as-is; "basic"/"strict" apply
# the regex redaction above. (Strict is a hook for future, broader detection.)
PRIVACY_MODES = ("off", "basic", "strict")


def prepare_messages_for_model(messages: list[dict], *, is_local: bool, mode: str = "basic") -> list[dict]:
    """The single privacy boundary every cloud-bound call passes through. Local models and
    mode 'off' are untouched; otherwise PII is masked in each message's text content."""
    if is_local or mode not in ("basic", "strict"):
        return messages
    prepared: list[dict] = []
    for message in messages:
        content = message.get("content")
        copied = dict(message)
        if isinstance(content, str):
            copied["content"] = redact(content)
        elif isinstance(content, list):
            blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    block = {**block, "text": redact(block.get("text", ""))}
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
    return prepare_messages_for_model(messages, is_local=False, mode=mode), (
        redact(system_prompt) if system_prompt is not None else None
    )
