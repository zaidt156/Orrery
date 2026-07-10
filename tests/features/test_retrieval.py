import pytest

from backend.features.chat import retrieval


async def _fake_embed_query(q):
    return [0.0]  # the query vector is passed through to the (mocked) search; value is unused here


@pytest.mark.anyio
async def test_auto_collection_held_to_strict_bar_on_normal_turn(monkeypatch):
    """A chat's own uploaded files (auto-included) must not leak into a later, unrelated question:
    a weakly-related chunk that an explicitly-chosen collection would keep is dropped for an auto one."""
    async def fake_search(cid, query, k=5, query_vector=None):
        # dist 0.50: under rag.search's 0.58 floor, but over the strict 0.45 relevance bar
        return [{"source": f"{cid}:doc", "content": "weakly related text", "dist": 0.50}]

    monkeypatch.setattr(retrieval.rag, "embed_query", _fake_embed_query)
    monkeypatch.setattr(retrieval.rag, "search", fake_search)

    # explicit collection ("use my data" / project): the 0.50 chunk is kept on a normal turn
    block, sources = await retrieval._gather_rag("openai/gpt", ["explicit"], "a question about pasta")
    assert block is not None and "explicit:doc" in sources

    # auto collection (the chat's own uploads): the same chunk is held to the strict bar and dropped
    block, sources = await retrieval._gather_rag(
        "openai/gpt", ["own"], "a question about pasta", auto_collection_ids={"own"}
    )
    assert block is None and sources == []


@pytest.mark.anyio
async def test_auto_collection_keeps_clearly_relevant_and_keyword_hits(monkeypatch):
    async def fake_search(cid, query, k=5, query_vector=None):
        return [
            {"source": "close", "content": "clearly relevant", "dist": 0.30},          # under strict bar → kept
            {"source": "kwhit", "content": "exact word match", "kw": True, "dist": 0.9},  # keyword → always kept
        ]

    monkeypatch.setattr(retrieval.rag, "embed_query", _fake_embed_query)
    monkeypatch.setattr(retrieval.rag, "search", fake_search)
    block, sources = await retrieval._gather_rag(
        "openai/gpt", ["own"], "q", auto_collection_ids={"own"}
    )
    assert "close" in sources and "kwhit" in sources


def test_acknowledgments_are_recognized():
    """'nice' after a generated SVG must read as praise, not as 'generate another one' —
    regression for the heart/sun SVG drawn in response to the word 'nice'."""
    for text in ("nice", "nice!", "Nice one", "thanks", "thank you so much", "wow, love it",
                 "perfect", "great job", "awesome!!", "beautiful", "haha cool", "well done"):
        assert retrieval._is_acknowledgment(text), text


def test_proceed_and_question_and_modification_turns_are_not_acknowledgments():
    for text in ("do it", "yes go ahead", "ok", "proceed", "make it blue", "smaller please",
                 "what do you see", "can you add a second hand", "now as a PDF"):
        assert not retrieval._is_acknowledgment(text), text


def test_strict_gate_drops_a_whole_off_topic_collection():
    """Off-topic questions bottom out around dist >= ~0.51: even though single chunks would pass a
    0.58 per-chunk bar, the collection's BEST hit fails the on-topic bar so nothing rides along."""
    results = [
        {"source": "a", "content": "filler", "dist": 0.52},
        {"source": "b", "content": "filler", "dist": 0.55},
    ]
    assert retrieval._gate_strict(results) == []


def test_strict_gate_keeps_only_the_best_hits_neighborhood():
    results = [
        {"source": "hit", "content": "the answer", "dist": 0.29},
        {"source": "near", "content": "adjacent detail", "dist": 0.36},
        {"source": "far", "content": "other doc in same ontology", "dist": 0.50},  # outside best+margin
    ]
    kept = [r["source"] for r in retrieval._gate_strict(results)]
    assert kept == ["hit", "near"]


def test_strict_gate_always_passes_keyword_matches():
    results = [
        {"source": "kw", "content": "literal word match", "kw": True, "dist": 0.9},
        {"source": "vec", "content": "far vector hit", "dist": 0.70},
    ]
    kept = [r["source"] for r in retrieval._gate_strict(results)]
    assert kept == ["kw"]


@pytest.mark.anyio
async def test_query_is_embedded_once_across_many_collections(monkeypatch):
    """The query is embedded a single time per turn and the vector is reused for every collection,
    instead of re-embedding the same text once per collection."""
    embeds = {"n": 0}
    seen_vectors = []

    async def counting_embed(q):
        embeds["n"] += 1
        return [0.42]

    async def fake_search(cid, query, k=5, query_vector=None):
        seen_vectors.append(query_vector)
        return [{"source": f"{cid}:doc", "content": "clearly relevant", "dist": 0.10}]

    monkeypatch.setattr(retrieval.rag, "embed_query", counting_embed)
    monkeypatch.setattr(retrieval.rag, "search", fake_search)

    block, sources = await retrieval._gather_rag(
        "openai/gpt", ["a", "b", "c", "d"], "a real question with enough words"
    )
    assert embeds["n"] == 1                       # embedded once, not four times
    assert seen_vectors == [[0.42]] * 4           # the same vector reused for each collection
    assert len(sources) == 4
