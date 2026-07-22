"""Abuse-case coverage for netguard.fetch_checked (TODO P0): redirect chains to blocked hosts,
redirect loops, oversized bodies, credentialed URLs, blocked ports, pinned connections, and
auth headers dropped when a redirect leaves the original host."""
import socket as real_socket

import httpx
import pytest

from backend.security import netguard


def _fake_dns(mapping):
    def _resolver(host, port, *args, **kwargs):
        ip = mapping.get(host)
        if ip is None:
            raise real_socket.gaierror("no such host")
        return [(None, None, None, "", (ip, port))]
    return _resolver


@pytest.mark.anyio
async def test_follows_validated_redirect_and_returns_body(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo",
                        _fake_dns({"api.example.com": "8.8.8.8", "cdn.example.com": "9.9.9.9"}))

    def handler(request):
        if request.url.host == "8.8.8.8":
            return httpx.Response(302, headers={"location": "https://cdn.example.com/data.json"})
        return httpx.Response(200, json={"ok": True})

    resp = await netguard.fetch_checked(
        "https://api.example.com/x", max_bytes=1000, transport=httpx.MockTransport(handler),
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert resp.url == "https://cdn.example.com/data.json"


@pytest.mark.anyio
async def test_redirect_to_cloud_metadata_is_blocked(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo",
                        _fake_dns({"api.example.com": "8.8.8.8",
                                   "169.254.169.254": "169.254.169.254"}))

    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(netguard.UnsafeUrlError):
        await netguard.fetch_checked(
            "https://api.example.com/x", max_bytes=1000, transport=httpx.MockTransport(handler),
        )


@pytest.mark.anyio
async def test_redirect_to_private_host_blocked_in_team_mode(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo",
                        _fake_dns({"api.example.com": "8.8.8.8", "internal.lan": "10.0.0.5"}))

    def handler(request):
        return httpx.Response(302, headers={"location": "https://internal.lan/secrets"})

    with pytest.raises(netguard.UnsafeUrlError):
        await netguard.fetch_checked(
            "https://api.example.com/x", max_bytes=1000, allow_private=False,
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.anyio
async def test_redirect_loop_terminates(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns({"api.example.com": "8.8.8.8"}))

    def handler(request):
        return httpx.Response(302, headers={"location": "https://api.example.com/again"})

    with pytest.raises(netguard.FetchFailedError, match="Too many redirects"):
        await netguard.fetch_checked(
            "https://api.example.com/x", max_bytes=1000, transport=httpx.MockTransport(handler),
        )


@pytest.mark.anyio
async def test_oversized_body_hits_the_streamed_cap(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns({"api.example.com": "8.8.8.8"}))

    def handler(request):
        return httpx.Response(200, content=b"x" * 5001)

    with pytest.raises(netguard.FetchTooLargeError):
        await netguard.fetch_checked(
            "https://api.example.com/big", max_bytes=5000, transport=httpx.MockTransport(handler),
        )


@pytest.mark.anyio
async def test_credentialed_urls_are_rejected():
    with pytest.raises(netguard.UnsafeUrlError, match="credentials"):
        await netguard.fetch_checked("https://user:pw@api.example.com/x", max_bytes=1000)


@pytest.mark.anyio
async def test_low_service_ports_are_rejected(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns({"api.example.com": "8.8.8.8"}))
    with pytest.raises(netguard.UnsafeUrlError, match="port"):
        await netguard.fetch_checked("https://api.example.com:22/x", max_bytes=1000)


@pytest.mark.anyio
async def test_connection_is_pinned_to_validated_address(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns({"localhost": "127.0.0.1"}))
    seen = {}

    def handler(request):
        seen["connect_host"] = request.url.host
        seen["host_header"] = request.headers.get("host")
        return httpx.Response(200, content=b"ok")

    resp = await netguard.fetch_checked(
        "http://localhost:9000/x", max_bytes=1000, transport=httpx.MockTransport(handler),
    )
    assert resp.content == b"ok"
    assert seen["connect_host"] == "127.0.0.1"  # DNS answer can't change after validation
    assert seen["host_header"] == "localhost:9000"


@pytest.mark.anyio
async def test_auth_headers_dropped_when_redirect_leaves_host(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo",
                        _fake_dns({"api.example.com": "8.8.8.8", "evil.example.net": "9.9.9.9"}))
    hops = []

    def handler(request):
        hops.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == "8.8.8.8":
            return httpx.Response(302, headers={"location": "https://evil.example.net/steal"})
        return httpx.Response(200, content=b"{}")

    await netguard.fetch_checked(
        "https://api.example.com/x", max_bytes=1000,
        headers={"Authorization": "Bearer sekrit"}, transport=httpx.MockTransport(handler),
    )
    assert hops[0][1] == "Bearer sekrit"   # sent to the host the user configured
    assert hops[1][1] is None              # never replayed to the redirect target


@pytest.mark.anyio
async def test_http_error_message_contains_no_url(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns({"api.example.com": "8.8.8.8"}))

    def handler(request):
        return httpx.Response(401)

    resp = await netguard.fetch_checked(
        "https://api.example.com/x?api_key=sekrit", max_bytes=1000,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(netguard.FetchFailedError) as exc_info:
        resp.raise_for_status()
    assert "401" in str(exc_info.value)
    assert "sekrit" not in str(exc_info.value)
    assert "example" not in str(exc_info.value)
