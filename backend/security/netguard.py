from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

# Custom-model endpoints are user-supplied URLs the backend then calls server-side.
# This guard reduces SSRF blast radius (cloud metadata, link-local, odd schemes) while
# still allowing legitimate local model servers (Ollama/vLLM on loopback/private).
# Residual risk: DNS rebinding between this check and the actual request — acceptable
# for a single-user local app where the user configures their own endpoints (security.md §7).

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeUrlError(ValueError):
    """Raised when a URL is rejected by the SSRF guard."""


class FetchFailedError(ValueError):
    """A guarded fetch failed (unreachable, bad redirect, HTTP error) — message is safe to surface."""


class FetchTooLargeError(ValueError):
    """The response body exceeded the hard byte cap."""


def _resolved_ips(host: str, port: int) -> set[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError("The model URL host could not be resolved.") from exc
    return {info[4][0] for info in infos}


def validate_fetch_url(url: str, *, allow_private: bool = True) -> str:
    """SSRF guard for user-entered URLs the backend fetches (dataset API imports).

    Always blocks link-local (cloud metadata), multicast, reserved, and unspecified ranges.
    With allow_private=False (team mode: members shouldn't probe the host's LAN through Orrery),
    loopback and private ranges are blocked too.
    """
    cleaned = (url or "").strip()
    if len(cleaned) > 500:
        raise UnsafeUrlError("URL is too long.")
    parsed = urlparse(cleaned)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError("URL must start with http:// or https://.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL must not contain credentials.")
    if not parsed.hostname:
        raise UnsafeUrlError("URL is missing a host.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port < 1024 and port not in (80, 443):
        raise UnsafeUrlError("URL targets a blocked service port.")
    _checked_ips(parsed.hostname, port, allow_private=allow_private)
    return cleaned


def _checked_ips(host: str, port: int, *, allow_private: bool) -> list[str]:
    """Resolve and validate every address for host:port; return them sorted (deterministic pin)."""
    ips = sorted(_resolved_ips(host, port))
    for raw in ips:
        ip = ipaddress.ip_address(raw)
        if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise UnsafeUrlError("URL points to a blocked address range.")
        if not allow_private and (ip.is_loopback or ip.is_private):
            raise UnsafeUrlError("In team mode, imports can't target local/private network addresses.")
    return ips


def validate_model_base_url(url: str) -> str:
    """Return the URL if it is a safe model endpoint, else raise UnsafeUrlError.

    Policy: only http/https; block link-local (incl. 169.254.169.254 metadata), multicast,
    reserved, and unspecified addresses; plain http is allowed only for loopback/private
    hosts (local self-hosted models), https is allowed for private or public hosts.
    """
    cleaned = (url or "").strip()
    if len(cleaned) > 500:
        raise UnsafeUrlError("Model URL is too long.")
    parsed = urlparse(cleaned)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError("Model URL must start with http:// or https://.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Model URL must not contain credentials.")
    if parsed.fragment:
        raise UnsafeUrlError("Model URL must not contain a fragment.")
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


# --- guarded outbound fetch (dataset imports, automation HTTP node) -------------------------------

_REDIRECT_CODES = {301, 302, 303, 307, 308}


@dataclass
class CheckedResponse:
    """A fully buffered, size-capped response from fetch_checked."""

    status_code: int
    headers: dict[str, str]
    content: bytes
    url: str  # final logical URL (hostname form, never the pinned IP)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self) -> None:
        # deliberately no URL in the message: request URLs can carry secret query params
        if self.status_code >= 400:
            raise FetchFailedError(f"The server responded with HTTP {self.status_code}.")


def _pinned_request(parsed, ip_str: str) -> tuple[str, dict, str | None]:
    """(connect_url, httpx extensions, Host header) — connect to the validated IP, not the name,
    so a DNS answer cannot change between validation and connection (rebinding defense)."""
    if (parsed.hostname or "").lower() == ip_str.lower():
        return urlunparse(parsed), {}, None
    ip = ipaddress.ip_address(ip_str)
    host_literal = f"[{ip_str}]" if ip.version == 6 else ip_str
    suffix = f":{parsed.port}" if parsed.port else ""
    connect = urlunparse((parsed.scheme, host_literal + suffix, parsed.path or "/", parsed.params, parsed.query, ""))
    host_header = f"{parsed.hostname}{suffix}"
    extensions = {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else {}
    return connect, extensions, host_header


async def fetch_checked(
    url: str,
    *,
    max_bytes: int,
    allow_private: bool = True,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: float = 25.0,
    max_redirects: int = 5,
    transport=None,
) -> CheckedResponse:
    """Guarded HTTP fetch: every hop re-validated (scheme, credentials, host, port, every resolved
    address), the connection pinned to the validated IP, redirects followed manually, and the body
    streamed into a hard byte cap. Custom headers are dropped when a redirect leaves the original
    host so auth headers can't be replayed to an attacker-chosen destination.
    """
    import httpx

    logical = validate_fetch_url(url, allow_private=allow_private)
    original_host = (urlparse(logical).hostname or "").lower()
    request_method = (method or "GET").upper()
    if request_method not in ("GET", "HEAD"):
        raise UnsafeUrlError("Only GET and HEAD requests are allowed.")

    client_kwargs: dict = {"timeout": timeout, "follow_redirects": False}
    if transport is not None:
        client_kwargs["transport"] = transport
    async with httpx.AsyncClient(**client_kwargs) as client:
        for _hop in range(max_redirects + 1):
            parsed = urlparse(logical)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            pinned = _checked_ips(parsed.hostname or "", port, allow_private=allow_private)[0]
            connect_url, extensions, host_header = _pinned_request(parsed, pinned)
            send_headers = dict(headers or {}) if (parsed.hostname or "").lower() == original_host else {}
            if host_header:
                send_headers["Host"] = host_header
            try:
                async with client.stream(
                    request_method, connect_url, headers=send_headers, extensions=extensions
                ) as resp:
                    if resp.status_code in _REDIRECT_CODES:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchFailedError("The server redirected without a destination.")
                        logical = validate_fetch_url(urljoin(logical, location), allow_private=allow_private)
                        if resp.status_code == 303:
                            request_method = "GET"
                        continue
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            raise FetchTooLargeError(
                                f"The response is too large ({max_bytes // 1_000_000} MB cap)."
                            )
                    return CheckedResponse(
                        status_code=resp.status_code,
                        headers={k.lower(): v for k, v in resp.headers.items()},
                        content=bytes(buf),
                        url=logical,
                    )
            except httpx.HTTPError as exc:  # message may embed the URL → replace with a safe one
                raise FetchFailedError(f"Could not reach the server ({type(exc).__name__}).") from exc
        raise FetchFailedError("Too many redirects.")
