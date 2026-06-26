from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from functools import lru_cache

from backend.providers import manifest
from backend.security import secrets

CLAUDE_PLAN_MODEL_ID = "claude_plan/default"
_CLAUDE_PLAN_KEY = "account:anthropic:claude_plan"
_CLAUDE_CMD_TIMEOUT = 180
_STATUS_TIMEOUT = 8
_STATUS_CACHE_TTL = 30.0
_INSTALL_TIMEOUT = 300
# recommended CLI versions + plan variants come from the refreshable model manifest (plan #12)
_CODEX_RECOMMENDED_VERSION = manifest.recommended_version("chatgpt_plan") or (0, 141, 0)
_CLAUDE_RECOMMENDED_VERSION = manifest.recommended_version("claude_plan") or (2, 1, 185)
_install_lock = threading.Lock()

# Selectable models on the Claude plan route. "default" lets Claude Code pick;
# the others pass --model to the CLI so the user can switch tiers under OAuth.
CLAUDE_PLAN_VARIANTS = manifest.variants("claude_plan")
_CLAUDE_PLAN_FLAG = {vid: flag for vid, _label, flag in CLAUDE_PLAN_VARIANTS}
_status_cache_lock = threading.Lock()
_status_cache: tuple[float, dict] | None = None
_codex_login_cache: tuple[float, tuple[bool, str | None]] | None = None


class ClaudePlanUnavailable(Exception):
    """Raised when the official Claude plan route cannot be used safely."""


class UnsupportedClaudePlanInput(Exception):
    """Raised when a request needs capabilities not enabled for the plan route."""


def _first_command(candidates: list[str | None]) -> str | None:
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _claude_command() -> str | None:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        home = os.path.expanduser("~")
        return _first_command([
            os.path.join(local, "Microsoft", "WinGet", "Links", "claude.exe"),
            os.path.join(home, ".local", "bin", "claude.exe"),
            shutil.which("claude.exe"),
            shutil.which("claude.cmd"),
            shutil.which("claude"),
        ])
    return shutil.which("claude")


def _parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(part) for part in match.groups()) if match else None


def _command_version(cmd: str | None) -> tuple[int, int, int] | None:
    if not cmd:
        return None
    result = _run_cli_status(cmd, ["--version"])
    if result is None or result.returncode != 0:
        return None
    return _parse_version(f"{result.stdout}\n{result.stderr}")


def _version_label(version: tuple[int, int, int] | None) -> str | None:
    return ".".join(str(part) for part in version) if version else None


def _subscription_label(value: str | None) -> str:
    if not value:
        return "Claude plan"
    return f"Claude {value.title()} plan"


def _safe_claude_status(raw: dict | None) -> dict:
    raw = raw or {}
    subscription = raw.get("subscriptionType")
    logged_in = bool(raw.get("loggedIn"))
    first_party = raw.get("apiProvider") == "firstParty"
    claude_ai = raw.get("authMethod") == "claude.ai"
    plan_ready = logged_in and first_party and claude_ai and subscription not in (None, "", "free")
    return {
        "logged_in": logged_in,
        "plan_ready": plan_ready,
        "subscription": subscription if plan_ready else None,
        "preview": _subscription_label(subscription) if plan_ready else None,
    }


def _run_claude_auth_status() -> tuple[bool, dict | None, str | None]:
    cmd = _claude_command()
    if not cmd:
        return False, None, "Claude Code is not installed or is not on PATH."
    try:
        result = subprocess.run(
            [cmd, "auth", "status"],
            cwd=tempfile.gettempdir(),
            text=True,
            capture_output=True,
            timeout=_STATUS_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, None, "Claude Code did not answer quickly enough."
    except OSError:
        return False, None, "Claude Code could not be started."

    if result.returncode != 0:
        return False, None, "Sign in with Claude Code first, then connect the plan here."
    try:
        return True, json.loads(result.stdout or "{}"), None
    except json.JSONDecodeError:
        return False, None, "Claude Code returned an unreadable auth status."


@lru_cache(maxsize=1)
def _safe_cli_flags_ready() -> tuple[bool, str | None]:
    cmd = _claude_command()
    if not cmd:
        return False, "Claude Code is not installed or is not on PATH."
    try:
        result = subprocess.run(
            [cmd, "--help"],
            cwd=tempfile.gettempdir(),
            text=True,
            capture_output=True,
            timeout=_STATUS_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "Claude Code did not answer quickly enough."
    except OSError:
        return False, "Claude Code could not be started."

    help_text = f"{result.stdout}\n{result.stderr}"
    required = ("--print", "--no-session-persistence", "--tools", "--permission-mode", "--strict-mcp-config")
    missing = [flag for flag in required if flag not in help_text]
    if missing:
        return False, "This Claude Code version cannot provide Orrery's no-tools/no-session mode."
    return True, None


def clear_status_cache() -> None:
    global _status_cache, _codex_login_cache
    with _status_cache_lock:
        _status_cache = None
        _codex_login_cache = None
    for probe in (_safe_cli_flags_ready, _claude_effort_supported, _codex_exec_flags, _gemini_cli_flags):
        cache_clear = getattr(probe, "cache_clear", None)
        if cache_clear:
            cache_clear()


@lru_cache(maxsize=1)
def _claude_effort_supported() -> bool:
    cmd = _claude_command()
    if not cmd:
        return False
    try:
        result = subprocess.run(
            [cmd, "--help"],
            cwd=tempfile.gettempdir(),
            text=True,
            capture_output=True,
            timeout=_STATUS_TIMEOUT,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return "--effort" in f"{result.stdout}\n{result.stderr}"


def _claude_plan_probe(force: bool = False) -> dict:
    global _status_cache
    now = time.monotonic()
    with _status_cache_lock:
        if not force and _status_cache and now - _status_cache[0] < _STATUS_CACHE_TTL:
            return dict(_status_cache[1])

    flags_ok, flag_reason = _safe_cli_flags_ready()
    ok, raw, reason = _run_claude_auth_status() if flags_ok else (False, None, flag_reason)
    safe = _safe_claude_status(raw) if ok else _safe_claude_status(None)
    probe = {"safe": safe, "reason": reason}

    with _status_cache_lock:
        _status_cache = (now, probe)
    return dict(probe)


def _stored_claude_plan() -> bool:
    return secrets.get_secret(_CLAUDE_PLAN_KEY) == "connected"


def _set_claude_plan_connected() -> None:
    secrets.set_secret(_CLAUDE_PLAN_KEY, "connected")


def disconnect_claude_plan() -> dict:
    secrets.delete_secret(_CLAUDE_PLAN_KEY)
    return claude_plan_mode_status()


def claude_plan_mode_status(force: bool = False) -> dict:
    probe = _claude_plan_probe(force)
    safe = probe["safe"]
    reason = probe["reason"]
    cmd = _claude_command()
    version = _command_version(cmd)
    update_recommended = bool(version and version < _CLAUDE_RECOMMENDED_VERSION)
    connected = _stored_claude_plan() and safe["plan_ready"]
    status = "connected" if connected else "available" if safe["plan_ready"] else "unavailable"
    message = (
        "Ready to use Claude plan credits through official Claude Code."
        if connected
        else "Claude Code is signed in; connect it to Orrery to use this route."
        if safe["plan_ready"]
        else reason or "Sign in with an eligible Claude plan in Claude Code first."
    )
    return {
        "id": "claude_plan",
        "label": "Claude plan",
        "kind": "subscription",
        "configured": connected,
        "available": safe["plan_ready"],
        "status": status,
        "preview": safe["preview"] if connected else None,
        "message": message,
        "installed": cmd is not None,
        "authenticated": safe["logged_in"],
        "version": _version_label(version),
        "update_recommended": update_recommended,
        "can_install": os.name == "nt" and shutil.which("winget") is not None,
        "can_login": cmd is not None and not safe["logged_in"],
        "install_action": "update" if cmd else "install",
        "docs_url": "https://code.claude.com/docs/en/setup",
    }


def connect_claude_plan() -> dict:
    mode = claude_plan_mode_status(force=True)
    if not mode["available"]:
        raise ValueError(mode["message"])
    _verify_claude_ready()
    _set_claude_plan_connected()
    return claude_plan_mode_status()


def _verify_claude_ready() -> None:
    cmd = _claude_command()
    if not cmd:
        raise ValueError("Install Claude Code first.")
    args = [
        cmd,
        "--print",
        "--output-format", "json",
        "--no-session-persistence",
        "--tools", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--permission-mode", "dontAsk",
    ]
    try:
        result = subprocess.run(
            args,
            input="Reply with exactly: OK",
            cwd=tempfile.gettempdir(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Claude Code readiness check timed out.") from None
    if result.returncode == 0 and (result.stdout or "").strip():
        return
    error = f"{result.stderr}\n{result.stdout}".lower()
    if "login" in error or "auth" in error:
        raise ValueError("Claude Code needs sign-in. Choose Sign in, then check status.") from None
    if "credit" in error or "limit" in error:
        raise ValueError("Claude plan credits or limits are unavailable right now.") from None
    raise ValueError("Claude Code could not complete a safe readiness check.") from None


def provider_status(provider: str, info: dict) -> dict:
    key_status = secrets.provider_key_status(provider) if info.get("needs_key") else {"configured": True, "preview": None}
    out = {
        "label": info["label"],
        "needs_key": info["needs_key"],
        "configured": key_status["configured"],
        "preview": key_status["preview"],
        "modes": [],
    }

    if provider == "ollama":
        out["modes"].append({
            "id": "local",
            "label": "Ollama local",
            "kind": "local",
            "configured": True,
            "available": True,
            "status": "local",
            "preview": "http://localhost:11434",
            "message": "Runs on your machine; no account or key needed.",
        })
        return out

    out["modes"].append({
        "id": "api_key",
        "label": f"{info['label']} API key",
        "kind": "api_key",
        "configured": key_status["configured"],
        "available": True,
        "status": "connected" if key_status["configured"] else "not_set",
        "preview": key_status["preview"],
        "message": "Stored in your system keychain, never in files.",
    })

    if provider == "anthropic":
        out["modes"].append(claude_plan_mode_status())
    elif provider == "openai":
        out["modes"].append(chatgpt_plan_mode_status())
    elif provider == "google":
        out["modes"].append(gemini_plan_mode_status())

    return out


def providers_status(providers: dict[str, dict]) -> dict:
    return {name: provider_status(name, info) for name, info in providers.items()}


def claude_plan_model() -> dict | None:
    if not _stored_claude_plan():
        return None
    mode = claude_plan_mode_status()
    if not mode["configured"]:
        return None
    return {
        "id": CLAUDE_PLAN_MODEL_ID,
        "label": "Claude plan · default",
        "provider": "claude_plan",
        "auth_mode": "claude_plan",
    }


def claude_plan_models() -> list[dict]:
    """Selectable Claude-plan models, shown only when the plan is connected."""
    if not _stored_claude_plan():
        return []
    if not claude_plan_mode_status()["configured"]:
        return []
    return [
        {"id": vid, "label": label, "provider": "claude_plan", "auth_mode": "claude_plan"}
        for vid, label, _flag in CLAUDE_PLAN_VARIANTS
    ]


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if block.get("type") == "image_url":
                raise UnsupportedClaudePlanInput(
                    "Claude plan access in Orrery is text-first for now. Use an API-key vision model for image attachments."
                )
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(p for p in parts if p).strip()
    return str(content or "")


def _messages_to_prompt(messages: list[dict]) -> str:
    rendered = []
    for message in messages:
        role = message.get("role", "user").title()
        body = _content_to_text(message.get("content"))
        if body:
            rendered.append(f"{role}:\n{body}")
    return "\n\n".join(rendered).strip()


class CliStreamError(Exception):
    """A subprocess model route exited unsuccessfully; carries the raw stderr."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class _CliFailure:
    """Internal queue marker so the worker thread can hand a failure to the async side."""

    def __init__(self, message: str):
        self.message = message


class ReasoningChunk(str):
    """A streamed 'thinking' token from a CLI route — surfaced to the UI as reasoning, not answer."""


def _claude_text_delta(obj: dict) -> str | _CliFailure | None:
    """Pull the assistant text (and thinking) out of one Claude Code stream-json line."""
    if obj.get("type") == "stream_event":
        event = obj.get("event") or {}
        if event.get("type") == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                return delta.get("text") or None
            if delta.get("type") == "thinking_delta":  # extended-thinking tokens → show as reasoning
                thinking = delta.get("thinking") or ""
                return ReasoningChunk(thinking) if thinking else None
    if obj.get("type") == "result" and obj.get("is_error"):
        return _CliFailure(str(obj.get("result") or "Claude Code returned an error."))
    return None


async def _stream_cli_json(
    args: list[str],
    prompt: str,
    extract,
    idle_timeout: float = _CLAUDE_CMD_TIMEOUT,
    cwd: str | None = None,
) -> AsyncIterator[str]:
    """Run a JSONL-streaming CLI in a worker thread and yield text deltas as they arrive.

    Bridges the blocking subprocess to asyncio via a queue — the Windows Selector loop
    (required by psycopg async) has no native subprocess support, so we can't use
    asyncio.create_subprocess_exec. `extract(line_obj)` returns a text delta or None.
    """
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    done = object()
    holder: dict = {}

    def worker():
        produced = False
        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=cwd or tempfile.gettempdir(),
                bufsize=1,
            )
            holder["proc"] = proc
            if proc.stdin:
                proc.stdin.write(prompt)
                proc.stdin.close()
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = extract(obj)
                if delta:
                    produced = True
                    loop.call_soon_threadsafe(q.put_nowait, delta)
            err = (proc.stderr.read() if proc.stderr else "") or ""
            if proc.wait() != 0 and not produced:
                loop.call_soon_threadsafe(q.put_nowait, _CliFailure(err.strip()))
        except OSError as exc:
            loop.call_soon_threadsafe(q.put_nowait, _CliFailure(str(exc)))
        finally:
            loop.call_soon_threadsafe(q.put_nowait, done)

    threading.Thread(target=worker, daemon=True).start()
    try:
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                raise CliStreamError("the model route timed out") from None
            if item is done:
                return
            if isinstance(item, _CliFailure):
                raise CliStreamError(item.message)
            yield item
    finally:
        proc = holder.get("proc")  # kill the CLI if the caller stopped early (Stop button)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass


class ClaudePlanAdapter:
    """Official Claude Code route with tools disabled and no session persistence."""

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        model_id: str | None = None,
        effort: str | None = None,
    ) -> AsyncIterator[str]:
        async for delta in _stream_claude_plan_impl(messages, system_prompt, model_id, effort):
            yield delta


# Precise phrases only. Bare "rate"/"limit" matched ordinary words (e.g. "generate" contains
# "rate") and falsely reported "limit reached" on normal responses.
_LIMIT_KEYWORDS = (
    "rate limit", "rate-limit", "ratelimit", "usage limit", "usage cap", "quota",
    "limit reached", "limit exceeded", "exceeded your", "too many requests", "429",
    "plan limit", "you have hit", "you've hit", "usage_limit", "resets at",
)
# Phrases that begin the real limit sentence (CLI output is prefixed with startup noise we skip).
_LIMIT_SENTENCE_START = ("you've hit", "you have hit", "you've reached", "you have reached")


def _limit_text(err: str, plan: str) -> str | None:
    """A clear, actionable message if the CLI error looks like a plan usage/rate limit."""
    raw = " ".join((err or "").split())  # collapse the CLI's multi-line preamble
    low = raw.lower()
    if not any(k in low for k in _LIMIT_KEYWORDS):
        return None
    # Extract just the limit sentence — the raw output is prefixed with "Reading prompt…
    # OpenAI Codex v… workdir… model… user <prompt>" noise that must not be shown.
    for marker in (*_LIMIT_SENTENCE_START, "usage limit", "rate limit", "too many requests", "quota"):
        index = low.find(marker)
        if index < 0:
            continue
        start = index if marker in _LIMIT_SENTENCE_START else max(0, raw.rfind(". ", 0, index) + 2)
        tail = raw[start:]
        low_tail = tail.lower()
        cut = 320
        for boundary in (low_tail.find(" error", 8), low_tail.find(marker, len(marker) + 4)):
            if 0 < boundary < cut:  # stop before the CLI repeats the same message
                cut = boundary
        sentence = tail[:cut].strip(" .")
        if sentence:
            return f"{plan}: {sentence}."
    return (
        f"{plan} usage limit reached. These plans cap usage over rolling time windows "
        "and reset automatically. Wait and try again, or switch to an API-key or local model."
    )


def _claude_plan_args(
    cmd: str, model_id: str | None, effort: str | None, system_prompt: str | None, effort_supported: bool,
) -> list[str]:
    """Build the Claude Code argv with tools disabled and no session persistence (pure + testable)."""
    args = [
        cmd,
        "--print",
        "--output-format", "stream-json",  # realtime JSONL so we can stream deltas, not buffer
        "--include-partial-messages",
        "--verbose",  # required alongside stream-json
        "--no-session-persistence",
        "--tools", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--setting-sources", "user",
        "--permission-mode", "dontAsk",
    ]
    flag = _CLAUDE_PLAN_FLAG.get(model_id) if model_id else None
    if flag:
        args += ["--model", flag]
    if effort and effort in {"low", "medium", "high", "xhigh", "max"} and effort_supported:
        args += ["--effort", effort]
    if system_prompt:
        args += ["--system-prompt", system_prompt]
    return args


async def _stream_claude_plan_impl(
    messages: list[dict],
    system_prompt: str | None = None,
    model_id: str | None = None,
    effort: str | None = None,
) -> AsyncIterator[str]:
    mode = claude_plan_mode_status()
    if not mode["configured"]:
        raise ClaudePlanUnavailable(mode["message"])

    cmd = _claude_command()
    if not cmd:
        raise ClaudePlanUnavailable("Claude Code is not installed or is not on PATH.")

    prompt = _messages_to_prompt(messages)
    if not prompt:
        raise ClaudePlanUnavailable("There is no text to send to Claude plan.")

    args = _claude_plan_args(cmd, model_id, effort, system_prompt, _claude_effort_supported())

    produced = False
    try:
        async for delta in _stream_cli_json(args, prompt, _claude_text_delta):
            produced = True
            yield delta
    except CliStreamError as exc:
        raw = (exc.message or "").strip()
        if "session limit" in raw.lower():
            raise ClaudePlanUnavailable(raw) from None
        limit = _limit_text(raw, "Claude plan")
        if limit:
            raise ClaudePlanUnavailable(limit) from None
        if any(word in raw.lower() for word in ("auth", "login", "sign in", "signed out")):
            raise ClaudePlanUnavailable(
                "Claude Code is not signed in. Open Settings, sign in to Claude Code, then reconnect the Claude plan."
            ) from None
        raise ClaudePlanUnavailable("Claude plan request failed. Check Claude Code sign-in and plan status.") from None

    if not produced:
        # claude often exits 0 with no text when the rolling usage limit is hit
        raise ClaudePlanUnavailable(
            "Claude plan returned no text — this usually means the plan's usage limit was reached "
            "(it resets after a while). Try again later, or switch to an API-key or local model."
        )


async def stream_claude_plan(
    messages: list[dict],
    system_prompt: str | None = None,
    model_id: str | None = None,
    effort: str | None = None,
) -> AsyncIterator[str]:
    async for delta in ClaudePlanAdapter().stream(messages, system_prompt, model_id, effort):
        yield delta


# --- ChatGPT (Codex CLI) and Google CLI account routes ----------------------------
# These launch the user's installed first-party CLI and reuse its own saved sign-in.
# Orrery never reads, copies, or stores the CLI's OAuth/session token.

_CHATGPT_PLAN_KEY = "account:openai:chatgpt_plan"
_GEMINI_PLAN_KEY = "account:google:gemini_plan"

CHATGPT_PLAN_VARIANTS = manifest.variants("chatgpt_plan")
GEMINI_PLAN_VARIANTS = manifest.variants("gemini_plan")
_CHATGPT_PLAN_FLAG = {vid: flag for vid, _l, flag in CHATGPT_PLAN_VARIANTS}
_GEMINI_PLAN_FLAG = {vid: flag for vid, _l, flag in GEMINI_PLAN_VARIANTS}

_CODEX_LATEST_PINNED_MODEL = manifest.value("chatgpt_plan", "codex_latest_pinned_model", "gpt-5.5")
_CODEX_OLD_FAST_MODEL = manifest.value("chatgpt_plan", "codex_old_fast_model", "gpt-5.4-mini")

_CHATGPT_WARNING = (
    "Runs OpenAI's official Codex CLI in an empty temporary folder with a read-only sandbox, "
    "no approvals, and no saved Orrery session. It uses Codex/ChatGPT plan limits and can be "
    "slower than an API-key chat model. Orrery never copies the Codex login token."
)
_GEMINI_WARNING = (
    "Google ended consumer, Google AI Pro, and Google AI Ultra service through Gemini CLI on "
    "June 18, 2026 and moved those users to Antigravity CLI. This route remains for supported "
    "enterprise/API-key Gemini CLI accounts. Orrery never copies Google login tokens."
)


class CliRouteUnavailable(Exception):
    """Raised when a CLI subscription route (Codex/Gemini) cannot be used."""


def _codex_command() -> str | None:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        return _first_command([
            os.path.join(local, "Microsoft", "WinGet", "Links", "codex.exe"),
            os.path.join(local, "Programs", "OpenAI", "Codex", "bin", "codex.exe"),
            shutil.which("codex.exe"),
            shutil.which("codex.cmd"),
            shutil.which("codex"),
        ])
    return shutil.which("codex")


def _gemini_command() -> str | None:
    if os.name == "nt":
        return shutil.which("gemini.cmd") or shutil.which("gemini.exe") or shutil.which("gemini")
    return shutil.which("gemini")


def _run_cli_status(cmd: str, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            [cmd, *args], cwd=tempfile.gettempdir(), text=True,
            capture_output=True, timeout=_STATUS_TIMEOUT, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def _codex_login_status(cmd: str) -> tuple[bool, str | None]:
    # Override a stale/invalid user service_tier without changing the user's config file.
    result = _run_cli_status(cmd, ["login", "status", "-c", 'service_tier="fast"'])
    if result is None:
        return False, "Codex did not answer quickly enough."
    if result.returncode == 0:
        return True, None
    return False, "Codex is installed but not signed in. Run: codex login"


def _codex_login_probe(cmd: str, force: bool = False) -> tuple[bool, str | None]:
    global _codex_login_cache
    now = time.monotonic()
    with _status_cache_lock:
        if not force and _codex_login_cache and now - _codex_login_cache[0] < _STATUS_CACHE_TTL:
            return _codex_login_cache[1]
    result = _codex_login_status(cmd)
    with _status_cache_lock:
        _codex_login_cache = (now, result)
    return result


@lru_cache(maxsize=1)
def _codex_exec_flags() -> tuple[bool, bool, str | None]:
    cmd = _codex_command()
    if not cmd:
        return False, False, "OpenAI Codex CLI is not installed or is not on PATH."
    result = _run_cli_status(cmd, ["exec", "--help"])
    if result is None:
        return False, False, "Codex did not answer quickly enough."
    help_text = f"{result.stdout}\n{result.stderr}"
    required = ("--ephemeral", "--sandbox", "--output-last-message", "--skip-git-repo-check")
    if any(flag not in help_text for flag in required):
        return False, False, "This Codex CLI version lacks Orrery's required safe execution flags."
    return True, "--ignore-user-config" in help_text, None


@lru_cache(maxsize=1)
def _gemini_cli_flags() -> tuple[bool, str | None]:
    cmd = _gemini_command()
    if not cmd:
        return False, "Gemini CLI is not installed or is not on PATH."
    result = _run_cli_status(cmd, ["--help"])
    if result is None:
        return False, "Gemini CLI did not answer quickly enough."
    help_text = f"{result.stdout}\n{result.stderr}"
    required = ("--prompt", "--output-format", "--approval-mode")
    if any(flag not in help_text for flag in required):
        return False, "This Gemini CLI version lacks Orrery's required read-only headless flags."
    return True, None


_CLI_PACKAGES = {
    "claude_plan": {
        "package_id": "Anthropic.ClaudeCode",
        "label": "Claude Code",
        "login_args": ["auth", "login"],
    },
    "chatgpt_plan": {
        "package_id": "OpenAI.Codex",
        "label": "OpenAI Codex CLI",
        "login_args": ["login"],
    },
}


def _plan_mode_status(mode_id: str, force: bool = False) -> dict:
    if mode_id == "claude_plan":
        return claude_plan_mode_status(force)
    if mode_id == "chatgpt_plan":
        return chatgpt_plan_mode_status(force)
    raise ValueError("This account route does not support local CLI setup.")


def _plan_command(mode_id: str) -> str | None:
    if mode_id == "claude_plan":
        return _claude_command()
    if mode_id == "chatgpt_plan":
        return _codex_command()
    return None


def _winget_package_installed(winget: str, package_id: str) -> bool:
    result = subprocess.run(
        [
            winget, "list", "--id", package_id, "--exact", "--source", "winget",
            "--accept-source-agreements", "--disable-interactivity",
        ],
        cwd=tempfile.gettempdir(),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=_STATUS_TIMEOUT * 3,
        check=False,
    )
    return result.returncode == 0 and package_id.lower() in (result.stdout or "").lower()


def install_plan_cli(mode_id: str, acknowledged: bool = False) -> dict:
    """Install or update a supported first-party CLI through fixed WinGet package ids."""
    if not acknowledged:
        raise ValueError("Confirm the official CLI installation before continuing.")
    config = _CLI_PACKAGES.get(mode_id)
    if config is None:
        raise ValueError("This account route does not support one-click installation.")
    if os.name != "nt":
        raise ValueError("One-click CLI installation is currently available on Windows.")
    winget = shutil.which("winget")
    if not winget:
        raise ValueError("Windows Package Manager (winget) is required for one-click installation.")
    if not _install_lock.acquire(blocking=False):
        raise ValueError("Another CLI installation is already running.")

    try:
        package_id = config["package_id"]
        action = "upgrade" if _winget_package_installed(winget, package_id) else "install"
        result = subprocess.run(
            [
                winget, action, "--id", package_id, "--exact", "--source", "winget",
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity", "--silent",
            ],
            cwd=tempfile.gettempdir(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=_INSTALL_TIMEOUT,
            check=False,
        )
        output = f"{result.stdout}\n{result.stderr}".lower()
        no_update = "no available upgrade" in output or "no newer package versions" in output
        if result.returncode != 0 and not no_update:
            raise ValueError(
                f"{config['label']} installation failed. Open its official setup guide and try again."
            )
    except subprocess.TimeoutExpired:
        raise ValueError(f"{config['label']} installation timed out.") from None
    finally:
        _install_lock.release()

    clear_status_cache()
    status = _plan_mode_status(mode_id, force=True)
    if not status.get("installed"):
        raise ValueError(
            f"{config['label']} was installed, but Orrery cannot find it yet. Restart Orrery and check again."
        )
    return status


def launch_plan_login(mode_id: str) -> dict:
    """Open the first-party CLI login in a separate console without reading its credentials."""
    config = _CLI_PACKAGES.get(mode_id)
    cmd = _plan_command(mode_id)
    if config is None or not cmd:
        raise ValueError("Install the official CLI before signing in.")
    creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    try:
        subprocess.Popen(
            [cmd, *config["login_args"]],
            cwd=tempfile.gettempdir(),
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError:
        raise ValueError(f"Could not open {config['label']} sign-in.") from None
    clear_status_cache()
    return {
        "started": True,
        "message": f"Complete {config['label']} sign-in in the opened window, then check status.",
    }


def refresh_plan_mode(mode_id: str) -> dict:
    clear_status_cache()
    return _plan_mode_status(mode_id, force=True)


def chatgpt_plan_mode_status(force: bool = False) -> dict:
    cmd = _codex_command()
    installed = cmd is not None
    version = _command_version(cmd)
    update_recommended = bool(version and version < _CODEX_RECOMMENDED_VERSION)
    flags_ok, config_isolated, flags_reason = _codex_exec_flags() if installed else (False, False, None)
    logged_in, login_reason = _codex_login_probe(cmd, force) if installed and flags_ok else (False, None)
    available = installed and flags_ok and logged_in
    connected = secrets.get_secret(_CHATGPT_PLAN_KEY) == "connected" and available
    status = "connected" if connected else "available" if available else "unavailable"
    if connected and update_recommended:
        message = (
            "Using your Codex/ChatGPT plan through Codex CLI. This older CLI will auto-select "
            "its best compatible model; update Codex to unlock the newest GPT model pins."
        )
    elif connected:
        message = "Using your Codex/ChatGPT plan through the official local Codex CLI."
    elif available:
        message = "Codex is signed in. Connect it to use this official CLI route in Orrery."
    elif installed:
        message = flags_reason or login_reason or "Codex is installed but unavailable."
    else:
        message = "Install OpenAI's Codex CLI and run 'codex login' to use your ChatGPT plan."
    return {
        "id": "chatgpt_plan", "label": "Codex / ChatGPT plan", "kind": "subscription",
        "configured": connected, "available": available, "status": status,
        "preview": "Codex CLI" if connected else None, "message": message,
        "warning": (
            _CHATGPT_WARNING
            if config_isolated
            else _CHATGPT_WARNING
            + " This installed Codex version still loads your normal CLI configuration, so configured plugins or MCP servers may initialize."
        ),
        "requires_acknowledgement": True,
        "config_isolated": config_isolated,
        "installed": installed,
        "authenticated": logged_in,
        "version": _version_label(version),
        "update_recommended": update_recommended,
        "can_install": os.name == "nt" and shutil.which("winget") is not None,
        "can_login": installed and not logged_in,
        "install_action": "update" if installed else "install",
        "model_strategy": (
            "Default ChatGPT-plan chats let Codex choose the newest model this installed CLI supports."
        ),
        "docs_url": "https://developers.openai.com/codex/noninteractive/",
    }


def gemini_plan_mode_status() -> dict:
    cmd = _gemini_command()
    installed = cmd is not None
    flags_ok, flags_reason = _gemini_cli_flags() if installed else (False, None)
    available = installed and flags_ok
    connected = secrets.get_secret(_GEMINI_PLAN_KEY) == "connected" and available
    status = "connected" if connected else "available" if available else "unavailable"
    if connected:
        message = "Using a supported Google account through the official local Gemini CLI."
    elif available:
        message = "Gemini CLI found. Consumer/Pro/Ultra users must use Antigravity after June 18, 2026."
    elif installed:
        message = flags_reason or "Gemini CLI is installed but cannot provide Orrery's safe headless mode."
    else:
        message = (
            "Gemini CLI not found. Consumer/Pro/Ultra access moved to Antigravity CLI on June 18, "
            "2026; Orrery will add that route when Google documents a stable headless interface."
        )
    return {
        "id": "gemini_plan", "label": "Google account (Gemini CLI)", "kind": "subscription",
        "configured": connected, "available": available, "status": status,
        "preview": "Gemini CLI" if connected else None, "message": message,
        "warning": _GEMINI_WARNING,
        "requires_acknowledgement": True,
        "installed": installed,
        "authenticated": available,
        "version": _version_label(_command_version(cmd)),
        "update_recommended": False,
        "can_install": False,
        "can_login": False,
        "docs_url": "https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/",
    }


def connect_chatgpt_plan(acknowledged: bool = False) -> dict:
    if not acknowledged:
        raise ValueError("Confirm the Codex CLI notice before connecting this route.")
    mode = chatgpt_plan_mode_status(force=True)
    if not mode["available"]:
        raise ValueError(mode["message"])
    _verify_codex_ready()
    secrets.set_secret(_CHATGPT_PLAN_KEY, "connected")
    return chatgpt_plan_mode_status()


def disconnect_chatgpt_plan() -> dict:
    secrets.delete_secret(_CHATGPT_PLAN_KEY)
    return chatgpt_plan_mode_status()


def connect_gemini_plan(acknowledged: bool = False) -> dict:
    if not acknowledged:
        raise ValueError("Confirm the Google CLI notice before connecting this route.")
    mode = gemini_plan_mode_status()
    if not mode["available"]:
        raise ValueError(mode["message"])
    secrets.set_secret(_GEMINI_PLAN_KEY, "connected")
    return gemini_plan_mode_status()


def disconnect_gemini_plan() -> dict:
    secrets.delete_secret(_GEMINI_PLAN_KEY)
    return gemini_plan_mode_status()


def chatgpt_plan_models() -> list[dict]:
    """Selectable ChatGPT-plan models — only when connected (no CLI probe before that)."""
    if secrets.get_secret(_CHATGPT_PLAN_KEY) != "connected":
        return []
    if not chatgpt_plan_mode_status()["configured"]:
        return []
    return [
        {"id": vid, "label": label, "provider": "chatgpt_plan", "auth_mode": "chatgpt_plan"}
        for vid, label, _flag in _chatgpt_plan_variants()
    ]


def _codex_can_pin_latest(cmd: str | None = None) -> bool:
    version = _command_version(cmd or _codex_command())
    return bool(version and version >= _CODEX_RECOMMENDED_VERSION)


def _chatgpt_plan_variants() -> list[tuple[str, str, str | None]]:
    cmd = _codex_command()
    can_pin_latest = _codex_can_pin_latest(cmd) if cmd else False
    out: list[tuple[str, str, str | None]] = []
    for vid, label, flag in CHATGPT_PLAN_VARIANTS:
        if flag == _CODEX_LATEST_PINNED_MODEL and not can_pin_latest:
            continue
        out.append((vid, label, flag))
    return out


def gemini_plan_models() -> list[dict]:
    if secrets.get_secret(_GEMINI_PLAN_KEY) != "connected":
        return []
    if not gemini_plan_mode_status()["configured"]:
        return []
    return [
        {"id": vid, "label": label, "provider": "gemini_plan", "auth_mode": "gemini_plan"}
        for vid, label, _flag in GEMINI_PLAN_VARIANTS
    ]


def _run_cli_capture(args: list[str], prompt: str, timeout: float = _CLAUDE_CMD_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, input=prompt, cwd=tempfile.gettempdir(), text=True,
        encoding="utf-8", capture_output=True, timeout=timeout, check=False,
    )


def _run_codex(args: list[str], prompt: str, outfile: str) -> str:
    result = _run_cli_capture(args, prompt)
    if result.returncode != 0:
        raise CliStreamError((result.stderr or result.stdout or "").strip())
    try:
        with open(outfile, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return (result.stdout or "").strip()


def _codex_model_flag(model_id: str | None, cmd: str, config_isolated: bool = True) -> str | None:
    if not model_id or model_id == "chatgpt_plan/default":
        return None if config_isolated else _CODEX_OLD_FAST_MODEL
    flag = _CHATGPT_PLAN_FLAG.get(model_id)
    if flag == _CODEX_LATEST_PINNED_MODEL and not _codex_can_pin_latest(cmd):
        return None if config_isolated else _CODEX_OLD_FAST_MODEL
    return flag or None


def _codex_exec_args(
    cmd: str,
    workdir: str,
    outfile: str,
    model_id: str | None,
    effort: str | None,
    force_auto: bool = False,
) -> list[str]:
    flags_ok, config_isolated, reason = _codex_exec_flags()
    if not flags_ok:
        raise CliRouteUnavailable(reason or "Codex CLI cannot provide Orrery's safe execution mode.")
    args = [cmd, "exec"]
    if config_isolated:
        args.append("--ignore-user-config")
    args += [
        "-c", 'service_tier="fast"',
        # default to real reasoning (not "low") so GPT doesn't answer shallowly; the chat
        # effort selector (low/medium/high/xhigh) overrides this per conversation
        "-c", f'model_reasoning_effort="{effort or "medium"}"',
        "--ephemeral",
        "-s", "read-only",
        "--skip-git-repo-check",
        "-C", workdir,
        "--color", "never",
        "-o", outfile,
    ]
    model_flag = None if force_auto else _codex_model_flag(model_id, cmd, config_isolated)
    if model_flag:
        args += ["-m", model_flag]
    return args


def _codex_model_mismatch_error(raw: str) -> bool:
    low = (raw or "").lower()
    if "requires a newer version of codex" in low or "upgrade to the latest app or cli" in low:
        return True
    if "unknown model" in low or "unsupported model" in low or "model not found" in low:
        return True
    return "model" in low and ("unavailable" in low or "not supported" in low or "invalid" in low)


def _codex_should_retry_auto(model_id: str | None, raw: str, args: list[str] | None = None) -> bool:
    if not _codex_model_mismatch_error(raw):
        return False
    if model_id and model_id != "chatgpt_plan/default":
        return True
    return bool(args and "-m" in args)


def _friendly_codex_error(raw: str) -> str:
    low = (raw or "").lower()
    if "requires a newer version of codex" in low or "upgrade to the latest app or cli" in low:
        return (
            "Codex is signed in but too old for this pinned model. Orrery's default ChatGPT-plan "
            "model uses Codex auto-selection; update Codex in Settings to unlock the newest model pin."
        )
    if _codex_model_mismatch_error(raw):
        return (
            "Codex rejected that pinned model. Pick the default ChatGPT-plan model so Codex can "
            "auto-select the newest compatible GPT model, or update Codex in Settings."
        )
    if "not logged in" in low or "login" in low and ("required" in low or "expired" in low):
        return "Codex needs sign-in. Open Settings, choose Sign in, then check status."
    if "rate limit" in low or "usage limit" in low or "quota" in low:
        return "Your Codex/ChatGPT plan limit is unavailable right now."
    if "required" in low and ("mcp" in low or "plugin" in low):
        return "A required Codex plugin or MCP server failed. Update Codex or disable that required integration."
    return "Codex request failed. Check sign-in, update the CLI, and retry from Settings."


def _verify_codex_ready() -> None:
    cmd = _codex_command()
    if not cmd:
        raise ValueError("Install OpenAI Codex CLI first.")
    workdir = tempfile.mkdtemp(prefix="orrery_codex_check_")
    outfile = os.path.join(workdir, "last.txt")
    try:
        args = _codex_exec_args(cmd, workdir, outfile, "chatgpt_plan/default", "low")
        text = _run_codex(args, "Reply with exactly: OK", outfile)
        if not text.strip():
            raise ValueError("Codex returned an empty readiness check.")
    except subprocess.TimeoutExpired:
        raise ValueError("Codex readiness check timed out.") from None
    except CliStreamError as exc:
        raise ValueError(_friendly_codex_error(exc.message)) from None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _gemini_text_delta(obj: dict) -> str | None:
    if obj.get("type") != "message" or obj.get("role") != "assistant":
        return None
    content = obj.get("content")
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "".join(parts) or None
    return None


async def stream_chatgpt_plan(
    messages: list[dict],
    system_prompt: str | None = None,
    model_id: str | None = None,
    effort: str | None = None,
) -> AsyncIterator[str]:
    cmd = _codex_command()
    if not cmd or secrets.get_secret(_CHATGPT_PLAN_KEY) != "connected":
        raise CliRouteUnavailable("ChatGPT plan (Codex CLI) is not connected.")
    prompt = _messages_to_prompt(messages)  # raises UnsupportedClaudePlanInput on images
    if not prompt:
        raise CliRouteUnavailable("There is no text to send.")
    if system_prompt:
        prompt = f"{system_prompt}\n\n{prompt}"  # codex exec has no system-prompt flag
    workdir = tempfile.mkdtemp(prefix="orrery_codex_")
    outfile = os.path.join(workdir, "last.txt")
    args = _codex_exec_args(cmd, workdir, outfile, model_id, effort)
    try:
        text = await asyncio.to_thread(_run_codex, args, prompt, outfile)
    except subprocess.TimeoutExpired:
        raise CliRouteUnavailable("ChatGPT plan request timed out.") from None
    except CliStreamError as exc:
        if _codex_should_retry_auto(model_id, exc.message, args):
            try:
                args = _codex_exec_args(cmd, workdir, outfile, "chatgpt_plan/default", effort, force_auto=True)
                text = await asyncio.to_thread(_run_codex, args, prompt, outfile)
            except subprocess.TimeoutExpired:
                raise CliRouteUnavailable("ChatGPT plan request timed out.") from None
            except CliStreamError as retry_exc:
                limit = _limit_text(retry_exc.message or "", "ChatGPT plan")
                raise CliRouteUnavailable(limit or _friendly_codex_error(retry_exc.message)) from None
        else:
            limit = _limit_text(exc.message or "", "ChatGPT plan")
            raise CliRouteUnavailable(limit or _friendly_codex_error(exc.message)) from None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if not text.strip():
        raise CliRouteUnavailable("ChatGPT plan returned an empty response.")
    yield text


async def stream_gemini_plan(
    messages: list[dict],
    system_prompt: str | None = None,
    model_id: str | None = None,
    effort: str | None = None,
) -> AsyncIterator[str]:
    cmd = _gemini_command()
    if not cmd or secrets.get_secret(_GEMINI_PLAN_KEY) != "connected":
        raise CliRouteUnavailable("Gemini plan (Gemini CLI) is not connected.")
    prompt = _messages_to_prompt(messages)
    if not prompt:
        raise CliRouteUnavailable("There is no text to send.")
    if system_prompt:
        prompt = f"{system_prompt}\n\n{prompt}"
    flags_ok, reason = _gemini_cli_flags()
    if not flags_ok:
        raise CliRouteUnavailable(reason or "Gemini CLI cannot provide Orrery's safe headless mode.")
    workdir = tempfile.mkdtemp(prefix="orrery_gemini_")
    args = [
        cmd,
        "--prompt", prompt,
        "--output-format", "stream-json",
        "--approval-mode", "plan",
    ]
    flag = _GEMINI_PLAN_FLAG.get(model_id) if model_id else None
    if flag:
        args += ["-m", flag]
    produced = False
    try:
        async for delta in _stream_cli_json(args, "", _gemini_text_delta, cwd=workdir):
            produced = True
            yield delta
    except CliStreamError as exc:
        limit = _limit_text(exc.message or "", "Gemini plan")
        raise CliRouteUnavailable(
            limit or "Google CLI request failed. Consumer/Pro/Ultra users must migrate to Antigravity CLI."
        ) from None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if not produced:
        raise CliRouteUnavailable("Gemini plan returned an empty response.")
