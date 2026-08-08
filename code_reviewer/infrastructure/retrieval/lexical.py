"""BM25 over tokenised identifiers.

The lexical half of the hybrid. An exact identifier is the strongest signal
code search has — a reviewer looking for `authenticate_user` means that name,
not something adjacent to it — and an embedding blurs exactly that.

BM25 rather than plain term frequency because of the inverse document
frequency: `def` appears in every Python chunk and should therefore rank
nothing, while a name that appears in three chunks out of a thousand is almost
an answer on its own. That is the whole reason to compute a score rather than
count matches.

Forty lines and no dependency. A library would bring a tokeniser this project
would have to override anyway, because it shares its tokeniser with the
embedding.
"""

import math
from collections import Counter

from code_reviewer.application.ports import LexicalIndex
from code_reviewer.domain.retrieval import CodeChunk, ScoredChunk

from .embedding import tokenise

#: Term-frequency saturation. Above it, a fourth occurrence of a word adds
#: almost nothing — which is what stops a chunk that repeats one identifier
#: from outranking one that uses it correctly.
DEFAULT_K1 = 1.5

#: How much document length is discounted for. At 0 length is ignored; at 1 it
#: is fully normalised. 0.75 is the standard compromise.
DEFAULT_B = 0.75


class BM25Index(LexicalIndex):
    """Okapi BM25 over chunk text."""

    def __init__(self, k1: float = DEFAULT_K1, b: float = DEFAULT_B):
        self._k1 = k1
        self._b = b
        self._chunks: list[CodeChunk] = []
        self._frequencies: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._document_count: Counter[str] = Counter()

    def add(self, chunks: list[CodeChunk]) -> None:
        for chunk in chunks:
            # The symbol name is indexed alongside the body, so a chunk is
            # findable by what it is called as well as by what it contains.
            tokens = tokenise(f"{chunk.name} {chunk.text}")
            frequencies = Counter(tokens)

            self._chunks.append(chunk)
            self._frequencies.append(frequencies)
            self._lengths.append(len(tokens))
            self._document_count.update(frequencies.keys())

    def search(self, query: str, limit: int) -> list[ScoredChunk]:
        terms = tokenise(query)
        if not terms or not self._chunks or limit <= 0:
            return []

        average_length = sum(self._lengths) / len(self._lengths)

        scored = [
            ScoredChunk(chunk=chunk, score=self._score(terms, index, average_length))
            for index, chunk in enumerate(self._chunks)
        ]
        # A chunk that matched nothing is not a weak answer, it is no answer.
        matched = [item for item in scored if item.score > 0.0]
        matched.sort(key=lambda item: (-item.score, item.chunk.citation))
        return matched[:limit]

    def _score(self, terms: list[str], index: int, average_length: float) -> float:
        frequencies = self._frequencies[index]
        length = self._lengths[index] or 1
        total = 0.0

        for term in terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            numerator = frequency * (self._k1 + 1)
            denominator = frequency + self._k1 * (1 - self._b + self._b * length / average_length)
            total += self._idf(term) * numerator / denominator

        return total

    def _idf(self, term: str) -> float:
        """Inverse document frequency, in the smoothed form.

        The classic formula goes negative for a term in more than half the
        corpus, which would let a common word *subtract* from a score and push
        a chunk containing the rare term below one that does not. Worse at this
        scale: with three chunks indexed, anything appearing in two of them
        scores zero, and a repository's first index is always small. The `1 +`
        keeps every term positive and preserves the ordering that matters —
        a term in one chunk out of three is worth several times one in all
        three. It is the form Lucene uses, for the same reason.
        """
        total = len(self._chunks)
        containing = self._document_count.get(term, 0)
        return math.log(1 + (total - containing + 0.5) / (containing + 0.5))
