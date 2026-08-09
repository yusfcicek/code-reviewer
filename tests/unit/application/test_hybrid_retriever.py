"""Step 9 — fusing two indexes, and surviving one of them."""

from code_reviewer.application.ports import EmbeddingModel, LexicalIndex, VectorIndex
from code_reviewer.application.retrieval_service import HybridRetriever
from code_reviewer.domain.retrieval import CodeChunk, ScoredChunk
from code_reviewer.infrastructure.retrieval.embedding import HashingEmbedding
from code_reviewer.infrastructure.retrieval.lexical import BM25Index
from code_reviewer.infrastructure.retrieval.vector_index import InMemoryVectorIndex

CORPUS = [
    CodeChunk(
        path="auth/tokens.py",
        start_line=1,
        end_line=4,
        text="def authenticate_user(token):\n    return verify_token(token)",
        name="authenticate_user",
    ),
    CodeChunk(
        path="auth/session.py",
        start_line=1,
        end_line=4,
        text="def start_session(user):\n    return Session(user)",
        name="start_session",
    ),
    CodeChunk(
        path="billing/invoice.py",
        start_line=1,
        end_line=4,
        text="def render_invoice(order):\n    return template(order)",
        name="render_invoice",
    ),
]


def _retriever(**overrides) -> HybridRetriever:
    retriever = HybridRetriever(
        embedding=overrides.get("embedding", HashingEmbedding(dimensions=256)),
        lexical=overrides.get("lexical", BM25Index()),
        vectors=overrides.get("vectors", InMemoryVectorIndex()),
    )
    if "chunks" not in overrides or overrides["chunks"]:
        retriever.index(list(overrides.get("chunks", CORPUS)))
    return retriever


class ExplodingLexical(LexicalIndex):
    def add(self, chunks):
        pass

    def search(self, query, limit):
        raise RuntimeError("the index is corrupt")


class ExplodingVectors(VectorIndex):
    def add(self, entries):
        pass

    def search(self, vector, limit):
        raise RuntimeError("no such collection")

    def vector_of(self, chunk):
        return None


class ExplodingEmbedding(EmbeddingModel):
    def embed(self, texts):
        raise RuntimeError("the endpoint is down")


def test_both_indexes_contribute_to_the_result():
    found = _retriever().related("authenticate_user token", limit=3)

    assert any(chunk.name == "authenticate_user" for chunk in found)


def test_the_file_under_review_is_never_returned():
    """The reviewer was handed that file whole before retrieval ran. Spending
    tokens re-showing it is the one certain waste."""
    found = _retriever().related("authenticate_user token", limit=3, exclude_path="auth/tokens.py")

    assert all(chunk.path != "auth/tokens.py" for chunk in found)


def test_the_limit_is_respected():
    assert len(_retriever().related("user session invoice token", limit=1)) == 1


def test_a_limit_of_zero_returns_nothing():
    assert _retriever().related("anything", limit=0) == []


def test_an_empty_query_returns_nothing():
    assert _retriever().related("   ", limit=3) == []


def test_an_empty_corpus_returns_nothing():
    assert _retriever(chunks=[]).related("authenticate", limit=3) == []


def test_a_broken_lexical_index_leaves_the_dense_half():
    found = _retriever(lexical=ExplodingLexical()).related("authenticate user", limit=3)

    assert found


def test_a_broken_vector_index_leaves_the_lexical_half():
    found = _retriever(vectors=ExplodingVectors()).related("authenticate_user", limit=3)

    assert found


def test_a_broken_embedding_leaves_the_lexical_half():
    retriever = HybridRetriever(
        embedding=ExplodingEmbedding(), lexical=BM25Index(), vectors=InMemoryVectorIndex()
    )
    retriever._lexical.add(list(CORPUS))  # indexing would need the embedding too

    assert retriever.related("authenticate_user", limit=3)


def test_both_halves_broken_returns_nothing_rather_than_raising():
    retriever = HybridRetriever(
        embedding=HashingEmbedding(dimensions=32),
        lexical=ExplodingLexical(),
        vectors=ExplodingVectors(),
    )

    assert retriever.related("authenticate_user", limit=3) == []


def test_indexing_nothing_is_not_an_error():
    retriever = _retriever(chunks=[])

    retriever.index([])

    assert retriever.related("x", limit=1) == []


def test_diversification_prefers_a_second_chunk_unlike_the_first():
    """Two near-duplicates and one different file: at a low relevance weight
    the second pick should be the one that adds something."""
    duplicate = CodeChunk(
        path="auth/tokens_copy.py",
        start_line=1,
        end_line=4,
        text=CORPUS[0].text,
        name="authenticate_user",
    )
    retriever = HybridRetriever(
        embedding=HashingEmbedding(dimensions=256),
        lexical=BM25Index(),
        vectors=InMemoryVectorIndex(),
        relevance_weight=0.0,
    )
    retriever.index([*CORPUS, duplicate])

    found = retriever.related("authenticate_user token", limit=2)

    assert found[1].text != found[0].text


def test_a_chunk_found_by_only_one_index_still_appears():
    found = _retriever().related("render_invoice", limit=3)

    assert any(chunk.name == "render_invoice" for chunk in found)


def test_the_result_is_deterministic():
    first = _retriever().related("user token session", limit=3)
    second = _retriever().related("user token session", limit=3)

    assert first == second


def test_a_scored_chunk_is_never_handed_out():
    """The port returns chunks. A score is an implementation detail of one
    retriever, and the workflow has no use for it."""
    for chunk in _retriever().related("user", limit=3):
        assert isinstance(chunk, CodeChunk)
        assert not isinstance(chunk, ScoredChunk)
