import json

import pytest

from backend.providers import accounts, ai
from backend.security import secrets


def _ready_status():
    return (
        True,
        {
            "loggedIn": True,
            "authMethod": "claude.ai",
            "apiProvider": "firstParty",
            "email": "person@example.com",
            "subscriptionType": "pro",
        },
        None,
    )


def test_provider_status_includes_modes_without_raw_secrets(monkeypatch):
    monkeypatch.setattr(accounts, "_run_claude_auth_status", _ready_status)
    monkeypatch.setattr(accounts, "_codex_command", lambda: None)
    monkeypatch.setattr(accounts, "_gemini_command", lambda: None)
    secrets.set_provider_key("openai", "sk-proj-SECRET-OPENAI-KEY")

    body = accounts.providers_status(ai.PROVIDERS)
    payload = json.dumps(body)

    assert body["openai"]["configured"] is True
    assert "SECRET-OPENAI-KEY" not in payload
    assert "person@example.com" not in payload
    assert any(m["id"] == "chatgpt_plan" and m["requires_acknowledgement"] for m in body["openai"]["modes"])
    assert any(m["id"] == "gemini_plan" and m["requires_acknowledgement"] for m in body["google"]["modes"])
    assert any(m["id"] == "claude_plan" and m["available"] is True for m in body["anthropic"]["modes"])


def test_connect_claude_plan_stores_only_local_opt_in(monkeypatch, fake_keyring):
    monkeypatch.setattr(accounts, "_run_claude_auth_status", _ready_status)

    status = accounts.connect_claude_plan()

    assert status["configured"] is True
    assert status["preview"] == "Claude Pro plan"
    stored_values = list(fake_keyring.values())
    assert stored_values == ["connected"]


def test_claude_plan_unavailable_without_safe_cli_flags(monkeypatch):
    monkeypatch.setattr(accounts, "_safe_cli_flags_ready", lambda: (False, "No safe mode."))
    monkeypatch.setattr(accounts, "_run_claude_auth_status", _ready_status)

    status = accounts.claude_plan_mode_status()

    assert status["available"] is False
    assert status["configured"] is False
    assert status["message"] == "No safe mode."


def test_claude_plan_model_requires_successful_connect(monkeypatch):
    monkeypatch.setattr(accounts, "_run_claude_auth_status", _ready_status)

    assert accounts.claude_plan_model() is None
    accounts.connect_claude_plan()
    assert accounts.claude_plan_model()["id"] == "claude_plan/default"


def test_claude_plan_rejects_image_blocks():
    with pytest.raises(accounts.UnsupportedClaudePlanInput):
        accounts._content_to_text([{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}])


def test_claude_plan_models_skip_cli_without_local_connection(monkeypatch):
    monkeypatch.setattr(
        accounts,
        "_run_claude_auth_status",
        lambda: pytest.fail("model listing should not probe Claude Code before local connect"),
    )

    assert accounts.claude_plan_models() == []


@pytest.mark.anyio
async def test_ai_routes_claude_plan_to_adapter(monkeypatch):
    async def fake_stream(messages, system_prompt=None, model_id=None, effort=None):
        yield "from claude plan"

    monkeypatch.setattr(accounts, "stream_claude_plan", fake_stream)
    out = []
    async for delta in ai.stream_chat("claude_plan/default", [{"role": "user", "content": "hi"}]):
        out.append(delta)

    assert "".join(out) == "from claude plan"


def test_cli_plan_models_skip_cli_without_local_connection(monkeypatch):
    monkeypatch.setattr(accounts, "_codex_command", lambda: pytest.fail("should not probe codex before connect"))
    monkeypatch.setattr(accounts, "_gemini_command", lambda: pytest.fail("should not probe gemini before connect"))
    assert accounts.chatgpt_plan_models() == []
    assert accounts.gemini_plan_models() == []


def test_codex_status_overrides_invalid_user_service_tier(monkeypatch):
    calls = []

    def fake_status(_cmd, args):
        calls.append(args)
        if args == ["exec", "--help"]:
            return type("Result", (), {
                "returncode": 0,
                "stdout": "--ephemeral --sandbox --output-last-message --skip-git-repo-check",
                "stderr": "",
            })()
        return type("Result", (), {"returncode": 0, "stdout": "Logged in using ChatGPT", "stderr": ""})()

    monkeypatch.setattr(accounts, "_codex_command", lambda: "codex.cmd")
    monkeypatch.setattr(accounts, "_run_cli_status", fake_status)
    accounts.clear_status_cache()

    status = accounts.chatgpt_plan_mode_status()

    assert status["available"] is True
    assert status["requires_acknowledgement"] is True
    assert ["login", "status", "-c", 'service_tier="fast"'] in calls


def test_cli_plan_connect_requires_acknowledgement(monkeypatch):
    monkeypatch.setattr(
        accounts,
        "chatgpt_plan_mode_status",
        lambda: {"available": True, "message": "ready", "configured": False},
    )
    monkeypatch.setattr(
        accounts,
        "gemini_plan_mode_status",
        lambda: {"available": True, "message": "ready", "configured": False},
    )

    with pytest.raises(ValueError, match="Confirm the Codex CLI notice"):
        accounts.connect_chatgpt_plan()
    with pytest.raises(ValueError, match="Confirm the Google CLI notice"):
        accounts.connect_gemini_plan()


@pytest.mark.anyio
async def test_codex_route_uses_ephemeral_read_only_temp_execution(monkeypatch):
    captured = {}
    secrets.set_secret(accounts._CHATGPT_PLAN_KEY, "connected")
    monkeypatch.setattr(accounts, "_codex_command", lambda: "codex.cmd")
    monkeypatch.setattr(accounts, "_codex_exec_flags", lambda: (True, False, None))

    def fake_run(args, prompt, outfile):
        captured.update(args=args, prompt=prompt, outfile=outfile)
        return "safe reply"

    monkeypatch.setattr(accounts, "_run_codex", fake_run)
    out = [
        delta
        async for delta in accounts.stream_chatgpt_plan(
            [{"role": "user", "content": "hello"}],
            model_id="chatgpt_plan/default",
            effort="high",
        )
    ]

    assert out == ["safe reply"]
    assert captured["args"][1] == "exec"
    assert "--ephemeral" in captured["args"]
    assert captured["args"][captured["args"].index("-s") + 1] == "read-only"
    assert 'service_tier="fast"' in captured["args"]
    assert 'model_reasoning_effort="high"' in captured["args"]
    assert captured["args"][captured["args"].index("-m") + 1] == "gpt-5.5"


def test_old_codex_default_uses_compatible_fast_model(monkeypatch):
    monkeypatch.setattr(accounts, "_command_version", lambda _cmd: (0, 121, 0))

    assert accounts._codex_model_flag("chatgpt_plan/default", "codex.cmd") == "gpt-5.4-mini"
    assert accounts._codex_model_flag("chatgpt_plan/gpt-5.5-mini", "codex.cmd") == "gpt-5.4-mini"


def test_plan_cli_install_requires_consent():
    with pytest.raises(ValueError, match="Confirm the official CLI installation"):
        accounts.install_plan_cli("chatgpt_plan")


def test_plan_cli_install_uses_fixed_winget_package(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1] == "list":
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "Installed", "stderr": ""})()

    monkeypatch.setattr(accounts.shutil, "which", lambda name: "winget.exe" if name == "winget" else None)
    monkeypatch.setattr(accounts.subprocess, "run", fake_run)
    monkeypatch.setattr(
        accounts,
        "_plan_mode_status",
        lambda _mode_id, force=False: {"installed": True, "available": False},
    )

    status = accounts.install_plan_cli("chatgpt_plan", acknowledged=True)

    install = next(args for args in calls if args[1] == "install")
    assert install[install.index("--id") + 1] == "OpenAI.Codex"
    assert status["installed"] is True


def test_plan_login_launches_only_vendor_command(monkeypatch):
    captured = {}

    class FakeProcess:
        pass

    monkeypatch.setattr(accounts, "_plan_command", lambda _mode_id: "codex.exe")
    monkeypatch.setattr(
        accounts.subprocess,
        "Popen",
        lambda args, **kwargs: captured.update(args=args, kwargs=kwargs) or FakeProcess(),
    )

    result = accounts.launch_plan_login("chatgpt_plan")

    assert result["started"] is True
    assert captured["args"] == ["codex.exe", "login"]


def test_gemini_stream_parser_only_returns_assistant_text():
    assert accounts._gemini_text_delta({"type": "message", "role": "assistant", "content": "hello"}) == "hello"
    assert accounts._gemini_text_delta({"type": "message", "role": "user", "content": "hello"}) is None
    assert accounts._gemini_text_delta({"type": "tool_use", "content": "ignored"}) is None


def test_claude_stream_parser_returns_result_errors():
    failure = accounts._claude_text_delta({
        "type": "result",
        "is_error": True,
        "result": "You've hit your session limit - resets 1:10am (Europe/Copenhagen)",
    })

    assert isinstance(failure, accounts._CliFailure)
    assert "resets 1:10am" in failure.message


@pytest.mark.anyio
async def test_claude_route_preserves_session_limit_reset(monkeypatch):
    secrets.set_secret(accounts._CLAUDE_PLAN_KEY, "connected")
    monkeypatch.setattr(accounts, "_claude_command", lambda: "claude.exe")
    monkeypatch.setattr(
        accounts,
        "claude_plan_mode_status",
        lambda: {"configured": True, "message": "connected"},
    )

    async def fake_stream(*_args, **_kwargs):
        raise accounts.CliStreamError(
            "You've hit your session limit - resets 1:10am (Europe/Copenhagen)"
        )
        yield

    monkeypatch.setattr(accounts, "_stream_cli_json", fake_stream)

    with pytest.raises(accounts.ClaudePlanUnavailable, match="resets 1:10am"):
        async for _ in accounts.stream_claude_plan(
            [{"role": "user", "content": "hello"}]
        ):
            pass


@pytest.mark.anyio
async def test_claude_route_passes_supported_reasoning_effort(monkeypatch):
    captured = {}
    secrets.set_secret(accounts._CLAUDE_PLAN_KEY, "connected")
    monkeypatch.setattr(accounts, "_claude_command", lambda: "claude.exe")
    monkeypatch.setattr(accounts, "_claude_effort_supported", lambda: True)
    monkeypatch.setattr(
        accounts,
        "claude_plan_mode_status",
        lambda: {"configured": True, "message": "connected"},
    )

    async def fake_stream(args, prompt, extract, idle_timeout=180, cwd=None):
        captured["args"] = args
        yield "reply"

    monkeypatch.setattr(accounts, "_stream_cli_json", fake_stream)
    out = [
        delta
        async for delta in accounts.stream_claude_plan(
            [{"role": "user", "content": "hello"}],
            model_id="claude_plan/opus",
            effort="xhigh",
        )
    ]

    assert out == ["reply"]
    assert captured["args"][captured["args"].index("--effort") + 1] == "xhigh"
    assert captured["args"][captured["args"].index("--model") + 1] == "claude-opus-4-8"


@pytest.mark.anyio
async def test_gemini_route_uses_plan_mode_and_stream_json(monkeypatch):
    captured = {}
    secrets.set_secret(accounts._GEMINI_PLAN_KEY, "connected")
    monkeypatch.setattr(accounts, "_gemini_command", lambda: "gemini.cmd")
    monkeypatch.setattr(accounts, "_gemini_cli_flags", lambda: (True, None))

    async def fake_stream(args, prompt, extract, idle_timeout=180, cwd=None):
        captured.update(args=args, prompt=prompt, cwd=cwd)
        yield "google reply"

    monkeypatch.setattr(accounts, "_stream_cli_json", fake_stream)
    out = [
        delta
        async for delta in accounts.stream_gemini_plan(
            [{"role": "user", "content": "hello"}],
            model_id="gemini_plan/default",
        )
    ]

    assert out == ["google reply"]
    assert captured["args"][captured["args"].index("--approval-mode") + 1] == "plan"
    assert captured["args"][captured["args"].index("--output-format") + 1] == "stream-json"
    assert captured["cwd"]


@pytest.mark.anyio
async def test_ai_routes_chatgpt_and_gemini_plan(monkeypatch):
    async def fake_chatgpt(messages, system_prompt=None, model_id=None, effort=None):
        yield "from chatgpt"

    async def fake_gemini(messages, system_prompt=None, model_id=None, effort=None):
        yield "from gemini"

    monkeypatch.setattr(accounts, "stream_chatgpt_plan", fake_chatgpt)
    monkeypatch.setattr(accounts, "stream_gemini_plan", fake_gemini)
    out1 = [d async for d in ai.stream_chat("chatgpt_plan/default", [{"role": "user", "content": "hi"}])]
    out2 = [d async for d in ai.stream_chat("gemini_plan/default", [{"role": "user", "content": "hi"}])]
    assert "".join(out1) == "from chatgpt"
    assert "".join(out2) == "from gemini"
