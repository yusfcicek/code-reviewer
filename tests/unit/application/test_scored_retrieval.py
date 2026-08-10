"""Step 1 — a score on the port, with an honest default.

The floor needs a number and the port did not have one, so Level 23's plan
described a relevance floor that could not be built and dropped it. Then the
self-review found the tier returning nothing at all, undetected for a level,
because there was no floor and no measurement to fail.

The default matters as much as the override. A retriever with no notion of a
score is a real thing — a keyword-only adapter, a stub in a test — and a floor
over its results must report itself as **inapplicable** rather than passing
everything. Silence there is how a whole tier went missing.
"""

from code_reviewer.application.ports import CodeRetriever
from code_reviewer.application.retrieval_service import HybridRetriever
from code_reviewer.domain.retrieval import CodeChunk
from code_reviewer.infrastructure.retrieval.embedding import HashingEmbedding
from code_reviewer.infrastructure.retrieval.lexical import BM25Index
from code_reviewer.infrastructure.retrieval.vector_index import InMemoryVectorIndex

CHUNKS = [
    CodeChunk(
        path="a.py", start_line=1, end_line=3, text="def suppress(rule):\n    return rule\n", name="suppress"
    ),
    CodeChunk(
        path="b.py", start_line=1, end_line=3, text="def unrelated(x):\n    return x\n", name="unrelated"
    ),
    CodeChunk(
        path="c.md",
        start_line=1,
        end_line=4,
        text="## Suppression\n\nA directive silences a rule.\n",
        name="Suppression",
    ),
]


class _Unscored(CodeRetriever):
    """A retriever with no notion of a score, which is a real thing."""

    def index(self, chunks):
        pass

    def related(self, query, limit=5, exclude_path=""):
        return CHUNKS[:limit]


def _hybrid():
    retriever = HybridRetriever(
        embedding=HashingEmbedding(), lexical=BM25Index(), vectors=InMemoryVectorIndex()
    )
    retriever.index(list(CHUNKS))
    return retriever


class TestTheDefault:
    def test_a_retriever_that_cannot_score_still_answers(self):
        results = _Unscored().scored("suppression", limit=2)

        assert len(results) == 2

    def test_its_results_are_marked_unscored(self):
        """AC-1. The floor reads this and reports itself as not applied."""
        assert all(not result.is_scored for result in _Unscored().scored("suppression", limit=2))

    def test_it_returns_the_same_chunks_as_related(self):
        scored = _Unscored().scored("suppression", limit=2)
        plain = _Unscored().related("suppression", limit=2)

        assert [result.chunk for result in scored] == plain


class TestTheHybridRetriever:
    def test_it_returns_scored_results(self):
        """AC-2 — the fused score it already computes internally."""
        results = _hybrid().scored("suppression directive silences a rule", limit=3)

        assert results
        assert all(result.is_scored for result in results)

    def test_the_scores_descend(self):
        results = _hybrid().scored("suppression directive silences a rule", limit=3)

        assert [result.score for result in results] == sorted(
            (result.score for result in results), reverse=True
        )

    def test_the_order_matches_related(self):
        """Two methods, one ranking. A scored query that reordered the results
        would make the floor drop a different chunk from the one it reported."""
        retriever = _hybrid()
        query = "suppression directive silences a rule"

        assert [result.chunk for result in retriever.scored(query, limit=3)] == retriever.related(
            query, limit=3
        )

    def test_an_empty_index_answers_nothing(self):
        empty = HybridRetriever(
            embedding=HashingEmbedding(), lexical=BM25Index(), vectors=InMemoryVectorIndex()
        )

        assert empty.scored("anything", limit=3) == []

    def test_the_limit_is_honoured(self):
        assert len(_hybrid().scored("rule", limit=1)) == 1

    def test_a_path_can_be_excluded(self):
        results = _hybrid().scored("rule", limit=5, exclude_path="a.py")

        assert all(result.chunk.path != "a.py" for result in results)
