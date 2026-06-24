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
