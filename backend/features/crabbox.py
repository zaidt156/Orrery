"""Optional Crabbox executor integration.

Orrery never bundles Crabbox and never stores Crabbox provider secrets. This module only keeps
non-secret preferences, checks the local CLI with non-mutating commands, and runs Crabbox when both
the admin/user feature gate and the user's Crabbox settings allow it.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.core import appconfig
from backend.security.secrets import redact_secrets

_SETTINGS_KEY = "crabbox"
_ROOT = Path(__file__).resolve().parents[2]
_MAX_OUTPUT_CHARS = 12_000
_MAX_COMMAND_ARGS = 48
_MAX_ARG_CHARS = 1_000


class CrabboxSettings(BaseModel):
    enabled: bool = False
    cli_path: str = Field(default="", max_length=400)
    provider: str = Field(default="", max_length=80)
    profile: str = Field(default="", max_length=120)
    target: str = Field(default="", pattern=r"^(|linux|macos|windows)$")
    windows_mode: str = Field(default="", pattern=r"^(|normal|wsl2)$")
    static_host: str = Field(default="", max_length=240)
    static_user: str = Field(default="", max_length=120)
    static_port: str = Field(default="", max_length=8)
    static_work_root: str = Field(default="", max_length=260)
    lease_id: str = Field(default="", max_length=120)
    timeout_seconds: int = Field(default=600, ge=10, le=7200)

    @field_validator(
        "cli_path", "provider", "profile", "target", "windows_mode",
        "static_host", "static_user", "static_port", "static_work_root", "lease_id",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, value: Any) -> str:
        return str(value or "").strip()


def default_settings() -> dict[str, Any]:
    return CrabboxSettings().model_dump()


async def get_settings() -> CrabboxSettings:
    saved = await appconfig.get_setting(_SETTINGS_KEY, default_settings()) or {}
    try:
        return CrabboxSettings.model_validate(saved)
    except Exception:  # noqa: BLE001 - bad stored shape should not break the app
        return CrabboxSettings()


async def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    settings = CrabboxSettings.model_validate(data).model_dump()
    await appconfig.set_setting(_SETTINGS_KEY, settings)
    return settings


def _resolve_cli(settings: CrabboxSettings) -> str | None:
    if settings.cli_path:
        path = Path(settings.cli_path)
        if path.is_file():
            return str(path)
        found = shutil.which(settings.cli_path)
        return found or settings.cli_path
    return shutil.which("crabbox")


def _option_args(settings: CrabboxSettings, *, include_profile: bool = True) -> list[str]:
    args: list[str] = []
    if include_profile and settings.profile:
        args += ["--profile", settings.profile]
    if settings.provider:
        args += ["--provider", settings.provider]
    if settings.target:
        args += ["--target", settings.target]
    if settings.windows_mode:
        args += ["--windows-mode", settings.windows_mode]
    if settings.static_host:
        args += ["--static-host", settings.static_host]
    if settings.static_user:
        args += ["--static-user", settings.static_user]
    if settings.static_port:
        args += ["--static-port", settings.static_port]
    if settings.static_work_root:
        args += ["--static-work-root", settings.static_work_root]
    return args


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value[:200]]
    if isinstance(value, str):
        return redact_secrets(value)[:_MAX_OUTPUT_CHARS]
    return value


def _run_process(argv: list[str], *, timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd or _ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


async def _run(argv: list[str], *, timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(_run_process, argv, timeout=timeout, cwd=cwd)


async def _version(cli: str) -> str | None:
    try:
        completed = await _run([cli, "--version"], timeout=10)
    except Exception:  # noqa: BLE001
        return None
    text = (completed.stdout or completed.stderr or "").strip()
    return redact_secrets(text)[:200] if text else None


async def _doctor(cli: str, settings: CrabboxSettings) -> dict[str, Any]:
    argv = [cli, "doctor", "--json", *_option_args(settings)]
    try:
        completed = await _run(argv, timeout=30)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "crabbox doctor timed out."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": redact_secrets(str(exc))[:300]}

    raw = (completed.stdout or "").strip()
    parsed: Any = None
    if raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
    payload: dict[str, Any] = {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
    }
    if parsed is not None:
        payload["json"] = _redact(parsed)
    else:
        payload["stdout"] = redact_secrets(raw)[:_MAX_OUTPUT_CHARS]
        payload["stderr"] = redact_secrets(completed.stderr or "")[:_MAX_OUTPUT_CHARS]
    return payload


async def status() -> dict[str, Any]:
    settings = await get_settings()
    cli = _resolve_cli(settings)
    installed = bool(cli and (Path(cli).is_file() or shutil.which(cli)))
    version = await _version(cli) if cli and installed else None
    doctor = await _doctor(cli, settings) if cli else {"ok": False, "error": "Crabbox CLI was not found."}
    return {
        "enabled": settings.enabled,
        "installed": installed,
        "configured": bool(settings.enabled and cli and doctor.get("ok")),
        "cli_path": cli or "",
        "version": version,
        "settings": settings.model_dump(),
        "doctor": doctor,
        "guidance": (
            "Install Crabbox, configure its provider/profile outside Orrery, then enable this executor. "
            "Orrery stores only non-secret preferences; Crabbox owns its tokens and provider credentials."
        ),
    }


def _validate_run_request(command: list[str], shell: str) -> tuple[list[str], str]:
    cmd = [str(part).strip() for part in (command or []) if str(part).strip()]
    shell = str(shell or "").strip()
    if bool(cmd) == bool(shell):
        raise ValueError("Provide either command argv or shell text, not both.")
    if len(cmd) > _MAX_COMMAND_ARGS:
        raise ValueError("Crabbox command has too many arguments.")
    for part in cmd:
        if "\x00" in part or len(part) > _MAX_ARG_CHARS:
            raise ValueError("Crabbox command contains an invalid argument.")
    if "\x00" in shell or len(shell) > 8_000:
        raise ValueError("Crabbox shell text is invalid or too large.")
    return cmd, shell


async def run_command(
    *,
    command: list[str] | None = None,
    shell: str = "",
    label: str = "",
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    settings = await get_settings()
    if not settings.enabled:
        raise RuntimeError("Crabbox is disabled. Enable it in settings before running remote commands.")
    cli = _resolve_cli(settings)
    if not cli:
        raise RuntimeError("Crabbox CLI was not found. Install it or set the Crabbox path in settings.")
    cmd, shell_text = _validate_run_request(command or [], shell)

    argv = [cli, "run", *_option_args(settings)]
    if settings.lease_id:
        argv += ["--id", settings.lease_id]
    if label:
        argv += ["--label", str(label)[:120]]
    if shell_text:
        argv += ["--shell", shell_text]
    else:
        argv += ["--", *cmd]

    timeout = int(timeout_seconds or settings.timeout_seconds)
    timeout = max(10, min(timeout, 7200))
    try:
        completed = await _run(argv, timeout=timeout)
        return {
            "exit_code": completed.returncode,
            "timed_out": False,
            "stdout": redact_secrets(completed.stdout or "")[:_MAX_OUTPUT_CHARS],
            "stderr": redact_secrets(completed.stderr or "")[:_MAX_OUTPUT_CHARS],
        }
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        return {
            "exit_code": -1,
            "timed_out": True,
            "stdout": redact_secrets(stdout)[:_MAX_OUTPUT_CHARS],
            "stderr": (redact_secrets(stderr) + f"\nCrabbox run exceeded {timeout}s and was stopped.")[:_MAX_OUTPUT_CHARS],
        }
