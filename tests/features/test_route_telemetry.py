import uuid

from backend.features import route_telemetry, taskrouter


def test_event_payload_stores_route_metadata_not_prompt_text():
    prompt = "Create a PDF about Project Alpha with email me@example.com"
    plan = taskrouter.plan(prompt)

    payload = route_telemetry.event_payload(
        plan,
        conversation_id="00000000-0000-0000-0000-000000000001",
        has_attachments=True,
    )

    rendered = repr(payload)
    assert payload["conversation_id"] == uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert payload["route"] == "file"
    assert payload["output_mode"] == "file"
    assert payload["has_attachments"] is True
    assert "Project Alpha" not in rendered
    assert "me@example.com" not in rendered


def test_sandbox_policy_reflects_plan_policy():
    plan = taskrouter.plan("Create a PNG chart from sales data")

    assert route_telemetry.sandbox_policy(plan) == "preferred"


def test_clean_detail_redacts_secret_shapes():
    bearer = "Bearer " + ("a" * 16)
    key = "sk-" + "test-" + "abcdefghijkl"
    detail = route_telemetry.clean_detail(f"provider error {bearer} and {key}")

    assert "a" * 16 not in detail
    assert key not in detail
    assert "[redacted]" in detail
