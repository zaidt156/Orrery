"""One-click connection check: live-probe the database and every CONFIGURED model connection.

Drives the sidebar "Check connections" button. Everything runs concurrently and each probe is
individually contained — a hung or crashing probe becomes one red row, never an exception or an
unbounded wait. Security (security.md §1): every detail string is passed through the provider
layer's secret scrubber and clamped, so a provider error that echoes a key can never reach the UI;
custom endpoints are re-validated by netguard before any request is made; CLI plans use their
cheap status commands, never paid model calls.
"""
from __future__ import annotations

import asyncio
import datetime
import time
from typing import Awaitable

import httpx

from backend.core import database
from backend.features import local_models
from backend.providers import accounts, ai, catalog
from backend.security import netguard, secrets

_TIMEOUT = 8.0   # per-check ceiling; probes have their own tighter internal timeouts
_REUSE_S = 3.0   # double-clicks reuse the last result instead of stampeding CLI subprocesses

_lock = asyncio.Lock()
_last: tuple[float, dict] | None = None


async def _timed(check_id: str, label: str, probe: Awaitable) -> dict:
    start = time.perf_counter()
    try:
        ok, detail = await asyncio.wait_for(probe, _TIMEOUT)
    except asyncio.TimeoutError:
        ok, detail = False, "Timed out."
    except Exception as exc:  # noqa: BLE001 — one broken probe must not sink the run
        ok, detail = False, ai._sanitize(exc)
    ms = int((time.perf_counter() - start) * 1000)
    return {"id": check_id, "label": label, "ok": bool(ok), "detail": ai._scrub_secrets(str(detail))[:200], "ms": ms}


async def _db_probe() -> tuple[bool, str]:
    ok = await database.check_connection(force=True)
    return ok, "Connected" if ok else "Connection failed — is PostgreSQL running?"


async def _plan_probe(status_fn) -> tuple[bool, str]:
    status = await asyncio.to_thread(status_fn)
    ok = bool(status.get("configured"))
    return ok, status.get("message") or ("Connected" if ok else "Account connection is not usable right now.")


async def _ollama_probe() -> tuple[bool, str]:
    status = await local_models.status()
    if status.get("running"):
        version = status.get("version") or "?"
        return True, f"v{version} · {len(status.get('models') or [])} models"
    return False, "Installed but not running — start Ollama to use local models."


async def _custom_probe(row: dict) -> tuple[bool, str]:
    base = netguard.validate_model_base_url(row["base_url"])  # never probe an unvetted URL
    key = catalog.custom_model_key(row["custom_id"])
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(timeout=6) as c:
        r = await c.get(base.rstrip("/") + "/models", headers=headers)
    return r.status_code < 400, f"HTTP {r.status_code}"


async def _run_checks() -> list[dict]:
    tasks = [_timed("database", "PostgreSQL", _db_probe())]
    for provider in ai._KEYED:
        if secrets.get_provider_key(provider):
            label = ai.PROVIDERS.get(provider, {}).get("label", provider)
            tasks.append(_timed(provider, f"{label} API", ai.probe_provider(provider)))
    if secrets.get_secret(accounts._CLAUDE_PLAN_KEY) == "connected":
        tasks.append(_timed("claude_plan", "Claude plan (CLI)",
                            _plan_probe(lambda: accounts.claude_plan_mode_status(True))))
    if secrets.get_secret(accounts._CHATGPT_PLAN_KEY) == "connected":
        tasks.append(_timed("chatgpt_plan", "ChatGPT plan (CLI)",
                            _plan_probe(lambda: accounts.chatgpt_plan_mode_status(True))))
    if secrets.get_secret(accounts._GEMINI_PLAN_KEY) == "connected":
        tasks.append(_timed("gemini_plan", "Google account (CLI)",
                            _plan_probe(accounts.gemini_plan_mode_status)))
    if local_models._ollama_command():  # only when installed; stopped-but-installed is a real red
        tasks.append(_timed("ollama", "Ollama (local)", _ollama_probe()))
    for row in await catalog.list_custom_models():
        if row.get("configured"):
            tasks.append(_timed(f"custom:{row['custom_id']}", row.get("label") or "Custom endpoint",
                                _custom_probe(row)))
    return list(await asyncio.gather(*tasks))


async def check_all() -> dict:
    """{ok, at, checks:[{id,label,ok,detail,ms}]} — ok is true only when every check passed."""
    global _last
    async with _lock:
        if _last and time.monotonic() - _last[0] < _REUSE_S:
            return _last[1]
        checks = await _run_checks()
        result = {
            "ok": all(c["ok"] for c in checks),
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "checks": checks,
        }
        _last = (time.monotonic(), result)
        return result
