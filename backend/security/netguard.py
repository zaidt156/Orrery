from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Custom-model endpoints are user-supplied URLs the backend then calls server-side.
# This guard reduces SSRF blast radius (cloud metadata, link-local, odd schemes) while
# still allowing legitimate local model servers (Ollama/vLLM on loopback/private).
# Residual risk: DNS rebinding between this check and the actual request — acceptable
# for a single-user local app where the user configures their own endpoints (security.md §7).

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeUrlError(ValueError):
    """Raised when a model endpoint URL is rejected by the SSRF guard."""


def _resolved_ips(host: str, port: int) -> set[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError("The model URL host could not be resolved.") from exc
    return {info[4][0] for info in infos}


def validate_model_base_url(url: str) -> str:
    """Return the URL if it is a safe model endpoint, else raise UnsafeUrlError.

    Policy: only http/https; block link-local (incl. 169.254.169.254 metadata), multicast,
    reserved, and unspecified addresses; plain http is allowed only for loopback/private
    hosts (local self-hosted models), https is allowed for private or public hosts.
    """
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError("Model URL must start with http:// or https://.")
    if not parsed.hostname:
        raise UnsafeUrlError("Model URL is missing a host.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    ips = _resolved_ips(parsed.hostname, port)
    parsed_ips = [ipaddress.ip_address(ip) for ip in ips]

    for ip in parsed_ips:
        if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise UnsafeUrlError("Model URL points to a blocked address range.")

    if parsed.scheme == "http" and not all(ip.is_loopback or ip.is_private for ip in parsed_ips):
        raise UnsafeUrlError("Plain http is only allowed for local/private model servers — use https.")

    return cleaned
