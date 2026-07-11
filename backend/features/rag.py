from __future__ import annotations

import asyncio
import base64
import io
import logging
import uuid

from sqlalchemy import func, select, text

from backend.core.database import get_sessionmaker
from backend.core.models import Chunk, Collection

log = logging.getLogger("orrery.rag")

EMBED_MODEL = "BAAI/bge-small-en-v1.5"  # local, 384-dim, runs on-device
_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding  # heavy import, deferred to first use

        _embedder = TextEmbedding(model_name=EMBED_MODEL)
    return _embedder


def _embed_docs(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _get_embedder().embed(texts)]


def _embed_query(q: str) -> list[float]:
    return list(_get_embedder().query_embed(q))[0].tolist()


async def embed_docs(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_embed_docs, texts)


async def embed_query(q: str) -> list[float]:
    return await asyncio.to_thread(_embed_query, q)


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def _pdf_text(data_url: str) -> str:
    try:
        b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(base64.b64decode(b64)))
        return "\n\n".join((p.extract_text() or "").strip() for p in reader.pages).strip()
    except Exception:  # noqa: BLE001
        return ""


def _office_text(name: str, data_url: str) -> str:
    """Extract text from Office files (docx/xlsx/pptx) so any file type can become RAG context."""
    try:
        b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
        raw = io.BytesIO(base64.b64decode(b64))
        low = name.lower()
        if low.endswith(".docx"):
            from docx import Document
            doc = Document(raw)
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    parts.append("\t".join(c.text for c in row.cells))
            return "\n".join(parts).strip()
        if low.endswith((".xlsx", ".xls", ".xlsm")):
            from openpyxl import load_workbook
            wb = load_workbook(raw, read_only=True, data_only=True)
            out: list[str] = []
            for ws in wb.worksheets:
                out.append(f"# {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) for c in row if c is not None]
                    if cells:
                        out.append("\t".join(cells))
            wb.close()
            return "\n".join(out).strip()
        if low.endswith(".pptx"):
            from pptx import Presentation
            prs = Presentation(raw)
            parts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False) and shape.text.strip():
                        parts.append(shape.text.strip())
            return "\n".join(parts).strip()
    except Exception:  # noqa: BLE001 — unreadable file → no text, skip rather than break upload
        return ""
    return ""


def _extract(f: dict) -> str:
    name = (f.get("name") or "").lower()
    content = f.get("content") or ""
    if f.get("kind") == "pdf" or name.endswith(".pdf"):
        return _pdf_text(content)
    if name.endswith((".docx", ".xlsx", ".xls", ".xlsm", ".pptx")):
        return _office_text(name, content)
    if f.get("kind") == "text":
        return content  # text file: content is the raw text
    return ""  # unknown binary (image, zip, …): no extractable text, skip rather than embed base64


def chunk_text(body: str, size: int = 900, overlap: int = 150) -> list[str]:
    body = (body or "").strip()
    if not body:
        return []
    out, i = [], 0
    while i < len(body):
        out.append(body[i:i + size])
        i += size - overlap
    return out


def _collection_dict(c: Collection, chunks: int) -> dict:
    return {
        "id": str(c.id), "name": c.name, "embed_model": c.embed_model, "chunks": int(chunks or 0),
        "kind": getattr(c, "kind", "collection"), "connected": bool(getattr(c, "connected", False)),
        "description": getattr(c, "description", None),
    }


async def list_collections(kind: str = "collection") -> list[dict]:
    """List collections of a given kind ('collection' for the Data tab, 'ontology' for the Ontology tab)."""
    async with get_sessionmaker()() as s:
        rows = (await s.execute(
            select(Collection).where(Collection.kind == kind).order_by(Collection.created_at)
        )).scalars().all()
        # One grouped query for all chunk counts instead of a COUNT(*) per collection (N+1).
        counts = dict(
            (await s.execute(
                select(Chunk.collection_id, func.count())
                .where(Chunk.collection_id.in_([c.id for c in rows]))
                .group_by(Chunk.collection_id)
            )).all()
        ) if rows else {}
        return [_collection_dict(c, counts.get(c.id, 0)) for c in rows]


async def create_collection(name: str, kind: str = "collection", description: str | None = None) -> dict:
    async with get_sessionmaker()() as s:
        c = Collection(name=(name.strip() or "documents"), embed_model=EMBED_MODEL, kind=kind, description=(description or None))
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return _collection_dict(c, 0)


async def set_connected(cid: str, connected: bool) -> bool:
    """Connect/disconnect an ontology so its knowledge is (or isn't) used as context in every chat."""
    async with get_sessionmaker()() as s:
        c = await s.get(Collection, uuid.UUID(cid))
        if c is None:
            return False
        c.connected = bool(connected)
        await s.commit()
        return True


async def update_collection(cid: str, name: str | None = None, description: str | None = None) -> bool:
    async with get_sessionmaker()() as s:
        c = await s.get(Collection, uuid.UUID(cid))
        if c is None:
            return False
        if name is not None and name.strip():
            c.name = name.strip()[:120]
        if description is not None:
            c.description = description or None
        await s.commit()
        return True


async def connected_collection_ids() -> list[str]:
    """Collection ids of all connected ontologies — searched as context in every chat."""
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(Collection.id).where(Collection.connected.is_(True)))).scalars().all()
        return [str(r) for r in rows]


async def delete_collection(cid: str) -> bool:
    async with get_sessionmaker()() as s:
        c = await s.get(Collection, uuid.UUID(cid))
        if c is None:
            return False
        await s.delete(c)
        await s.commit()
        return True


async def add_documents(cid: str, files: list[dict]) -> int:
    from sqlalchemy import delete as sa_delete

    items: list[tuple[str, int, str]] = []
    for f in files:
        for i, ch in enumerate(chunk_text(_extract(f))):
            items.append((f.get("name", "file"), i, ch))
    if not items:
        return 0
    vecs = await embed_docs([c for _, _, c in items])
    replaced = {src for src, _, _ in items}
    async with get_sessionmaker()() as s:
        # Re-uploading a source REPLACES it — delete-then-insert in ONE transaction, so duplicates
        # can't accumulate and retrieval never sees a half-replaced source (plan Task 3).
        await s.execute(sa_delete(Chunk).where(
            Chunk.collection_id == uuid.UUID(cid), Chunk.source.in_(replaced)
        ))
        for (src, ordn, content), v in zip(items, vecs):
            s.add(Chunk(collection_id=uuid.UUID(cid), source=src, ordinal=ordn, content=content, embedding=v))
        await s.commit()
    return len(items)


# ── bulk ingestion as a durable queue job (large drops must never freeze the app) ──
_INGEST_PROGRESS: dict[str, dict] = {}  # collection id → {state,total_files,done_files,chunks,error}


def ingest_progress(cid: str) -> dict | None:
    return _INGEST_PROGRESS.get(str(uuid.UUID(cid)))


async def enqueue_ingest(cid: str, files: list[dict]) -> dict:
    """Spool payloads to disk and index them as a durable queue job (inline fallback).

    The upload request returns immediately; the UI polls ingest_progress. Payloads are spooled
    as a file because large base64 bodies don't belong in queue-job arguments."""
    import json as _json
    from pathlib import Path

    from backend.core.paths import user_data_dir

    safe_cid = str(uuid.UUID(cid))  # normalize before it touches a filename
    spool_dir = user_data_dir() / "tmp" / "ingest"
    spool_dir.mkdir(parents=True, exist_ok=True)
    spool = spool_dir / f"{safe_cid}-{uuid.uuid4().hex}.json"
    spool.write_text(_json.dumps(files), encoding="utf-8")
    _INGEST_PROGRESS[safe_cid] = {"state": "queued", "total_files": len(files),
                                  "done_files": 0, "chunks": 0, "error": None}
    from backend.core.queue import get_queue_app

    try:
        await get_queue_app().configure_task(name="ingest_documents").defer_async(
            cid=safe_cid, spool=str(spool))
    except Exception:  # noqa: BLE001 — queue down (tests/dev): index inline so uploads still work
        log.warning("ingest defer failed; running inline for %s", safe_cid)
        await run_ingest(safe_cid, str(spool))
    return {"queued": True, "files_queued": len(files)}


async def run_ingest(cid: str, spool: str) -> None:
    """Index one spool file with per-file transactions (progress is visible file by file)."""
    import json as _json
    from pathlib import Path

    progress = _INGEST_PROGRESS.setdefault(cid, {"state": "queued", "total_files": 0,
                                                 "done_files": 0, "chunks": 0, "error": None})
    progress.update(state="running", error=None)
    try:
        files = _json.loads(Path(spool).read_text(encoding="utf-8"))
        progress["total_files"] = len(files)
        for payload in files:
            added = await add_documents(cid, [payload])
            progress["done_files"] += 1
            progress["chunks"] += added
        progress["state"] = "done"
    except Exception as exc:  # noqa: BLE001 — recorded for the UI, never kills the worker
        progress["state"] = "error"
        progress["error"] = str(exc)[:300]
        log.warning("ingest failed for %s: %s", cid, exc)
    finally:
        try:
            Path(spool).unlink(missing_ok=True)
        except OSError:
            pass


async def documents(cid: str) -> list[dict]:
    """Distinct source files in a collection, with their chunk counts."""
    async with get_sessionmaker()() as s:
        rows = (await s.execute(
            select(Chunk.source, func.count())
            .where(Chunk.collection_id == uuid.UUID(cid))
            .group_by(Chunk.source)
            .order_by(Chunk.source)
        )).all()
        return [{"source": src, "chunks": int(n or 0)} for src, n in rows]


async def document_text(cid: str, source: str, max_chars: int = 60_000) -> str:
    """The extracted text of one indexed file, re-joined from its chunks (attachment preview)."""
    async with get_sessionmaker()() as s:
        rows = (await s.execute(
            select(Chunk.content)
            .where(Chunk.collection_id == uuid.UUID(cid), Chunk.source == source)
            .order_by(Chunk.ordinal)
        )).scalars().all()
    return "\n".join(rows)[:max_chars]


async def delete_source(cid: str, source: str) -> int:
    """Remove all chunks for one source file from a collection."""
    from sqlalchemy import delete
    async with get_sessionmaker()() as s:
        result = await s.execute(
            delete(Chunk).where(Chunk.collection_id == uuid.UUID(cid), Chunk.source == source)
        )
        await s.commit()
        return result.rowcount or 0


# Above this cosine distance a chunk is judged unrelated to the question and dropped. Without this
# gate the vector arm ALWAYS returns k chunks, so files from earlier turns kept leaking into every
# answer ("why is it reading my Q2 report when I asked about pasta?").
MAX_COSINE_DISTANCE = 0.58


async def search(cid: str, query: str, k: int = 5, query_vector: list[float] | None = None) -> list[dict]:
    """Hybrid retrieval: vector (pgvector) + keyword (Postgres FTS), fused by RRF.

    Relevance-gated: vector hits past MAX_COSINE_DISTANCE are dropped; keyword hits always pass
    (the text literally matched). An empty result means "these files say nothing about this".

    Pass `query_vector` (from embed_query) to reuse one embedding across several collections in a
    single turn instead of re-embedding the same query per collection."""
    qv = _vec(query_vector if query_vector is not None else await embed_query(query))
    async with get_sessionmaker()() as s:
        vec = (await s.execute(
            text("SELECT id::text AS id, source, content, (embedding <=> (:q)::vector) AS dist "
                 "FROM chunks WHERE collection_id = (:cid)::uuid "
                 "ORDER BY embedding <=> (:q)::vector LIMIT :k"),
            {"q": qv, "cid": cid, "k": k},
        )).mappings().all()
        kw = (await s.execute(
            text("SELECT id::text AS id, source, content "
                 "FROM chunks WHERE collection_id = (:cid)::uuid "
                 "AND tsv @@ plainto_tsquery('english', :q) "
                 "ORDER BY ts_rank(tsv, plainto_tsquery('english', :q)) DESC LIMIT :k"),
            {"q": query, "cid": cid, "k": k},
        )).mappings().all()

    fused: dict[str, dict] = {}
    for ranked in (vec, kw):
        for rank, row in enumerate(ranked, 1):
            entry = fused.setdefault(row["id"], {"source": row["source"], "content": row["content"], "score": 0.0})
            entry["score"] += 1.0 / (60 + rank)
            if "dist" in row:
                entry["dist"] = float(row["dist"])
            else:
                entry["kw"] = True  # matched by actual words → relevant regardless of distance
    kept = [e for e in fused.values() if e.get("kw") or e.get("dist", 1.0) <= MAX_COSINE_DISTANCE]
    return sorted(kept, key=lambda r: r["score"], reverse=True)[:k]
