"""Ontology RAG stress test: 300 files across 3 ontologies against the REAL local database.

Run manually (needs the local Postgres up):  .venv/Scripts/python scripts/stress_ontology_rag.py

Creates scratch ontology collections (names prefixed stress-test-), ingests 100 synthetic
files into each (each file carries one unique, retrievable fact), connects them, then checks:
  1. ingestion   - every file embedded (chunk counts)
  2. search      - pointed queries hit the right file in the right ontology
  3. chat gather - retrieval._gather_rag over all connected ontologies surfaces the fact
     (called exactly as the chat router does: ontologies ride as AUTO collections)
  4. isolation   - facts from ontology A are not attributed to ontology C's files,
     and an unrelated question pulls NOTHING from any ontology (no context mixing)
  5. timing      - per-stage wall clock
Cleans up its scratch collections at the end (leaves real user data untouched).
"""
import asyncio
import pathlib
import random
import sys
import time

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.core import database
from backend.features import rag
from backend.features.chat import retrieval

PREFIX = "stress-test-"
N_PER = 100
TOPICS = [
    ("alpha", "planetary navigation"), ("beta", "harbor logistics"), ("gamma", "orchard biology"),
]

FILLER = (
    "This section covers routine operational notes. Standard procedures apply to all teams. "
    "Review cycles happen quarterly and documentation is updated after each cycle. "
)


def make_file(ont_key: str, i: int) -> dict:
    fact = f"The {ont_key} reference code for unit {i} is {ont_key.upper()}-{1000 + i}."
    body = FILLER * 3 + "\n" + fact + "\n" + FILLER * 3
    return {"name": f"{ont_key}-doc-{i:03d}.txt", "kind": "text", "content": body}


async def main() -> int:
    url = database.resolve_database_url()
    if not url:
        print("FAIL: no database configured"); return 1
    if not await database.check_connection(force=True):
        print("FAIL: cannot connect to database"); return 1

    # -- cleanup any previous run
    for kind in ("ontology",):
        for c in await rag.list_collections(kind=kind):
            if c["name"].startswith(PREFIX):
                await rag.delete_collection(c["id"])

    failures: list[str] = []
    onts: dict[str, str] = {}

    # 1) ingestion ------------------------------------------------------------
    t0 = time.perf_counter()
    for key, desc in TOPICS:
        created = await rag.create_collection(f"{PREFIX}{key}", kind="ontology", description=desc)
        onts[key] = created["id"]
        files = [make_file(key, i) for i in range(N_PER)]
        added = await rag.add_documents(created["id"], files)
        docs = await rag.documents(created["id"])
        print(f"[ingest] {key}: {added} chunks from {len(docs)} files")
        if len(docs) != N_PER:
            failures.append(f"{key}: expected {N_PER} files indexed, got {len(docs)}")
        if added == 0:
            failures.append(f"{key}: zero chunks embedded")
    t_ingest = time.perf_counter() - t0

    # connect all three (the Ontology tab's toggle)
    for key, cid in onts.items():
        await rag.set_connected(cid, True)
    connected = set(await rag.connected_collection_ids())
    for key, cid in onts.items():
        if cid not in connected:
            failures.append(f"{key}: not in connected_collection_ids()")

    # 2) direct search -------------------------------------------------------
    t0 = time.perf_counter()
    random.seed(7)
    checks = [(key, random.randrange(N_PER)) for key, _ in TOPICS for _ in range(5)]
    for key, i in checks:
        q = f"what is the {key} reference code for unit {i}?"
        results = await rag.search(onts[key], q, k=5)
        hit = any(f"{key.upper()}-{1000 + i}" in r["content"] for r in results)
        if not hit:
            failures.append(f"search miss: {q!r} in {key} (got {[r['source'] for r in results]})")
    t_search = time.perf_counter() - t0

    # 3) chat-level gather across ALL connected ontologies (what a chat turn does)
    t0 = time.perf_counter()
    gather_ids = list(connected)
    for key, i in checks[:6]:
        q = f"what is the {key} reference code for unit {i}?"
        # exactly as the chat router calls it: connected ontologies ride as AUTO collections
        block, sources = await retrieval._gather_rag(
            "openai/gpt-test", gather_ids, q, auto_collection_ids=set(gather_ids)
        )
        if not block or f"{key.upper()}-{1000 + i}" not in block:
            failures.append(f"gather miss: {q!r} (sources={sources})")
        # 4) isolation: the fact must come from its own ontology's file
        elif not any(s.startswith(f"{key}-doc-") for s in sources):
            failures.append(f"attribution: {q!r} surfaced from {sources}")
    t_gather = time.perf_counter() - t0

    # unrelated question must surface nothing from these ontologies
    block, sources = await retrieval._gather_rag(
        "openai/gpt-test", gather_ids, "best pasta recipe for dinner tonight",
        auto_collection_ids=set(gather_ids),
    )
    stress_sources = [s for s in sources if s.split("-doc-")[0] in onts]
    if stress_sources:
        failures.append(f"leak: unrelated query pulled {stress_sources[:5]}")

    # -- cleanup
    for cid in onts.values():
        await rag.delete_collection(cid)

    print(f"[time] ingest 300 files: {t_ingest:.1f}s | 15 searches: {t_search:.1f}s | 6 gathers: {t_gather:.1f}s")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
