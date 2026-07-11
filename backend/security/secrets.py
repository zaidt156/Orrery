from __future__ import annotations

import re

import keyring

_SERVICE = "orrery"
# matches the "user:password@" portion of a connection URL
_URL_PW = re.compile(r"(://[^:/@\s]+:)([^@/\s]+)(@)")
_SECRET_NAME_RX = re.compile(r"^[A-Za-z0-9:_\-]{1,120}$")


class SecretStoreError(RuntimeError):
    """The OS keychain failed (locked, unavailable, or no backend). Fail closed."""


def _validate_secret_name(name: str) -> str:
    if not _SECRET_NAME_RX.fullmatch(name or ""):
        raise ValueError("Invalid secret name.")
    return name


def get_secret(name: str) -> str | None:
    """Return a stored secret, or None if it isn't set. Raises SecretStoreError if the
    keychain backend itself fails (vs. simply not having the entry)."""
    _validate_secret_name(name)
    try:
        return keyring.get_password(_SERVICE, name)
    except keyring.errors.KeyringError as exc:
        raise SecretStoreError("The OS keychain is unavailable.") from exc


def set_secret(name: str, value: str) -> None:
    """Store a secret in the OS keychain."""
    _validate_secret_name(name)
    try:
        keyring.set_password(_SERVICE, name, value)
    except keyring.errors.KeyringError as exc:
        raise SecretStoreError("Could not save to the OS keychain.") from exc


def delete_secret(name: str) -> None:
    """Remove a secret if present (no error if it isn't)."""
    _validate_secret_name(name)
    try:
        keyring.delete_password(_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError as exc:
        raise SecretStoreError("Could not update the OS keychain.") from exc


def redact_url(text: str) -> str:
    """Mask any embedded connection-string password before logging/displaying."""
    return _URL_PW.sub(r"\1****\3", text)


# Broad secret scrubber for anything user-facing (logs, provider/CLI errors, streamed errors).
# Catches common key/token shapes, bearer tokens, URL passwords, and key-bearing query params.
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "[redacted]"),
    (re.compile(r"AIza[A-Za-z0-9_\-]{8,}"), "[redacted]"),
    (re.compile(r"xox(?:a|b|p|r|s)-[A-Za-z0-9-]{10,}", re.IGNORECASE), "[redacted]"),
    (re.compile(r"xapp-[A-Za-z0-9-]{10,}", re.IGNORECASE), "[redacted]"),
    (re.compile(r"(?:1//|ya29\.)[A-Za-z0-9._\-]{10,}"), "[redacted]"),
    (re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"), "[redacted private key]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE), "Bearer [redacted]"),
    (_URL_PW, r"\1****\3"),
    (re.compile(r"([?&](?:key|api_key|token|access_token|secret)=)[^&\s]+", re.IGNORECASE), r"\1[redacted]"),
]


def redact_secrets(text: str) -> str:
    """Scrub key-like values, bearer tokens, URL passwords, and secret query params."""
    value = str(text or "")
    for pattern, repl in _SECRET_PATTERNS:
        value = pattern.sub(repl, value)
    return value


# provider keys live in the keychain under "key:<provider>"; only a masked
# preview or a boolean ever leaves the backend, never the raw key

def _provider_key_name(provider: str) -> str:
    return f"key:{provider}"


def get_provider_key(provider: str) -> str | None:
    """The raw key — for use ONLY when calling the provider. Never log/return it."""
    return get_secret(_provider_key_name(provider))


def set_provider_key(provider: str, value: str) -> None:
    set_secret(_provider_key_name(provider), value)


def clear_provider_key(provider: str) -> None:
    delete_secret(_provider_key_name(provider))


def mask_key(value: str) -> str:
    """A safe-to-display preview like 'sk-ant-••••3kF9' — never the full key."""
    if len(value) <= 8:
        return "••••"
    return f"{value[:6]}••••{value[-4:]}"


def provider_key_status(provider: str) -> dict:
    """Whether a key exists + a masked preview — never the key itself."""
    value = get_provider_key(provider)
    return {"configured": bool(value), "preview": mask_key(value) if value else None}
