"""Multilingual RAG: the default embedder is multilingual, a dimension mismatch is refused rather
than silently corrupting the vector column, and the keyword arm is language-neutral."""
import pytest

from backend.core.models import Chunk
from backend.features import rag


def test_default_embed_model_is_multilingual():
    assert "multilingual" in rag.default_embed_model().lower()


def test_default_embed_model_is_384_dim():
    """The default must fit the fixed 384-dim vector column, or every insert would fail."""
    from backend.core.models import EMBED_DIM
    assert rag._model_dim(rag.default_embed_model()) == EMBED_DIM


def test_get_embedder_refuses_dimension_mismatch():
    """A model whose dimension != the vector column is rejected before it can corrupt the store —
    the check reads fastembed's static metadata, so it never downloads the model."""
    rag._embedders.pop("BAAI/bge-base-en-v1.5", None)
    with pytest.raises(ValueError, match="dim"):
        rag._get_embedder("BAAI/bge-base-en-v1.5")  # 768-dim vs the 384-dim column


def test_keyword_column_is_language_neutral():
    """The generated full-text column uses 'simple' (no language stemmer/stopwords) so terms in any
    language match — a regression to 'english' would quietly break non-English keyword search."""
    expr = str(Chunk.__table__.c.tsv.computed.sqltext)
    assert "simple" in expr
    assert "english" not in expr
