from backend.features import rag


def test_chunk_text_splits_with_overlap():
    body = "".join(str(i % 10) for i in range(2000))
    chunks = rag.chunk_text(body, size=900, overlap=150)
    assert len(chunks) >= 2
    assert all(len(c) <= 900 for c in chunks)
    assert chunks[0][-150:] == chunks[1][:150]  # overlap carries context across chunks


def test_chunk_text_empty():
    assert rag.chunk_text("") == []
    assert rag.chunk_text("   ") == []


def test_extract_text_passthrough():
    assert rag._extract({"kind": "text", "content": "hello world"}) == "hello world"


def test_vec_literal():
    assert rag._vec([0.1, 0.25]) == "[0.1,0.25]"
