"""Universal, keyless web search.

The backend performs the search (via the ddgs library) and feeds the results to the model as context.
That is what makes web access universal: it works for ANY model/connection — local Ollama, a CLI plan,
or an API key — because it does not depend on a provider's own web tool.

This is the one outbound path beyond the model providers, opted into by using a web feature. Results
are always treated as UNTRUSTED context (facts to cite, never instructions) and are redacted by the
normal privacy layer before they reach a cloud model. Every call is best-effort: any failure returns
an empty list so a search miss never breaks chat or research.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("orrery.websearch")

MAX_RESULTS = 6
_SNIPPET_CHARS = 600


def _search_sync(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS
    except Exception:  # noqa: BLE001 — library missing → behave as "no web"
        log.debug("ddgs not installed; web search disabled")
        return []
    try:
        with DDGS() as ddgs:
            rows = list(ddgs.text(query, max_results=max_results))
    except Exception as exc:  # noqa: BLE001 — network/ratelimit/parse → degrade gracefully
        log.debug("web search failed: %s", type(exc).__name__)
        return []
    results: list[dict] = []
    for row in rows:
        title = (row.get("title") or "").strip()
        url = (row.get("href") or row.get("url") or "").strip()
        snippet = (row.get("body") or row.get("snippet") or "").strip()[:_SNIPPET_CHARS]
        if title or snippet:
            results.append({"title": title or url, "url": url, "snippet": snippet})
    return results


async def search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """Return up to max_results web hits [{title, url, snippet}]; [] on any failure (best-effort)."""
    query = (query or "").strip()
    if not query:
        return []
    return await asyncio.to_thread(_search_sync, query, max_results)


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
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.get('title','')} — {r.get('url','')}\n{r.get('snippet','')}".strip())
    return "\n\n".join(lines)
