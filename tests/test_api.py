import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import Branding, NewConversation, create_app
from backend.api import deps
from backend.features import chat, exports, route_telemetry
from backend.providers import accounts
from backend.security import secrets

TOKEN = "secret-token"


def _client():
    return TestClient(create_app(TOKEN))


def test_api_requires_token():
    assert _client().get("/api/health").status_code == 401


def test_health_with_token():
    r = _client().get("/api/health", headers={"X-Orrery-Token": TOKEN})
    assert r.status_code == 200
    assert "database" in r.json()


def test_security_headers_present():
    r = _client().get("/api/health", headers={"X-Orrery-Token": TOKEN})
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_wrong_token_rejected():
    assert _client().get("/api/health", headers={"X-Orrery-Token": "nope"}).status_code == 401


def test_permission_error_returns_403(monkeypatch):
    async def locked_conversations():
        raise PermissionError("Team access key required.")

    monkeypatch.setattr(chat, "list_conversations", locked_conversations)

    r = _client().get("/api/conversations", headers={"X-Orrery-Token": TOKEN})

    assert r.status_code == 403
    assert r.json()["detail"] == "Team access key required."


def test_context_window_has_safe_bounds():
    # any size within bounds is accepted — the UI offers per-model tiers and the backend clamps to
    # the model's real maximum in chat.create/update_conversation
    assert NewConversation(model="openai/test").context_window == 1_000_000
    assert NewConversation(model="openai/test", context_window=131072).context_window == 131072
    assert NewConversation(model="openai/test", context_window=65536).context_window == 65536
    with pytest.raises(ValidationError):
        NewConversation(model="openai/test", context_window=1024)  # below the floor
    with pytest.raises(ValidationError):
        NewConversation(model="openai/test", context_window=5_000_000)  # above the ceiling


def test_branding_accepts_uploaded_raster_images_only():
    branding = Branding(
        enabled=True,
        name="Acme",
        details="Internal workspace",
        logo="data:image/png;base64,AA==",
    )
    assert branding.details == "Internal workspace"

    with pytest.raises(ValidationError):
        Branding(logo="https://example.com/logo.png")
    with pytest.raises(ValidationError):
        Branding(logo="data:image/svg+xml;base64,PHN2Zz4=")


def test_providers_never_return_raw_key():
    secrets.set_provider_key("openai", "sk-proj-SECRETKEY999")
    r = _client().get("/api/providers", headers={"X-Orrery-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["openai"]["configured"] is True
    # The raw key must not appear anywhere in the response payload.
    assert "SECRETKEY999" not in json.dumps(body)


def test_set_key_returns_masked_status():
    r = _client().put(
        "/api/providers/openai/key",
        headers={"X-Orrery-Token": TOKEN},
        json={"key": "sk-proj-ANOTHERSECRET42"},
    )
    assert r.status_code == 200
    assert "ANOTHERSECRET42" not in json.dumps(r.json())
    assert r.json()["configured"] is True


def test_provider_key_write_requires_admin_access(monkeypatch):
    async def not_admin():
        return False

    monkeypatch.setattr(deps.team, "is_admin", not_admin)

    r = _client().put(
        "/api/providers/openai/key",
        headers={"X-Orrery-Token": TOKEN},
        json={"key": "sk-proj-NOTALLOWED"},
    )

    assert r.status_code == 403
    assert r.json()["detail"] == "Admin access required."


def test_connect_claude_plan_endpoint(monkeypatch):
    monkeypatch.setattr(
        accounts,
        "_run_claude_auth_status",
        lambda: (
            True,
            {
                "loggedIn": True,
                "authMethod": "claude.ai",
                "apiProvider": "firstParty",
                "email": "person@example.com",
                "subscriptionType": "pro",
            },
            None,
        ),
    )

    r = _client().post("/api/providers/anthropic/claude-plan/connect", headers={"X-Orrery-Token": TOKEN})

    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert "person@example.com" not in json.dumps(body)


def test_connect_claude_plan_endpoint_unavailable():
    r = _client().post("/api/providers/anthropic/claude-plan/connect", headers={"X-Orrery-Token": TOKEN})

    assert r.status_code == 400
    assert "Claude Code" in r.json()["detail"]


def test_cli_install_endpoint_requires_acknowledgement():
    r = _client().post(
        "/api/providers/openai/chatgpt-plan/install",
        headers={"X-Orrery-Token": TOKEN},
        json={"acknowledged": False},
    )

    assert r.status_code == 400
    assert "Confirm" in r.json()["detail"]


def test_local_runtime_install_requires_acknowledgement():
    r = _client().post(
        "/api/local-models/install",
        headers={"X-Orrery-Token": TOKEN},
        json={"acknowledged": False},
    )

    assert r.status_code == 400
    assert "Confirm" in r.json()["detail"]


def test_cli_login_endpoint_uses_account_helper(monkeypatch):
    monkeypatch.setattr(
        accounts,
        "launch_plan_login",
        lambda mode_id: {"started": True, "message": f"started {mode_id}"},
    )

    r = _client().post(
        "/api/providers/openai/chatgpt-plan/login",
        headers={"X-Orrery-Token": TOKEN},
    )

    assert r.status_code == 200
    assert r.json()["message"] == "started chatgpt_plan"


def test_reply_export_returns_download(monkeypatch):
    async def fake_export(*args):
        return exports.ExportResult(b"%PDF-test", "application/pdf", "reply.pdf")

    async def fake_access(*args):
        return True

    monkeypatch.setattr(exports, "export_message", fake_export)
    monkeypatch.setattr(chat, "can_access_conversation", fake_access)
    r = _client().get(
        "/api/conversations/c1/messages/m1/export/pdf",
        headers={"X-Orrery-Token": TOKEN},
    )

    assert r.status_code == 200
    assert r.content == b"%PDF-test"
    assert r.headers["content-type"].startswith("application/pdf")
    assert 'filename="reply.pdf"' in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"


def test_reply_export_rejects_unsupported_format():
    r = _client().get(
        "/api/conversations/c1/messages/m1/export/exe",
        headers={"X-Orrery-Token": TOKEN},
    )

    assert r.status_code == 404


def test_task_route_summary_endpoint(monkeypatch):
    async def fake_summary():
        return {
            "routes": {"chat": 2, "file": 1},
            "outcomes": {"completed": 2, "sandbox_fallback": 1},
            "recent": [],
        }

    monkeypatch.setattr(route_telemetry, "summary", fake_summary)

    r = _client().get("/api/task-routes", headers={"X-Orrery-Token": TOKEN})

    assert r.status_code == 200
    assert r.json()["routes"]["chat"] == 2
    assert "sandbox_fallback" in r.json()["outcomes"]


def test_tools_catalog_endpoint():
    r = _client().get("/api/tools", headers={"X-Orrery-Token": TOKEN})

    assert r.status_code == 200
    keys = {tool["key"] for tool in r.json()["tools"]}
    assert "file_generate" in keys
    assert "crabbox_run" in keys


def test_crabbox_status_endpoint(monkeypatch):
    from backend.features import crabbox

    async def fake_status():
        return {"enabled": False, "installed": False, "configured": False, "doctor": {"ok": False}}

    monkeypatch.setattr(crabbox, "status", fake_status)

    r = _client().get("/api/crabbox/status", headers={"X-Orrery-Token": TOKEN})

    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_app_update_endpoint(monkeypatch):
    from backend.features import app_updates

    monkeypatch.setattr(
        app_updates,
        "check_for_updates",
        lambda: {"ok": True, "current_version": "0.1.3", "update_available": False},
    )

    r = _client().get("/api/app/update", headers={"X-Orrery-Token": TOKEN})

    assert r.status_code == 200
    assert r.json()["current_version"] == "0.1.3"
