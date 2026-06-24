import pytest

from backend.security import netguard


def _fake_dns(ip):
    def _resolver(host, port, *args, **kwargs):
        return [(None, None, None, "", (ip, port))]
    return _resolver


def test_rejects_non_http_schemes():
    for url in ("file:///etc/passwd", "ftp://host/x", "gopher://host", "data:text/plain,hi"):
        with pytest.raises(netguard.UnsafeUrlError):
            netguard.validate_model_base_url(url)


def test_rejects_missing_host():
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("https:///v1")


def test_blocks_cloud_metadata_link_local(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns("169.254.169.254"))
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("https://metadata.internal/v1")


def test_blocks_plain_http_to_public(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns("8.8.8.8"))
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("http://api.example.com/v1")


def test_allows_https_public(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns("1.2.3.4"))
    assert netguard.validate_model_base_url("https://api.openai.com/v1 ").strip() == "https://api.openai.com/v1"


def test_allows_http_loopback_and_private(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns("127.0.0.1"))
    assert netguard.validate_model_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    monkeypatch.setattr(netguard.socket, "getaddrinfo", _fake_dns("10.0.0.5"))
    assert netguard.validate_model_base_url("http://my-vllm.lan:8000/v1") == "http://my-vllm.lan:8000/v1"


def test_unresolvable_host_is_rejected(monkeypatch):
    import socket as _s

    def _boom(*a, **k):
        raise _s.gaierror("nope")

    monkeypatch.setattr(netguard.socket, "getaddrinfo", _boom)
    with pytest.raises(netguard.UnsafeUrlError):
        netguard.validate_model_base_url("https://does-not-exist.invalid/v1")
