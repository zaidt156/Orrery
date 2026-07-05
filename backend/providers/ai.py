from __future__ import annotations

import logging
import re
import time
import asyncio
import hashlib
from collections.abc import AsyncIterator

import httpx

from backend.providers import accounts
from backend.security import secrets

log = logging.getLogger("orrery.ai")

# providers and whether they need a key; Ollama runs locally (no key)
PROVIDERS: dict[str, dict] = {
    "anthropic": {"label": "Anthropic", "needs_key": True},
    "openai": {"label": "OpenAI", "needs_key": True},
    "google": {"label": "Google", "needs_key": True},
    "mistral": {"label": "Mistral (EU)", "needs_key": True},
    "deepseek": {"label": "DeepSeek", "needs_key": True},
    "openrouter": {"label": "OpenRouter", "needs_key": True},
    "ollama": {"label": "Ollama (local)", "needs_key": False},
}

# litellm routing prefix → our canonical provider name
_PREFIX_TO_PROVIDER = {
    "anthropic": "anthropic", "openai": "openai", "gemini": "google",
    "mistral": "mistral", "deepseek": "deepseek", "openrouter": "openrouter", "ollama": "ollama",
}

_OLLAMA_BASE = "http://localhost:11434"
_CACHE_TTL = 120.0
_cache: dict[str, tuple[float, list[dict]]] = {}
# per-cache-name freshness: "live" (just fetched), "cache" (TTL hit), "fallback" (fetch failed,
# serving a stale/empty list). Lets us flag silently-stale model lists instead of hiding the failure.
_discovery_source: dict[str, str] = {}


def discovery_source(name: str) -> str:
    return _discovery_source.get(name, "live")

_litellm = None


def clear_model_cache(provider: str | None = None) -> None:
    if provider is None:
        _cache.clear()
        return
    for key in list(_cache):
        if key == provider or key.startswith(f"{provider}:"):
            _cache.pop(key, None)


class MissingKeyError(Exception):
    """Raised when a cloud model is requested but its provider key isn't set."""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"No API key configured for {provider}.")


class ReasoningDelta(str):
    """A streamed reasoning/'thinking' token — kept separate from the final answer text."""


def _load_litellm():
    global _litellm
    if _litellm is None:
        import litellm

        litellm.telemetry = False  # do not phone home (local-first)
        litellm.suppress_debug_info = True
        litellm.drop_params = True  # drop params a given model doesn't support (e.g. reasoning_effort)
        _litellm = litellm
    return _litellm


def model_provider(model_id: str) -> str:
    """The canonical provider a model id belongs to (from its routing prefix)."""
    if model_id.startswith("claude_plan/"):
        return "claude_plan"
    if model_id.startswith("chatgpt_plan/"):
        return "chatgpt_plan"
    if model_id.startswith("gemini_plan/"):
        return "gemini_plan"
    if model_id.startswith("custom/"):
        return "custom"
    if "/" in model_id:
        prefix = model_id.split("/", 1)[0]
        return _PREFIX_TO_PROVIDER.get(prefix, prefix)
    if model_id.startswith("claude"):
        return "anthropic"
    if model_id.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if model_id.startswith("gemini"):
        return "google"
    return "openai"


# Context-window sizes for routes litellm can't look up. Plan CLIs run the provider's standard
# context; explicit "[1m]" plan variants opt into long context. Local/custom fallbacks stay
# conservative — this is the history budget Orrery trims to, so overstating it makes models
# silently lose context.
_PLAN_CONTEXT: dict[str, int] = {
    "claude_plan": 200_000,
    "chatgpt_plan": 272_000,
    "gemini_plan": 1_048_576,
}
_DEFAULT_CONTEXT = 131_072
_LOCAL_DEFAULT_CONTEXT = 32_768
_1M = 1_000_000

# Anthropic models with long-context support: 1M on the API via the context-1m beta header, and on
# the Claude CLI plan via the "[1m]" model suffix. Prefix-matched on the bare model name.
_ANTHROPIC_1M_PREFIXES = ("claude-sonnet-4", "claude-sonnet-5", "claude-opus-4-8", "claude-fable-5")


def supports_1m_context(model_id: str) -> bool:
    bare = model_id.split("/")[-1]
    return any(bare.startswith(p) for p in _ANTHROPIC_1M_PREFIXES)


def _claude_plan_flag(model_id: str) -> str:
    from backend.providers import manifest
    for vid, _label, flag in manifest.variants("claude_plan"):
        if vid == model_id:
            return flag or ""
    return ""


def plan_long_context_model(model_id: str, context_window: int | None) -> str:
    """Reach 1M from a single 'Claude Opus' entry: when the chosen context window exceeds the 200K
    standard tier, switch a Claude-plan model to its 1M ("[1m]") sibling so the CLI runs long-context
    mode. The window drives the mode instead of the user picking a separate model. A no-op for windows
    at/under 200K, non-plan models, and models without a 1M sibling."""
    if not context_window or context_window <= _PLAN_CONTEXT["claude_plan"]:
        return model_id
    if model_provider(model_id) != "claude_plan" or model_id.endswith("-1m"):
        return model_id
    from backend.providers import manifest
    sibling = f"{model_id}-1m"
    if any(vid == sibling for vid, _label, _flag in manifest.variants("claude_plan")):
        return sibling
    return model_id


def model_context_window(model_id: str) -> int:
    """Max usable context for a model, so the UI only offers sizes the model actually has."""
    provider = model_provider(model_id)
    if provider == "claude_plan":
        # 1M-capable plan models (Opus/Sonnet/Fable) expose the full window from a single entry; Orrery
        # turns on the CLI's "[1m]" long-context mode at request time when the chosen window exceeds the
        # 200K standard tier (see plan_long_context_model). Haiku and the generic "adaptive" route,
        # which have no 1M mode, stay at the standard tier.
        flag = _claude_plan_flag(model_id)
        return _1M if ("[1m]" in flag or supports_1m_context(flag.replace("[1m]", ""))) else _PLAN_CONTEXT[provider]
    if provider in _PLAN_CONTEXT:
        return _PLAN_CONTEXT[provider]
    if provider == "anthropic" and supports_1m_context(model_id):
        return _1M  # stream_chat sends the context-1m beta header for these
    try:
        info = _load_litellm().get_model_info(model_id)
        known = int(info.get("max_input_tokens") or info.get("max_tokens") or 0)
        if known > 0:
            return known
    except Exception:  # noqa: BLE001 — unknown to litellm → conservative fallback below
        pass
    return _LOCAL_DEFAULT_CONTEXT if provider in ("ollama", "custom") else _DEFAULT_CONTEXT


# --- live model discovery ---

def _clean_openai(ids: list[str]) -> list[str]:
    """Keep current chat models; drop non-chat, legacy, and dated snapshots."""
    out = []
    for i in sorted(ids):
        if not re.match(r"^(gpt-|o1|o3|o4|chatgpt)", i):
            continue
        if any(x in i for x in (
            "embedding", "whisper", "tts", "dall", "audio", "realtime",
            "image", "moderation", "search", "transcribe", "instruct", "gpt-3.5",
        )):
            continue
        if re.search(r"\d{4}-\d{2}-\d{2}", i):  # dated snapshot
            continue
        if re.search(r"-\d{3,4}$", i) or i.endswith("-16k"):  # -0125, -1106, -16k
            continue
        out.append(i)
    return out


async def _fetch_openai(key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
    return [{"id": f"openai/{i}", "label": i, "provider": "openai"} for i in _clean_openai(ids)]


async def _fetch_anthropic(key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        r.raise_for_status()
        data = r.json().get("data", [])
    return [
        {"id": f"anthropic/{m['id']}", "label": m.get("display_name") or m["id"], "provider": "anthropic"}
        for m in data
    ]


async def _fetch_google(key: str) -> list[dict]:
    # key goes in a header, never the URL — a failed request's error string is logged, and a
    # URL-embedded key would leak there (security.md §1)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": key},
        )
        r.raise_for_status()
        models = r.json().get("models", [])
    out = []
    for m in models:
        if "generateContent" in m.get("supportedGenerationMethods", []):
            name = m["name"].split("/", 1)[-1]
            if name.startswith("gemini"):
                out.append({"id": f"gemini/{name}", "label": name, "provider": "google"})
    return out


async def _fetch_ollama() -> list[dict]:
    async with httpx.AsyncClient(timeout=4) as c:
        r = await c.get(f"{_OLLAMA_BASE}/api/tags")
        r.raise_for_status()
        models = r.json().get("models", [])
    return [
        {"id": f"ollama/{m['name']}", "label": f"{m['name']} (local)", "provider": "ollama"}
        for m in models
    ]


# --- curation: ~4 latest models per provider, always incl. a reasoning model ---

def _ver(s: str) -> float:
    """A rough version score from the digits in a model id (4-8 → 4.08, 5.5 → 5.05)."""
    nums = re.findall(r"\d+", s)
    if not nums:
        return 0.0
    major = int(nums[0])
    minor = int(nums[1]) if len(nums) > 1 else 0
    return major + minor / 100.0


def _curate_openai(items: list[dict]) -> list[dict]:
    """Latest flagship + reasoning (o-series) + a fast model + a pro, max 4."""
    by = {it["label"]: it for it in items}
    buckets: dict[str, list[str]] = {"flagship": [], "mini": [], "pro": [], "reason": []}
    for label in by:
        if re.match(r"^o\d", label):
            buckets["reason"].append(label)  # o1 / o3 / o4-mini = reasoning
        elif "codex" in label or "chat-latest" in label:
            continue  # specialized aliases — skip
        elif "mini" in label or "nano" in label:
            buckets["mini"].append(label)
        elif "pro" in label:
            buckets["pro"].append(label)
        else:
            buckets["flagship"].append(label)
    for b in buckets.values():
        b.sort(key=_ver, reverse=True)
    picked: list[str] = []
    for slot in ("flagship", "reason", "mini", "pro"):
        if buckets[slot]:
            picked.append(buckets[slot][0])
    for label in sorted(by, key=_ver, reverse=True):
        if len(picked) >= 4:
            break
        if label not in picked and "codex" not in label and "chat-latest" not in label:
            picked.append(label)
    return [by[l] for l in picked[:4]]


def _curate_anthropic(items: list[dict]) -> list[dict]:
    """Latest of each Claude tier (opus, sonnet, haiku, fable) — all reasoning-capable."""
    best: dict[str, tuple[float, dict]] = {}
    for it in items:
        mid = it["id"].split("/", 1)[-1]
        for tier in ("opus", "sonnet", "haiku", "fable", "mythos"):
            if tier in mid:
                v = _ver(mid)
                if tier not in best or v > best[tier][0]:
                    best[tier] = (v, it)
                break
    picked = [best[t][1] for t in ("opus", "sonnet", "haiku", "fable", "mythos") if t in best]
    return picked[:4]


def _curate_google(items: list[dict]) -> list[dict]:
    """A pro, a flash, a thinking/reasoning variant, max 4."""
    buckets: dict[str, list[dict]] = {"pro": [], "flash": [], "thinking": [], "other": []}
    for it in items:
        label = it["label"]
        if "thinking" in label or "reason" in label:
            buckets["thinking"].append(it)
        elif "pro" in label:
            buckets["pro"].append(it)
        elif "flash" in label:
            buckets["flash"].append(it)
        else:
            buckets["other"].append(it)
    for b in buckets.values():
        b.sort(key=lambda it: _ver(it["label"]), reverse=True)
    picked: list[dict] = []
    for slot in ("pro", "flash", "thinking", "other"):
        if buckets[slot]:
            picked.append(buckets[slot][0])
    for it in sorted(items, key=lambda it: _ver(it["label"]), reverse=True):
        if len(picked) >= 4:
            break
        if it not in picked:
            picked.append(it)
    return picked[:4]


async def _fetch_mistral(key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.mistral.ai/v1/models", headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
    return [{"id": f"mistral/{i}", "label": i, "provider": "mistral"} for i in sorted(set(ids))]


def _curate_mistral(items: list[dict]) -> list[dict]:
    """Latest chat/reasoning Mistral models; drop embeddings/moderation/ocr and dated snapshots."""
    cand = []
    for it in items:
        mid = it["id"].split("/", 1)[-1]
        if any(x in mid for x in ("embed", "moderation", "ocr")):
            continue
        if re.search(r"\d{4}", mid) and "latest" not in mid:  # prefer -latest over dated snapshots
            continue
        cand.append(it)
    buckets: dict[str, list[dict]] = {"large": [], "reason": [], "small": [], "other": []}
    for it in cand:
        mid = it["id"].split("/", 1)[-1]
        if "magistral" in mid:  # Mistral's reasoning family
            buckets["reason"].append(it)
        elif "large" in mid:
            buckets["large"].append(it)
        elif "small" in mid or "ministral" in mid:
            buckets["small"].append(it)
        else:
            buckets["other"].append(it)
    for b in buckets.values():
        b.sort(key=lambda it: _ver(it["label"]), reverse=True)
    picked: list[dict] = []
    for slot in ("large", "reason", "small", "other"):
        if buckets[slot]:
            picked.append(buckets[slot][0])
    for it in cand:
        if len(picked) >= 4:
            break
        if it not in picked:
            picked.append(it)
    return picked[:4]


async def _fetch_deepseek(key: str) -> list[dict]:
    # DeepSeek serves just two chat models; a static list avoids an extra round-trip.
    return [
        {"id": "deepseek/deepseek-chat", "label": "deepseek-chat", "provider": "deepseek"},
        {"id": "deepseek/deepseek-reasoner", "label": "deepseek-reasoner (reasoning)", "provider": "deepseek"},
    ]


def _curate_passthrough(items: list[dict]) -> list[dict]:
    return items[:4]


# OpenRouter aggregates hundreds of models; keep popular providers' chat models and cap the list so
# the picker/catalog stays usable. litellm routes "openrouter/<id>" natively with the OpenRouter key.
_OPENROUTER_KEEP = ("anthropic/", "openai/", "google/", "meta-llama/", "mistralai/", "deepseek/", "qwen/", "x-ai/", "cohere/")


async def _fetch_openrouter(key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        data = r.json().get("data", [])
    out: list[dict] = []
    for m in data:
        mid = m.get("id") or ""
        low = mid.lower()
        if not mid.startswith(_OPENROUTER_KEEP):
            continue
        if any(x in low for x in (":free", "-free", "preview", "deprecated", "-vision", "embed")):
            continue
        out.append({"id": f"openrouter/{mid}", "label": m.get("name") or mid, "provider": "openrouter"})
    out.sort(key=lambda it: it["label"].lower())
    return out[:60]


def _curate_openrouter(items: list[dict]) -> list[dict]:
    """Pick a few flagships across families for auto-activation when the key is first added."""
    picked: list[dict] = []
    for kw in ("claude", "gpt", "gemini", "llama", "deepseek"):
        for it in items:
            if kw in it["label"].lower() and it not in picked:
                picked.append(it)
                break
        if len(picked) >= 4:
            break
    for it in items:
        if len(picked) >= 4:
            break
        if it not in picked:
            picked.append(it)
    return picked[:4]


async def _cached(name: str, fn, *args) -> list[dict]:
    now = time.time()
    hit = _cache.get(name)
    if hit and now - hit[0] < _CACHE_TTL:
        _discovery_source[name] = "cache"
        return hit[1]
    try:
        val = await fn(*args)
        _discovery_source[name] = "live"
    except Exception as exc:  # noqa: BLE001 — discovery failure shouldn't break the picker
        _discovery_source[name] = "fallback"
        from backend.core.observability import log_event
        log_event(log, "model_discovery_fallback", provider=name, error=type(exc).__name__)
        val = hit[1] if hit else []
    _cache[name] = (now, val)
    return val


def _provider_cache_name(provider: str, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"{provider}:{digest}"


# discovery + curation per key-gated provider, in one table
_DISCOVERY: dict[str, tuple] = {
    "anthropic": (_fetch_anthropic, _curate_anthropic),
    "openai": (_fetch_openai, _curate_openai),
    "google": (_fetch_google, _curate_google),
    "mistral": (_fetch_mistral, _curate_mistral),
    "deepseek": (_fetch_deepseek, _curate_passthrough),
    "openrouter": (_fetch_openrouter, _curate_openrouter),
}
_KEYED = ("anthropic", "openai", "google", "mistral", "deepseek", "openrouter")


async def provider_models(provider: str) -> list[dict]:
    """Curated models for one provider (used to auto-activate when a key is first added)."""
    if provider == "ollama":
        return await _cached("ollama", _fetch_ollama)
    key = secrets.get_provider_key(provider)
    entry = _DISCOVERY.get(provider)
    if not key or not entry:
        return []
    fetch, curate = entry
    return curate(await _cached(_provider_cache_name(provider, key), fetch, key))


def _cli_plan_models() -> list[dict]:
    return accounts.claude_plan_models() + accounts.chatgpt_plan_models() + accounts.gemini_plan_models()


async def _discover_available() -> list[dict]:
    """Every model the user could turn on, key-gated and curated to ~4 latest per provider."""
    out: list[dict] = await asyncio.to_thread(_cli_plan_models)
    work: list[tuple[str, object]] = []
    for p in _KEYED:
        if key := secrets.get_provider_key(p):
            fetch, _curate = _DISCOVERY[p]
            work.append((p, _cached(_provider_cache_name(p, key), fetch, key)))
    work.append(("ollama", _cached("ollama", _fetch_ollama)))

    values = await asyncio.gather(*(coro for _, coro in work))
    results = {name: models for (name, _), models in zip(work, values, strict=True)}

    for p in _KEYED:
        _fetch, curate = _DISCOVERY[p]
        out += curate(results.get(p, []))
    out += results.get("ollama", [])  # local; empty if not running
    return out


async def list_available_models() -> list[dict]:
    """The Chat model menu: only the models the user has activated in Settings."""
    from backend.providers import catalog
    await catalog.refresh_active_metadata(await _discover_available())
    return await catalog.list_active()


async def list_catalog() -> list[dict]:
    """The Settings model list: everything pickable, each flagged active or not."""
    from backend.providers import catalog
    active = await catalog.active_ids()
    available, customs = await _discover_available(), await catalog.list_custom_models()
    await catalog.refresh_active_metadata(available + customs)
    out = [
        {"id": m["id"], "label": m["label"], "provider": m["provider"], "active": m["id"] in active}
        for m in available
    ]
    for m in customs:
        out.append({
            "id": m["id"], "label": m["label"], "provider": "custom",
            "active": m["id"] in active, "configured": m["configured"],
            "base_url": m["base_url"], "model": m["model"], "custom_id": m["custom_id"],
        })
    return out


# any key-shaped token that might ride along in a provider error string
_SECRET_RX = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|AIza[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9._\-]{6,})")


def _scrub_secrets(text: str) -> str:
    # Centralized scrubber (key shapes, bearer tokens, URL passwords, secret query params),
    # plus the provider layer's own key-shaped pattern for anything it catches first.
    return secrets.redact_secrets(_SECRET_RX.sub("[redacted]", text))


def _sanitize(exc: Exception) -> str:
    """A user-safe, friendly one-liner; provider errors can carry keys/request fragments."""
    msg = str(exc)
    low = msg.lower()
    if "sk-" in msg or "aiza" in low or "api_key" in low or "api key" in low or "authorization" in low:
        return "The provider rejected the request — check your API key in Settings."
    if "quota" in low or "insufficient_quota" in low or "billing" in low:
        return ("You're out of API credit for this provider. Add billing/credit in your "
                "provider account, switch to another model, or use a local model.")
    if "rate limit" in low or "ratelimit" in low or " 429" in msg:
        return "Rate limited by the provider — wait a moment and try again."
    name = type(exc).__name__
    clean = _scrub_secrets(msg.replace("litellm.", "").strip())  # never surface a key
    return f"{name}: {clean[:200]}"


async def stream_chat(
    model_id: str,
    messages: list[dict],
    system_prompt: str | None = None,
    effort: str | None = None,
    usage_out: dict | None = None,
) -> AsyncIterator[str]:
    """Yield assistant text deltas; raises MissingKeyError if the provider key is missing.

    `usage_out`, when provided, enables API-key spend metering: the cap is enforced before
    the call and token/cost usage is written into the dict after. CLI-plan and local routes
    are exempt (they don't bill per token).
    """
    provider = model_provider(model_id)

    # Privacy boundary: every cloud-bound route (API keys, custom endpoints, CLI plans) passes
    # user/document text through PII redaction first. Local (Ollama) models are exempt — nothing
    # leaves the machine. Controlled by the "privacy_mode" setting (off / basic / strict).
    if provider != "ollama":
        from backend.core import appconfig
        from backend.security import privacy
        try:
            mode = await appconfig.get_setting("privacy_mode", "basic") or "basic"
        except Exception:  # noqa: BLE001 — a settings read failure must not break the chat; redact by default
            mode = "basic"
        messages = privacy.prepare_messages_for_model(messages, is_local=False, mode=mode)

    if provider == "claude_plan":
        try:
            async for delta in accounts.stream_claude_plan(messages, system_prompt, model_id, effort):
                yield ReasoningDelta(str(delta)) if isinstance(delta, accounts.ReasoningChunk) else delta
            return
        except accounts.UnsupportedClaudePlanInput:
            raise
        except accounts.ClaudePlanUnavailable as exc:
            raise RuntimeError(_scrub_secrets(str(exc))) from None

    if provider in ("chatgpt_plan", "gemini_plan"):
        adapter = accounts.stream_chatgpt_plan if provider == "chatgpt_plan" else accounts.stream_gemini_plan
        try:
            async for delta in adapter(messages, system_prompt, model_id, effort):
                yield delta
            return
        except accounts.UnsupportedClaudePlanInput:
            raise
        except accounts.CliRouteUnavailable as exc:
            raise RuntimeError(_scrub_secrets(str(exc))) from None

    full = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages
    litellm = _load_litellm()
    kwargs: dict = {"messages": full, "stream": True}

    if provider == "custom":
        from backend.providers import catalog
        custom_id = model_id.split("/", 1)[1]
        cm = await catalog.get_custom_model(custom_id)
        if cm is None:
            raise RuntimeError("This custom model is no longer configured. Pick another in Settings.")
        key = catalog.custom_model_key(custom_id)
        if not key:
            raise MissingKeyError("custom")
        from backend.security import netguard
        try:  # re-check at call time (defense in depth) in case the stored URL is unsafe
            safe_base = netguard.validate_model_base_url(cm["base_url"])
        except netguard.UnsafeUrlError as exc:
            raise RuntimeError(str(exc)) from None
        kwargs["model"] = f"openai/{cm['model']}"  # route any OpenAI-compatible endpoint
        kwargs["api_base"] = safe_base
        kwargs["api_key"] = key
    else:
        needs_key = PROVIDERS.get(provider, {}).get("needs_key", True)
        api_key = secrets.get_provider_key(provider) if needs_key else None
        if needs_key and not api_key:
            raise MissingKeyError(provider)
        kwargs["model"] = model_id
        if api_key:
            kwargs["api_key"] = api_key
        if provider == "anthropic" and supports_1m_context(model_id):
            # long-context beta: harmless under 200K input, enables up to 1M above it
            kwargs["extra_headers"] = {"anthropic-beta": "context-1m-2025-08-07"}
        if provider == "ollama":
            kwargs["api_base"] = _OLLAMA_BASE
            from backend.features import local_models
            if not await local_models.is_running():
                raise RuntimeError(
                    "Ollama isn't running, so local models can't respond. Open the Local Models tab "
                    "and start Ollama (or launch the Ollama app), then try again."
                )

    if effort:
        kwargs["reasoning_effort"] = effort  # litellm maps per provider; drop_params handles the rest

    # API-key spend metering (ollama is local → exempt; CLI plans returned earlier)
    metered = usage_out is not None and provider != "ollama"
    if metered:
        from backend.features import usage
        blocked, info = await usage.cap_exceeded()
        if blocked:
            cap = info["cap"]
            raise RuntimeError(
                f"API spend cap reached: ${info['cost']:.2f} used of your ${cap['limit_usd']:.2f} "
                f"per-{cap['period']} limit. Switch to a subscription plan (Claude/ChatGPT/Gemini) or a "
                "local Ollama model — those don't bill per token — or raise the cap in Settings → Spending."
            )
        kwargs["stream_options"] = {"include_usage": True}

    captured = None
    try:
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            if metered and getattr(chunk, "usage", None):
                captured = chunk.usage
            if chunk.choices:
                d = chunk.choices[0].delta
                # Providers expose reasoning under different fields — handle them all:
                # reasoning_content (DeepSeek/most), reasoning (some), thinking_blocks (Anthropic).
                reasoning = getattr(d, "reasoning_content", None) or getattr(d, "reasoning", None)
                if reasoning:
                    yield ReasoningDelta(reasoning if isinstance(reasoning, str) else str(reasoning))
                else:
                    for block in (getattr(d, "thinking_blocks", None) or []):
                        text = (block.get("thinking") or block.get("text") or "") if isinstance(block, dict) else ""
                        if text:
                            yield ReasoningDelta(text)
                if d.content:
                    yield d.content
    except MissingKeyError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface a sanitized message
        log.error("Model call failed (%s): %s", model_id, _sanitize(exc))
        raise RuntimeError(_sanitize(exc)) from None

    if metered and captured is not None:
        tin = int(getattr(captured, "prompt_tokens", 0) or 0)
        tout = int(getattr(captured, "completion_tokens", 0) or 0)
        pricing_known = True
        try:
            pc, cc = litellm.cost_per_token(model=kwargs["model"], prompt_tokens=tin, completion_tokens=tout)
            cost = float((pc or 0) + (cc or 0))
        except Exception:  # noqa: BLE001 — unknown/custom model pricing → count tokens, cost 0
            cost = 0.0
            pricing_known = False  # cost is a placeholder, not genuinely free — surface that honestly
        usage_out.update({
            "provider": provider, "model": model_id, "tokens_in": tin, "tokens_out": tout,
            "cost": cost, "pricing_known": pricing_known,
        })
