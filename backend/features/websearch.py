"""Universal, keyless web search.

The backend performs the search (via the ddgs library) and feeds the results to the model as context.
That is what makes web access universal: it works for ANY model/connection — local Ollama, a CLI plan,
or an API key — because it does not depend on a provider's own web tool.

This is the one outbound path beyond the model providers, opted into by using a web feature. Search
queries are screened for common PII and secrets before leaving the device. Results are always treated
as UNTRUSTED context (facts to cite, never instructions) and are redacted by the normal privacy layer
before they reach a cloud model. The compatibility ``search`` API remains best-effort, while
``search_detailed`` preserves availability and provider-failure state for user-facing callers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from urllib.parse import urlsplit

from backend.security.privacy import redact
from backend.security.secrets import redact_secrets

log = logging.getLogger("orrery.websearch")

MAX_RESULTS = 6
MAX_RESULTS_LIMIT = 10
MAX_QUERY_CHARS = 400
_SEARCH_TIMEOUT_SECONDS = 8
_TITLE_CHARS = 300
_SNIPPET_CHARS = 600
_URL_CHARS = 2048
_PROVIDER_ERROR = "The web-search provider did not respond. Try again later."
_DEPENDENCY_ERROR = "Web search is unavailable because its search dependency is not installed."


class _WebSearchUnavailable(RuntimeError):
    pass


class _WebSearchProviderFailure(RuntimeError):
    pass


def _text(value: object, limit: int) -> str:
    """Normalize untrusted result text to a small, single-line value."""
    try:
        normalized = " ".join(str(value or "").split())
    except Exception:  # noqa: BLE001 - a malformed provider row is skipped, not fatal
        return ""
    return normalized[:limit].strip()


def _http_url(value: object) -> str:
    """Return a bounded HTTP(S) URL, or an empty string for unsafe/malformed values."""
    try:
        url = str(value or "").strip()
    except Exception:  # noqa: BLE001
        return ""
    if not url or len(url) > _URL_CHARS or any(char.isspace() for char in url):
        return ""
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
    except ValueError:
        return ""
    return url


def _outbound_query(value: object) -> str:
    """Bound and scrub a query before it crosses the third-party search boundary."""
    query = _text(value, MAX_QUERY_CHARS)
    if not query:
        return ""
    # Web search is a separate third-party boundary, so PII screening applies even when a model is
    # local. Secret screening is unconditional throughout Orrery and must happen before logging or I/O.
    return _text(redact_secrets(redact(query)), MAX_QUERY_CHARS)


def _bounded_result_count(max_results: object) -> int:
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        value = MAX_RESULTS
    return min(MAX_RESULTS_LIMIT, max(1, value))


def _search_sync(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS
    except Exception as exc:  # noqa: BLE001 - optional dependency can fail during import
        log.debug("ddgs not installed; web search disabled")
        raise _WebSearchUnavailable(_DEPENDENCY_ERROR) from exc
    try:
        with DDGS(timeout=_SEARCH_TIMEOUT_SECONDS) as ddgs:
            rows = ddgs.text(query, max_results=max_results) or []
    except Exception as exc:  # noqa: BLE001 - provider failures become safe status data
        log.debug("web search failed: %s", type(exc).__name__)
        raise _WebSearchProviderFailure(_PROVIDER_ERROR) from exc
    results: list[dict] = []
    seen_urls: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        url = _http_url(row.get("href") or row.get("url"))
        dedupe_key = url.casefold()
        if not url or dedupe_key in seen_urls:
            continue
        title = _text(row.get("title"), _TITLE_CHARS)
        snippet = _text(row.get("body") or row.get("snippet"), _SNIPPET_CHARS)
        if not title and not snippet:
            continue
        seen_urls.add(dedupe_key)
        results.append({"title": title or _text(url, _TITLE_CHARS), "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


async def search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """Return up to max_results web hits [{title, url, snippet}]; [] on any failure (best-effort)."""
    outcome = await search_detailed(query, max_results=max_results)
    return outcome["results"]


async def search_detailed(query: str, max_results: int = MAX_RESULTS) -> dict:
    """Return safe results plus an explicit ``ok``/``unavailable``/``error`` status."""
    outbound_query = _outbound_query(query)
    if not outbound_query:
        return {"status": "error", "results": [], "error": "Enter a non-empty web-search query."}
    try:
        results = await asyncio.to_thread(
            _search_sync,
            outbound_query,
            _bounded_result_count(max_results),
        )
    except _WebSearchUnavailable:
        return {"status": "unavailable", "results": [], "error": _DEPENDENCY_ERROR}
    except _WebSearchProviderFailure:
        return {"status": "error", "results": [], "error": _PROVIDER_ERROR}
    except Exception as exc:  # noqa: BLE001 - contain malformed provider output without leaking detail
        log.debug("unexpected web search failure: %s", type(exc).__name__)
        return {"status": "error", "results": [], "error": _PROVIDER_ERROR}
    return {"status": "ok", "results": results, "error": None}


def available() -> bool:
    """True if the web-search library is importable (so callers can advertise the capability)."""
    try:
        import ddgs  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def format_results(results: list[dict]) -> str:
    """Render hits as a compact, citable block for the model (numbered, with URLs)."""
    if not results:
        return "(no web results)"
    lines: list[str] = []
    for result in results[:MAX_RESULTS_LIMIT]:
        if not isinstance(result, Mapping):
            continue
        url = _http_url(result.get("url"))
        if not url:
            continue
        title = _text(result.get("title"), _TITLE_CHARS) or _text(url, _TITLE_CHARS)
        snippet = _text(result.get("snippet"), _SNIPPET_CHARS)
        lines.append(f"[{len(lines) + 1}] {title} — {url}\n{snippet}".strip())
    return "\n\n".join(lines) or "(no web results)"
