"""CLI account routes must always run with safe flags (architecture plan #16) and read their
fast-changing model IDs / versions from the manifest (#12)."""

from backend.providers import accounts, manifest


def test_claude_plan_args_disable_tools_and_session_persistence():
    args = accounts._claude_plan_args("claude", "claude_plan/opus", "high", "be terse", effort_supported=True)
    assert "--no-session-persistence" in args
    assert "--strict-mcp-config" in args
    assert "--disable-slash-commands" in args
    # tools are disabled (passed as an empty value right after the flag)
    assert "--tools" in args and args[args.index("--tools") + 1] == ""
    # the manifest flag for the opus variant is forwarded as the model
    assert "--model" in args and "claude-opus-4-8" in args


def test_claude_plan_args_omits_effort_when_unsupported():
    args = accounts._claude_plan_args("claude", "claude_plan/default", "high", None, effort_supported=False)
    assert "--effort" not in args


def test_codex_exec_args_are_read_only_and_ephemeral(monkeypatch):
    monkeypatch.setattr(accounts, "_codex_exec_flags", lambda: (True, True, None))
    args = accounts._codex_exec_args("codex", "/tmp/work", "/tmp/out.txt", "chatgpt_plan/default", "medium")
    assert "--ephemeral" in args
    assert "--skip-git-repo-check" in args
    assert "--ignore-user-config" in args
    assert "-s" in args and args[args.index("-s") + 1] == "read-only"
    assert "-o" in args and args[args.index("-o") + 1] == "/tmp/out.txt"


def test_codex_exec_args_force_auto_sends_no_pinned_model(monkeypatch):
    monkeypatch.setattr(accounts, "_codex_exec_flags", lambda: (True, True, None))
    args = accounts._codex_exec_args("codex", "/tmp/work", "/tmp/out.txt", "chatgpt_plan/gpt-5.5", "medium", force_auto=True)
    assert "-m" not in args  # auto route must not pin a model


def test_manifest_falls_back_to_defaults_and_has_plan_variants():
    assert manifest.variants("claude_plan")[0][0] == "claude_plan/default"
    assert manifest.recommended_version("chatgpt_plan")  # a tuple, not None
    assert manifest.value("chatgpt_plan", "codex_latest_pinned_model")
