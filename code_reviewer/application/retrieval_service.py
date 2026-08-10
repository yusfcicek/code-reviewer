"""Two searches, fused and diversified.

The adapter behind :class:`~code_reviewer.application.ports.CodeRetriever`. It
lives in the application layer rather than in infrastructure because it touches
nothing: it is composed entirely of ports and of domain arithmetic, and the
only reason it is not in the domain is that it *orchestrates* — it decides how
many candidates to ask each index for, and what to do when one of them falls
over.

That last part is the contract worth stating twice: retrieval is an
improvement to the prompt, never a precondition for reviewing. An index that
raises costs the review some context and nothing else (decision D-5). This is
the opposite of the rule Level 9 applied to static analysis, and deliberately
so — a gate must not read "nothing examined" as "nothing found", but a prompt
with less context in it is still a prompt.
"""

import logging

from code_reviewer.domain.retrieval import (
    CodeChunk,
    ScoredChunk,
    Vector,
    maximal_marginal_relevance,
    reciprocal_rank_fusion,
)

from .ports import CodeRetriever, EmbeddingModel, LexicalIndex, VectorIndex

logger = logging.getLogger(__name__)

#: How many candidates each index is asked for before fusion. Larger than the
#: final limit on purpose: fusion can only reorder what it was given, and
#: diversification can only drop.
DEFAULT_CANDIDATES = 20


class HybridRetriever(CodeRetriever):
    """BM25 and cosine, fused by rank, reduced by marginal relevance.

    Args:
        embedding: Turns the query into a vector.
        lexical: The keyword half.
        vectors: The dense half, which also stores the vectors that
            diversification compares candidates by.
        candidates: How deep each index is searched before fusion.
        relevance_weight: λ. At 1.0 the result is the fused ranking; lower
            trades relevance for novelty.
    """

    def __init__(
        self,
        embedding: EmbeddingModel,
        lexical: LexicalIndex,
        vectors: VectorIndex,
        candidates: int = DEFAULT_CANDIDATES,
        relevance_weight: float = 0.7,
    ):
        self._embedding = embedding
        self._lexical = lexical
        self._vectors = vectors
        self._candidates = candidates
        self._relevance_weight = relevance_weight

    def index(self, chunks: list[CodeChunk]) -> None:
        """Adds chunks to both indexes, embedding them once."""
        if not chunks:
            return
        vectors = self._embedding.embed([chunk.text for chunk in chunks])
        self._lexical.add(list(chunks))
        self._vectors.add(list(zip(chunks, vectors, strict=True)))

    def related(self, query: str, limit: int = 5, exclude_path: str = "") -> list[CodeChunk]:
        if limit <= 0 or not query.strip():
            return []

        lexical_hits = self._lexical_candidates(query, exclude_path)
        dense_hits = self._dense_candidates(query, exclude_path)

        fused = reciprocal_rank_fusion([lexical_hits, dense_hits])
        if not fused:
            return []

        known: dict[CodeChunk, Vector] = {}
        for scored in fused:
            vector = self._vectors.vector_of(scored.chunk)
            if vector is not None:
                known[scored.chunk] = vector

        return maximal_marginal_relevance(fused, known, limit=limit, relevance_weight=self._relevance_weight)

    def scored(self, query: str, limit: int = 5, exclude_path: str = "") -> list[ScoredChunk]:
        """The same ranking, with the fused score this already computes.

        Two methods, one ranking: the chunks and their order match
        :meth:`related` exactly. A scored query that reordered its results would
        make a floor drop a different chunk from the one it reported dropping.
        """
        chosen = self.related(query, limit=limit, exclude_path=exclude_path)
        if not chosen:
            return []

        fused = reciprocal_rank_fusion(
            [self._lexical_candidates(query, exclude_path), self._dense_candidates(query, exclude_path)]
        )
        by_chunk = {scored.chunk: scored.score for scored in fused}
        return [ScoredChunk(chunk=chunk, score=by_chunk.get(chunk, 0.0)) for chunk in chosen]

    # -- internals ----------------------------------------------------------

    def _lexical_candidates(self, query: str, exclude_path: str) -> list[CodeChunk]:
        try:
            results = self._lexical.search(query, self._candidates)
        except Exception as error:
            # One index falling over leaves the other's answer, which is worse
            # than a hybrid and much better than nothing.
            logger.warning("Lexical search failed; continuing without it: %s", error)
            return []
        return _without(results, exclude_path)

    def _dense_candidates(self, query: str, exclude_path: str) -> list[CodeChunk]:
        try:
            vector = self._embedding.embed([query])[0]
            results = self._vectors.search(vector, self._candidates)
        except Exception as error:
            logger.warning("Vector search failed; continuing without it: %s", error)
            return []
        return _without(results, exclude_path)


def query_from_change(path: str, diff: str, max_characters: int = 2000) -> str:
    """A retrieval query built from what the change actually says.

    The added lines, plus the file's own name. Removed lines are left out on
    purpose: retrieval is looking for code *like the new code*, and the
    strongest signal for that is the identifiers the author just wrote.

    Diff markers are stripped, because `+` and `@@` are not identifiers and
    the tokeniser would keep them out of the vocabulary either way — but a
    hunk header carries line numbers that would become tokens, and a query
    full of integers ranks by nothing.
    """
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return f"{name}\n" + "\n".join(added)[:max_characters]


def _without(results, exclude_path: str) -> list[CodeChunk]:
    """Drops chunks from a file the caller already has in full.

    Re-showing the file under review is the one certain waste of a token
    budget: the reviewer was handed it whole before retrieval ran.
    """
    return [scored.chunk for scored in results if scored.chunk.path != exclude_path]
