"""Brute-force nearest-neighbour search over embedded chunks.

Approximate indexes — HNSW and its relatives — earn their complexity above
roughly 10⁵ vectors. A repository's worth of chunks is two orders of magnitude
below that, and an exhaustive cosine scan over it takes microseconds. Choosing
an approximate index at this size would be architecture as costume
(decision D-4).

It is recorded as a decision rather than left as an omission so that the next
person reads it as a choice. When a corpus arrives that needs one, `VectorIndex`
is the port and this is the module that gets a sibling.
"""

from code_reviewer.application.ports import VectorIndex
from code_reviewer.domain.retrieval import CodeChunk, ScoredChunk, Vector, cosine_similarity


class InMemoryVectorIndex(VectorIndex):
    """Every vector, scanned every time."""

    def __init__(self) -> None:
        self._entries: list[tuple[CodeChunk, Vector]] = []
        self._by_chunk: dict[CodeChunk, Vector] = {}
        self._dimensions: int | None = None

    def add(self, entries: list[tuple[CodeChunk, Vector]]) -> None:
        for chunk, vector in entries:
            if self._dimensions is None:
                self._dimensions = len(vector)
            elif len(vector) != self._dimensions:
                # Silently skipping would leave a chunk in the corpus that can
                # never be found by anything, which is worse than failing here.
                raise ValueError(
                    f"This index holds {self._dimensions}-dimensional vectors; "
                    f"'{chunk.citation}' arrived with {len(vector)}."
                )
            self._entries.append((chunk, vector))
            self._by_chunk[chunk] = vector

    def search(self, vector: Vector, limit: int) -> list[ScoredChunk]:
        if limit <= 0 or not self._entries:
            return []

        scored = [
            ScoredChunk(chunk=chunk, score=cosine_similarity(vector, stored))
            for chunk, stored in self._entries
            if len(stored) == len(vector)
        ]
        scored.sort(key=lambda item: (-item.score, item.chunk.citation))
        return scored[:limit]

    def vector_of(self, chunk: CodeChunk) -> Vector | None:
        return self._by_chunk.get(chunk)

    def __len__(self) -> int:
        return len(self._entries)
