"""Relevance-gated retrieval for chat turns (data collections, project files, chat attachments,
connected ontologies). Strict mode keeps old uploads out of unrelated questions."""
from __future__ import annotations

import re

from backend.core.config import settings
from backend.features import rag
from backend.providers import ai
from backend.security import privacy


async def _rag_context(model: str, collection_id: str, query: str) -> tuple[str | None, list[str]]:
    """Retrieve top chunks from one collection (kept for callers that pass a single id)."""
    return await _gather_rag(model, [collection_id], query)


# Strict mode: the turn has its own attachments (the user is clearly talking about THOSE), or the
# text is too short/vague to judge similarity reliably ("Do it") — old files must clear a much
# higher bar to be pulled in, instead of tagging along on every message.
_STRICT_MAX_DIST = 0.45


async def _gather_rag(
    model: str,
    collection_ids: list[str],
    query: str,
    *,
    strict: bool = False,
    auto_collection_ids: set[str] | None = None,
) -> tuple[str | None, list[str]]:
    """Retrieve and merge top chunks across every relevant collection (selected data + project files).

    Searching all of them means project files are never dropped when "use my data" is also on, and a
    project chat always sees its own files. Results are de-duplicated and redacted for cloud models.

    `auto_collection_ids` are collections that ride along automatically (a chat's own uploaded files),
    as opposed to ones the user explicitly chose ("use my data", a project). Auto collections are held
    to the strict relevance bar on EVERY turn, so a file uploaded earlier doesn't leak into a later,
    unrelated question — the user didn't ask for it this time.
    """
    is_local = ai.model_provider(model) == "ollama"
    auto = auto_collection_ids or set()
    seen: set[tuple[str, str]] = set()
    blocks: list[str] = []
    sources: list[str] = []
    for collection_id in dict.fromkeys(cid for cid in collection_ids if cid):  # dedupe, keep order
        try:
            results = await rag.search(collection_id, query, k=settings.rag_top_k)
        except Exception:  # noqa: BLE001 — a retrieval failure on one collection shouldn't break the chat
            continue
        gate_strict = strict or collection_id in auto
        for r in results:
            if gate_strict and not r.get("kw") and r.get("dist", 1.0) > _STRICT_MAX_DIST:
                continue  # not clearly about this message — leave the old file out
            key = (r["source"], r["content"][:120])
            if key in seen:
                continue
            seen.add(key)
            blocks.append(f"[{r['source']}]\n{privacy.redact_for_model(r['content'], is_local)}")
            if r["source"] not in sources:
                sources.append(r["source"])
    return ("\n\n".join(blocks) if blocks else None), sources


def _vague_query(text: str) -> bool:
    """Too little signal to judge file relevance (e.g. 'Do it', 'contineou', 'yes please')."""
    meaningful = [w for w in re.findall(r"[A-Za-z0-9]+", text or "") if len(w) > 2]
    return len(meaningful) < 4


# A short turn can be a "proceed with the previous job" confirmation ("do it", "yes", "make it
# blue") OR a fresh question about the current turn ("what do you see", "who is this?"). Only the
# former may inherit an earlier file/image-generation intent. A question must be planned on its own
# merits, or a vision-style ask silently produces another file. (Reported: "what do you see" after
# a file turn generated a second, useless PDF — see docs/history/DEVLOG.md.)
_QUESTION_LEAD = re.compile(
    r"^(?:what|why|how|who|whom|whose|which|when|where|"
    r"do\s+(?:you|we|i)|does|are\s+(?:you|we|there|these|those)|is\s+(?:this|that|it|there)|"
    r"can\s+you|could\s+you|would\s+you|should\s+(?:i|we|it)|"
    r"tell\s+me|explain|describe)\b",
    re.IGNORECASE,
)


def _is_question(text: str) -> bool:
    """True when a short turn reads as a fresh question (so it must NOT inherit a prior intent)."""
    stripped = (text or "").strip()
    return bool(stripped) and ("?" in stripped or bool(_QUESTION_LEAD.match(stripped)))
