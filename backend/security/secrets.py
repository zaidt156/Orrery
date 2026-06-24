from __future__ import annotations

import re

import keyring

_SERVICE = "orrery"
# matches the "user:password@" portion of a connection URL
_URL_PW = re.compile(r"(://[^:/@\s]+:)([^@/\s]+)(@)")


def get_secret(name: str) -> str | None:
    """Return a stored secret, or None if it isn't set."""
    return keyring.get_password(_SERVICE, name)


def set_secret(name: str, value: str) -> None:
    """Store a secret in the OS keychain."""
    keyring.set_password(_SERVICE, name, value)


def delete_secret(name: str) -> None:
    """Remove a secret if present (no error if it isn't)."""
    try:
        keyring.delete_password(_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass


def redact_url(text: str) -> str:
    """Mask any embedded connection-string password before logging/displaying."""
    return _URL_PW.sub(r"\1****\3", text)


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
