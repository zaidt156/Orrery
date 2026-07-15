import asyncio
import sys
import uuid

import pytest

from backend.features import rag

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _scratch_collection():
    from backend.core.migrations import run_migrations

    await run_migrations()
    created = await rag.create_collection(f"ingest-test-{uuid.uuid4().hex[:8]}")
    return created["id"]


async def _offline_embeddings(texts, model=None):
    """Keep ingestion tests deterministic and independent of model downloads."""
    return [[float(index + 1)] + [0.0] * (rag.EMBED_DIM - 1) for index, _ in enumerate(texts)]

@pytest.mark.anyio
async def test_reupload_replaces_instead_of_duplicating(monkeypatch):
    monkeypatch.setattr(rag, "embed_docs", _offline_embeddings)
    cid = await _scratch_collection()
    try:
        doc = {"name": "notes.txt", "kind": "text", "content": "Orrery keeps chats in the user's own database."}
        first = await rag.add_documents(cid, [doc])
        assert first > 0
        second = await rag.add_documents(cid, [doc])
        assert second == first

        docs = await rag.documents(cid)
        assert len(docs) == 1
        assert docs[0]["chunks"] == first  # same count after re-upload - no duplicates
    finally:
        await rag.delete_collection(cid)


@pytest.mark.anyio
async def test_enqueue_ingest_runs_inline_when_queue_is_down(monkeypatch, tmp_path):
    from backend.core import paths

    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(rag, "embed_docs", _offline_embeddings)

    class DownQueue:
        def configure_task(self, name):
            raise RuntimeError("queue offline")

    from backend.core import queue as queue_mod
    monkeypatch.setattr(queue_mod, "get_queue_app", lambda: DownQueue())

    cid = await _scratch_collection()
    try:
        files = [
            {"name": "a.txt", "kind": "text", "content": "alpha document body"},
            {"name": "b.txt", "kind": "text", "content": "beta document body"},
        ]
        result = await rag.enqueue_ingest(cid, files)
        assert result["queued"] is True and result["files_queued"] == 2

        progress = rag.ingest_progress(cid)
        assert progress["state"] == "done"
        assert progress["done_files"] == 2
        assert progress["chunks"] >= 2

        docs = await rag.documents(cid)
        assert {d["source"] for d in docs} == {"a.txt", "b.txt"}
        # the spool file is deleted after a successful run
        assert not list((tmp_path / "tmp" / "ingest").glob("*.json"))
    finally:
        await rag.delete_collection(cid)


def test_ingest_progress_rejects_non_uuid_ids():
    with pytest.raises(ValueError):
        rag.ingest_progress("../../etc/passwd")
