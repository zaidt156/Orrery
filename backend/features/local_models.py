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

import httpx

from backend.providers import ai, catalog

OLLAMA_BASE = "http://127.0.0.1:11434"
OLLAMA_PACKAGE_ID = "Ollama.Ollama"
_INSTALL_TIMEOUT = 600
_MODEL_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}(?::[A-Za-z0-9][A-Za-z0-9._-]{0,40})?$")
_install_lock = threading.Lock()

# A broad, current catalog of popular open-weight models on the Ollama library, across
# sizes (tier: tiny ≤2GB, small ~2-6GB, medium ~6-25GB, large 25GB+). Users can also pull
# any other valid model name from ollama.com/library via the search box (free-form pull).
CURATED_MODELS = [
    # --- tiny / fast (run on modest laptops) ---
    {"name": "llama3.2:1b", "label": "Llama 3.2 1B", "tier": "tiny", "size": "about 1.3 GB",
     "description": "Tiny, very fast assistant for quick chat on low-end hardware.", "capabilities": ["chat", "fast"]},
    {"name": "gemma3:1b", "label": "Gemma 3 1B", "tier": "tiny", "size": "about 0.8 GB",
     "description": "Google's smallest Gemma 3 — lightweight general chat.", "capabilities": ["chat", "fast"]},
    {"name": "qwen3:1.7b", "label": "Qwen 3 1.7B", "tier": "tiny", "size": "about 1.4 GB",
     "description": "Compact multilingual model with reasoning toggle.", "capabilities": ["chat", "reasoning", "multilingual"]},
    {"name": "deepseek-r1:1.5b", "label": "DeepSeek R1 1.5B", "tier": "tiny", "size": "about 1.1 GB",
     "description": "Smallest DeepSeek R1 reasoning distill.", "capabilities": ["reasoning"]},
    # --- small (a great default range) ---
    {"name": "llama3.2:3b", "label": "Llama 3.2 3B", "tier": "small", "size": "about 2.0 GB",
     "description": "Fast, lightweight everyday assistant.", "capabilities": ["chat", "fast"]},
    {"name": "qwen3:4b", "label": "Qwen 3 4B", "tier": "small", "size": "about 2.5 GB",
     "description": "Balanced local chat and multilingual reasoning.", "capabilities": ["chat", "reasoning", "multilingual"]},
    {"name": "gemma3:4b", "label": "Gemma 3 4B", "tier": "small", "size": "about 3.3 GB",
     "description": "Compact general model with vision support.", "capabilities": ["chat", "vision", "multilingual"]},
    {"name": "phi4-mini", "label": "Phi-4 Mini", "tier": "small", "size": "about 2.5 GB",
     "description": "Microsoft's small, capable reasoning-focused model.", "capabilities": ["chat", "reasoning"]},
    {"name": "qwen2.5-coder:7b", "label": "Qwen2.5 Coder 7B", "tier": "small", "size": "about 4.7 GB",
     "description": "Strong local coding model for code completion and review.", "capabilities": ["code"]},
    {"name": "mistral:7b", "label": "Mistral 7B", "tier": "small", "size": "about 4.1 GB",
     "description": "Popular, reliable general-purpose 7B.", "capabilities": ["chat"]},
    {"name": "deepseek-r1:8b", "label": "DeepSeek R1 8B", "tier": "small", "size": "about 5.2 GB",
     "description": "Local reasoning model for harder tasks.", "capabilities": ["reasoning", "code"]},
    {"name": "llava:7b", "label": "LLaVA 7B (vision)", "tier": "small", "size": "about 4.7 GB",
     "description": "Vision-language model — describe and reason over images.", "capabilities": ["vision", "chat"]},
    # --- medium (need a strong GPU / lots of RAM) ---
    {"name": "qwen3:14b", "label": "Qwen 3 14B", "tier": "medium", "size": "about 9 GB",
     "description": "Higher-quality multilingual reasoning.", "capabilities": ["chat", "reasoning", "multilingual"]},
    {"name": "gemma3:12b", "label": "Gemma 3 12B", "tier": "medium", "size": "about 8 GB",
     "description": "Larger Gemma 3 with vision; better quality.", "capabilities": ["chat", "vision"]},
    {"name": "phi4", "label": "Phi-4 14B", "tier": "medium", "size": "about 9 GB",
     "description": "Microsoft Phi-4 — strong reasoning at 14B.", "capabilities": ["chat", "reasoning"]},
    {"name": "deepseek-r1:14b", "label": "DeepSeek R1 14B", "tier": "medium", "size": "about 9 GB",
     "description": "Mid-size DeepSeek R1 reasoning.", "capabilities": ["reasoning", "code"]},
    {"name": "qwen2.5-coder:32b", "label": "Qwen2.5 Coder 32B", "tier": "medium", "size": "about 20 GB",
     "description": "Top open coding model; needs a strong GPU.", "capabilities": ["code"]},
    # --- large (workstation / multi-GPU) ---
    {"name": "gemma3:27b", "label": "Gemma 3 27B", "tier": "large", "size": "about 17 GB",
     "description": "Largest Gemma 3 — high quality, vision-capable.", "capabilities": ["chat", "vision"]},
    {"name": "qwen3:32b", "label": "Qwen 3 32B", "tier": "large", "size": "about 20 GB",
     "description": "Large Qwen 3 for demanding tasks.", "capabilities": ["chat", "reasoning"]},
    {"name": "mixtral:8x7b", "label": "Mixtral 8x7B", "tier": "large", "size": "about 26 GB",
     "description": "Mixture-of-experts; strong general quality.", "capabilities": ["chat"]},
    {"name": "llama3.3:70b", "label": "Llama 3.3 70B", "tier": "large", "size": "about 43 GB",
     "description": "Flagship open Llama; needs a lot of memory.", "capabilities": ["chat", "reasoning"]},
    {"name": "deepseek-r1:70b", "label": "DeepSeek R1 70B", "tier": "large", "size": "about 43 GB",
     "description": "Large DeepSeek R1 reasoning model.", "capabilities": ["reasoning", "code"]},
]
_CURATED_NAMES = {item["name"] for item in CURATED_MODELS}


def _ollama_command() -> str | None:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", "")
        candidates = [
            os.path.join(local, "Programs", "Ollama", "ollama.exe"),
            os.path.join(program_files, "Ollama", "ollama.exe"),
            shutil.which("ollama.exe"),
            shutil.which("ollama"),
        ]
        return next((path for path in candidates if path and os.path.isfile(path)), None)
    return shutil.which("ollama")


def _validate_model_name(model: str, curated_only: bool = False) -> str:
    name = (model or "").strip()
    if not _MODEL_RX.fullmatch(name):
        raise ValueError("Invalid Ollama model name.")
    if curated_only and name not in _CURATED_NAMES:
        raise ValueError("Choose a model from Orrery's reviewed one-click list.")
    return name


async def _server_info() -> tuple[bool, str | None, list[dict]]:
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            version_response, tags_response = await asyncio.gather(
                client.get(f"{OLLAMA_BASE}/api/version"),
                client.get(f"{OLLAMA_BASE}/api/tags"),
            )
            version_response.raise_for_status()
            tags_response.raise_for_status()
        version = version_response.json().get("version")
        return True, version, tags_response.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return False, None, []


def _model_info(raw: dict, active: set[str]) -> dict:
    name = raw.get("name") or raw.get("model") or ""
    return {
        "name": name,
        "id": f"ollama/{name}",
        "size": int(raw.get("size") or 0),
        "digest": str(raw.get("digest") or "")[:16],
        "modified_at": raw.get("modified_at"),
        "active": f"ollama/{name}" in active,
    }


async def status() -> dict:
    command = _ollama_command()
    running, version, raw_models = await _server_info()
    active = await catalog.active_ids()
    installed_names = {m.get("name") or m.get("model") for m in raw_models}
    curated = [
        {**item, "installed": item["name"] in installed_names, "active": f"ollama/{item['name']}" in active}
        for item in CURATED_MODELS
    ]
    return {
        "installed": command is not None,
        "running": running,
        "version": version,
        "can_install": os.name == "nt" and shutil.which("winget") is not None,
        "models": [_model_info(item, active) for item in raw_models],
        "curated": curated,
    }


def install(acknowledged: bool = False) -> None:
    if not acknowledged:
        raise ValueError("Confirm the official Ollama installation before continuing.")
    if os.name != "nt":
        raise ValueError("One-click Ollama installation is currently available on Windows.")
    winget = shutil.which("winget")
    if not winget:
        raise ValueError("Windows Package Manager (winget) is required for one-click installation.")
    if not _install_lock.acquire(blocking=False):
        raise ValueError("An Ollama installation is already running.")
    try:
        result = subprocess.run(
            [
                winget, "install", "--id", OLLAMA_PACKAGE_ID, "--exact", "--source", "winget",
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
        already = "already installed" in output or "no available upgrade" in output
        if result.returncode != 0 and not already:
            raise ValueError("Ollama installation failed. Use the official Windows installer and retry.")
    except subprocess.TimeoutExpired:
        raise ValueError("Ollama installation timed out.") from None
    finally:
        _install_lock.release()


async def start() -> dict:
    current = await status()
    if current["running"]:
        return current
    cmd = _ollama_command()
    if not cmd:
        raise ValueError("Install Ollama before starting the local model service.")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [cmd, "serve"],
            cwd=tempfile.gettempdir(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError:
        raise ValueError("Ollama could not be started.") from None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        running, _version, _models = await _server_info()
        if running:
            ai.clear_model_cache("ollama")
            return await status()
    raise ValueError("Ollama started but its local service did not become ready.")


async def pull(model: str) -> AsyncIterator[dict]:
    # any validly-named model from the Ollama library can be pulled (search box), not just
    # the curated set; the name regex blocks injection and Ollama refuses unknown models
    try:
        name = _validate_model_name(model, curated_only=False)
    except ValueError as exc:
        yield {"error": str(exc)}
        return
    running, _version, _models = await _server_info()
    if not running:
        yield {"error": "Start Ollama before downloading a model."}
        return
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE}/api/pull",
                json={"model": name, "stream": True},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("error"):
                        yield {"error": str(event["error"])[:240]}
                        return
                    yield {
                        "status": event.get("status") or "Downloading",
                        "completed": int(event.get("completed") or 0),
                        "total": int(event.get("total") or 0),
                    }
    except httpx.HTTPError:
        yield {"error": "Ollama could not download this model. Check the local service and connection."}
        return

    await catalog.set_active(f"ollama/{name}", f"{name} (local)", "ollama", True)
    ai.clear_model_cache("ollama")
    yield {"done": True, "model": f"ollama/{name}"}


async def set_active(model: str, active: bool) -> dict:
    name = _validate_model_name(model)
    _running, _version, models = await _server_info()
    installed = {item.get("name") or item.get("model") for item in models}
    if name not in installed:
        raise ValueError("Download this model before activating it.")
    await catalog.set_active(f"ollama/{name}", f"{name} (local)", "ollama", active)
    return {"id": f"ollama/{name}", "active": active}


async def remove(model: str) -> dict:
    name = _validate_model_name(model)
    running, _version, models = await _server_info()
    if not running:
        raise ValueError("Start Ollama before removing a model.")
    installed = {item.get("name") or item.get("model") for item in models}
    if name not in installed:
        raise ValueError("This Ollama model is not installed.")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request("DELETE", f"{OLLAMA_BASE}/api/delete", json={"model": name})
            response.raise_for_status()
    except httpx.HTTPError:
        raise ValueError("Ollama could not remove this model.") from None
    await catalog.set_active(f"ollama/{name}", "", "", False)
    ai.clear_model_cache("ollama")
    return {"deleted": True, "model": name}
