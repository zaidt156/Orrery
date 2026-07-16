"""Task 9 — serving app bundles safely. The route is unauthenticated (it feeds a sandboxed iframe
whose sub-resource requests cannot carry the token), so its whole security rests on: an unguessable
id, a strict CSP with no network egress, traversal-proof path resolution, and read-only access.
These tests pin every one of those.
"""

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.features import files as file_library
from backend.features.sandbox import SandboxFile


TOKEN = "app-bundle-test-token"

_INDEX = b"<!doctype html><html><head><link rel=stylesheet href=app.css></head>" \
         b"<body><div id=root></div><script src=app.js></script></body></html>"
_JS = b"document.getElementById('root').textContent = 'hi';"
_CSS = b"#root{color:teal}"


def _client() -> TestClient:
    return TestClient(create_app(TOKEN))


def _store_bundle() -> dict:
    return file_library.store_app_bundle(
        "expense-splitter.zip",
        [
            SandboxFile("index.html", _INDEX),
            SandboxFile("app.js", _JS),
            SandboxFile("app.css", _CSS),
            SandboxFile("assets/logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        ],
    )


def test_serves_the_entry_point_with_a_locked_down_csp(tmp_path, monkeypatch):
    monkeypatch.setattr(file_library, "_DIR", tmp_path / "generated")
    meta = _store_bundle()
    client = _client()

    # Bare id and explicit index.html both serve the entry point — no token required.
    for path in (f"/api/apps/{meta['id']}", f"/api/apps/{meta['id']}/index.html"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content == _INDEX
        assert response.headers["content-type"].startswith("text/html")
        csp = response.headers["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "connect-src 'none'" in csp          # the app can never reach the network
        assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]  # no inline JS
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"


def test_serves_members_with_correct_executable_mime(tmp_path, monkeypatch):
    monkeypatch.setattr(file_library, "_DIR", tmp_path / "generated")
    meta = _store_bundle()
    client = _client()

    js = client.get(f"/api/apps/{meta['id']}/app.js")
    assert js.status_code == 200 and js.content == _JS
    # nosniff means a wrong type would stop the script running — it must be a JS type, never text/plain.
    assert js.headers["content-type"].startswith("text/javascript")

    css = client.get(f"/api/apps/{meta['id']}/app.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")

    svg = client.get(f"/api/apps/{meta['id']}/assets/logo.svg")
    assert svg.status_code == 200 and svg.headers["content-type"] == "image/svg+xml"


def test_iframe_is_not_blocked_by_the_global_frame_headers(tmp_path, monkeypatch):
    monkeypatch.setattr(file_library, "_DIR", tmp_path / "generated")
    meta = _store_bundle()

    response = _client().get(f"/api/apps/{meta['id']}/index.html")
    # The blanket middleware sets X-Frame-Options: DENY on other routes; the bundle must stay framable.
    assert response.headers.get("x-frame-options") == "SAMEORIGIN"


def test_path_traversal_cannot_escape_the_bundle_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(file_library, "_DIR", tmp_path / "generated")
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)
    # A secret sitting two levels above the bundle root (generated/apps/<id>/), i.e. where a
    # ../../ traversal from inside the bundle would land.
    secret_body = b"TOP-SECRET-DO-NOT-SERVE"
    (tmp_path / "generated" / "secret.meta").write_bytes(secret_body)
    meta = _store_bundle()
    client = _client()

    # The guarantee is that the secret's CONTENT never reaches the client, regardless of how the
    # HTTP layer normalizes the URL. Encoded traversal reaches the route unmangled and must 404.
    encoded_attacks = [
        "..%2f..%2fsecret.meta",
        "%2e%2e%2f%2e%2e%2fsecret.meta",
        "app.js%2f..%2f..%2f..%2fsecret.meta",
        "..%5c..%5csecret.meta",
        "%00index.html",
    ]
    for attack in encoded_attacks:
        response = client.get(f"/api/apps/{meta['id']}/{attack}")
        assert response.status_code == 404, f"encoded traversal not refused: {attack}"

    # Belt and braces: across every attack (encoded or client-normalized), the secret never leaks.
    for attack in encoded_attacks + ["../../secret.meta", "../../../generated/secret.meta"]:
        assert secret_body not in client.get(f"/api/apps/{meta['id']}/{attack}").content


def test_backslash_and_absolute_paths_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(file_library, "_DIR", tmp_path / "generated")
    meta = _store_bundle()
    client = _client()

    assert client.get(f"/api/apps/{meta['id']}/..%5csecret.meta").status_code == 404
    assert client.get(f"/api/apps/{meta['id']}/nope.js").status_code == 404


def test_unknown_and_non_app_ids_are_404(tmp_path, monkeypatch):
    monkeypatch.setattr(file_library, "_DIR", tmp_path / "generated")
    # A plain generated file (not an app bundle) must not be reachable through the app route.
    plain = file_library.store("notes.txt", "text/plain", b"private notes")
    client = _client()

    assert client.get("/api/apps/deadbeefdeadbeefdeadbeefdeadbeef/index.html").status_code == 404
    assert client.get(f"/api/apps/{plain['id']}/index.html").status_code == 404
    assert client.get("/api/apps/not-a-valid-id/index.html").status_code == 404


def test_read_app_bundle_file_helper_confines_to_the_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(file_library, "_DIR", tmp_path / "generated")
    meta = _store_bundle()

    assert file_library.read_app_bundle_file(meta["id"], "app.js")[0] == _JS
    assert file_library.read_app_bundle_file(meta["id"], "")[0] == _INDEX  # defaults to index.html
    assert file_library.read_app_bundle_file(meta["id"], "../secret.meta") is None
    assert file_library.read_app_bundle_file(meta["id"], "missing.js") is None
    assert file_library.read_app_bundle_file("deadbeef" * 4, "index.html") is None
