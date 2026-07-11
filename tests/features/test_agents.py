from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.features import agents


def _config(**overrides):
    data = {
        "name": "Research assistant",
        "goal": "Research a question and return a concise evidence-backed brief.",
        "model": "ollama/llama3",
    }
    data.update(overrides)
    return agents.AgentConfig.model_validate(data)


def test_minimal_agent_has_secure_bounded_defaults():
    config = _config()

    assert config.trigger_modes == ["manual"]
    assert config.permissions.life_access == "none"
    assert "external_write" in config.permissions.approval_risks
    assert config.budgets.max_steps_per_run == 8
    assert config.schedule.enabled is False


def test_schedule_requires_five_fields_and_iana_timezone():
    with pytest.raises(ValidationError, match="five-field"):
        _config(schedule={"enabled": False, "cron": "0 0 9 * * *", "timezone": "UTC"})
    with pytest.raises(ValidationError, match="IANA"):
        _config(schedule={"enabled": False, "cron": "0 9 * * *", "timezone": "Moon/Base"})


def test_enabled_schedule_requires_schedule_trigger():
    with pytest.raises(ValidationError, match="schedule trigger"):
        _config(schedule={"enabled": True, "cron": "0 9 * * *", "timezone": "Europe/Copenhagen"})

    valid = _config(
        trigger_modes=["manual", "schedule"],
        schedule={"enabled": True, "cron": "0 9 * * *", "timezone": "Europe/Copenhagen"},
    )
    assert valid.schedule.enabled is True


def test_connector_trigger_requires_explicit_account_grant():
    with pytest.raises(ValidationError, match="slack trigger"):
        _config(trigger_modes=["manual", "slack"])

    valid = _config(
        trigger_modes=["manual", "slack"],
        connector_grants=[{
            "connector": "slack",
            "account_id": "workspace-1",
            "actions": ["receive"],
            "resources": ["channel:C123"],
        }],
    )
    assert valid.connector_grants[0].resources == ["channel:C123"]


def test_unknown_tool_and_dangerous_preapproval_are_rejected():
    with pytest.raises(agents.AgentConfigError, match="Unknown tool"):
        agents.validate_config(_config(tool_grants=[{"tool": "not-real"}]))
    with pytest.raises(agents.AgentConfigError, match="cannot be preapproved"):
        agents.validate_config(_config(tool_grants=[{"tool": "mcp_call", "approval": "preapproved"}]))


def test_agent_config_rejects_credentials():
    # assembled at runtime so secret scanners don't flag this FAKE fixture as a real token
    config = _config(guidelines=["Use token " + "xoxb-" + "123456789-abcdefghijklmnop"])

    with pytest.raises(agents.AgentConfigError, match="credential"):
        agents.validate_config(config)


def test_agent_config_hash_is_canonical():
    first = _config(guidelines=["One", "Two"])
    second = agents.AgentConfig.model_validate(first.model_dump())

    assert agents._canonical(first)[1] == agents._canonical(second)[1]
