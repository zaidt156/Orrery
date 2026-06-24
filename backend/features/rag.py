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


def _extract(f: dict) -> str:
    if f.get("kind") == "pdf":
        return _pdf_text(f.get("content") or "")
    return f.get("content") or ""  # text file: content is the raw text


def chunk_text(body: str, size: int = 900, overlap: int = 150) -> list[str]:
    body = (body or "").strip()
    if not body:
        return []
    out, i = [], 0
    while i < len(body):
        out.append(body[i:i + size])
        i += size - overlap
    return out


async def list_collections() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(Collection).order_by(Collection.created_at))).scalars().all()
        out = []
        for c in rows:
            n = (await s.execute(select(func.count()).select_from(Chunk).where(Chunk.collection_id == c.id))).scalar()
            out.append({"id": str(c.id), "name": c.name, "embed_model": c.embed_model, "chunks": int(n or 0)})
        return out


async def create_collection(name: str) -> dict:
    async with get_sessionmaker()() as s:
        c = Collection(name=(name.strip() or "documents"), embed_model=EMBED_MODEL)
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return {"id": str(c.id), "name": c.name, "embed_model": c.embed_model, "chunks": 0}


async def delete_collection(cid: str) -> bool:
    async with get_sessionmaker()() as s:
        c = await s.get(Collection, uuid.UUID(cid))
        if c is None:
            return False
        await s.delete(c)
        await s.commit()
        return True


async def add_documents(cid: str, files: list[dict]) -> int:
    items: list[tuple[str, int, str]] = []
    for f in files:
        for i, ch in enumerate(chunk_text(_extract(f))):
            items.append((f.get("name", "file"), i, ch))
    if not items:
        return 0
    vecs = await embed_docs([c for _, _, c in items])
    async with get_sessionmaker()() as s:
        for (src, ordn, content), v in zip(items, vecs):
            s.add(Chunk(collection_id=uuid.UUID(cid), source=src, ordinal=ordn, content=content, embedding=v))
        await s.commit()
    return len(items)


async def search(cid: str, query: str, k: int = 5) -> list[dict]:
    """Hybrid retrieval: vector (pgvector) + keyword (Postgres FTS), fused by RRF."""
    qv = _vec(await embed_query(query))
    async with get_sessionmaker()() as s:
        vec = (await s.execute(
            text("SELECT id::text AS id, source, content "
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
    return sorted(fused.values(), key=lambda r: r["score"], reverse=True)[:k]
