"""Abuse cases for the browser session handshake that replaced the `?token=` URL handoff."""
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.security.session import CODE_TTL_SECONDS, BrowserSession

TOKEN = "test-token"


def _app():
    app = create_app(TOKEN)
    return app, TestClient(app)


def test_header_auth_still_works():
    """The existing header path must not regress — packaged shells and tests rely on it."""
    _, client = _app()
    assert client.get("/api/health", headers={"X-Orrery-Token": TOKEN}).status_code == 200


def test_no_credential_is_rejected():
    _, client = _app()
    assert client.get("/api/health").status_code == 401


def test_claim_exchanges_code_for_an_httponly_cookie():
    app, client = _app()
    response = client.post("/api/session/claim", json={"code": app.state.session.code})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "httponly" in cookie.lower()
    assert "samesite=strict" in cookie.lower().replace(" ", "")


def test_cookie_authenticates_subsequent_requests():
    app, client = _app()
    client.post("/api/session/claim", json={"code": app.state.session.code})
    assert client.get("/api/health").status_code == 200  # cookie jar carries it


def test_launch_code_is_single_use():
    app, client = _app()
    code = app.state.session.code
    assert client.post("/api/session/claim", json={"code": code}).status_code == 200
    # replaying the same code must fail even though the session is still valid
    assert client.post("/api/session/claim", json={"code": code}).status_code == 401


def test_claim_rotates_to_a_fresh_usable_code():
    """Rotation keeps a valid code available so a lost cookie is recoverable."""
    app, client = _app()
    first = app.state.session.code
    client.post("/api/session/claim", json={"code": first})
    second = app.state.session.code
    assert second != first
    assert client.post("/api/session/claim", json={"code": second}).status_code == 200


def test_wrong_and_missing_codes_are_rejected():
    _, client = _app()
    assert client.post("/api/session/claim", json={"code": "guess"}).status_code == 401
    assert client.post("/api/session/claim", json={}).status_code == 401
    assert client.post("/api/session/claim", content=b"not json").status_code == 401


def test_expired_code_is_rejected():
    session = BrowserSession(TOKEN)
    session._code_minted_at -= CODE_TTL_SECONDS + 1
    assert session.claim(session.code) is None


def test_cookie_request_from_another_loopback_port_is_refused():
    """Cookies ignore port, so 127.0.0.1:9999 is same-site. Origin is what stops it."""
    app, client = _app()
    client.post("/api/session/claim", json={"code": app.state.session.code})
    response = client.get("/api/health", headers={"Origin": "http://127.0.0.1:9999"})
    assert response.status_code == 403


def test_cookie_request_from_the_app_origin_is_allowed():
    app, client = _app()
    client.post("/api/session/claim", json={"code": app.state.session.code})
    response = client.get("/api/health", headers={"Origin": "http://testserver"})
    assert response.status_code == 200


def test_header_auth_ignores_origin():
    """Header auth needs no Origin check, so a stale Origin must not break packaged clients."""
    _, client = _app()
    response = client.get(
        "/api/health",
        headers={"X-Orrery-Token": TOKEN, "Origin": "http://127.0.0.1:9999"},
    )
    assert response.status_code == 200


def test_origin_allowed_rejects_when_host_is_missing():
    session = BrowserSession(TOKEN)
    assert session.origin_allowed("http://127.0.0.1:9999", None, None) is False
    assert session.origin_allowed(None, None, None) is True
