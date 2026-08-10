"""What a retrieved piece of code is, and how a set of them is chosen.

The reviewer sees one diff and one file. Every question a human reviewer asks
second — is there already a helper for this, is this the pattern the rest of
the codebase uses, who calls this and what do they assume — needs evidence from
outside the diff (capabilities C-04 to C-06).

Two of the three hard parts of getting that evidence are arithmetic, and they
live here for the same reason `gate.py` and `evaluation.py` do: no filesystem,
no model, no index, and every edge case decidable with a list of four items.

**Fusing two rankings.** BM25 returns unbounded scores whose scale depends on
the corpus; cosine returns [-1, 1]. Making them comparable needs a constant
that is right for one repository and wrong for the next. Reciprocal rank fusion
throws the magnitudes away and keeps the order, which is the choice that needs
no tuning — and an untuned system that works is worth more than a tuned one
that works on one corpus (decision D-2).

**Diversifying what survives.** Three near-identical chunks are three copies of
one piece of evidence, and the token budget is real. Maximal marginal relevance
trades relevance against novelty by a stated weight.

Building the index is not here. That is I/O, and it belongs in an adapter.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: What a retriever with no notion of a score reports. NaN rather than a
#: sentinel number: every comparison against it is false, so a floor cannot
#: accidentally pass or fail it — it has to be asked about explicitly.
UNSCORED = float("nan")

#: An embedding. A plain tuple so it is hashable, immutable and framework-free.
Vector = tuple[float, ...]

#: Reciprocal rank fusion's smoothing constant. 60 is the value the original
#: paper used and the one every implementation since has kept; it is here as a
#: named default rather than a literal so a caller can say it changed it.
DEFAULT_RANK_CONSTANT = 60


@dataclass(frozen=True)
class CodeChunk:
    """One retrievable piece of source, and where it came from."""

    path: str
    start_line: int
    end_line: int
    text: str
    #: The qualified symbol name when the chunker knew one — `Class.method`.
    #: Empty for a line window, which is what a file that does not parse gets.
    name: str = ""

    def __post_init__(self) -> None:
        if not self.text.strip():
            # An index full of empty strings scores nothing and hides the
            # chunker bug that produced it.
            raise ValueError(f"A chunk must have text: {self.path}:{self.start_line}")
        if self.end_line < self.start_line:
            raise ValueError(f"A chunk cannot end before it starts: {self.path}")

    @property
    def citation(self) -> str:
        """Where this came from, as a reader would write it."""
        if self.start_line == self.end_line:
            return f"{self.path}:{self.start_line}"
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def __str__(self) -> str:
        heading = f"{self.citation} {self.name}".strip()
        return f"{heading}\n{self.text}"


@dataclass(frozen=True)
class ScoredChunk:
    """A chunk and how well it did, in whatever ranking produced it.

    ``score`` may be :data:`UNSCORED`, which is a different statement from a
    score of nought: it means the ranking that produced this chunk has no
    notion of a score at all. A floor applied to unscored results must report
    itself as inapplicable rather than passing everything — silence there is
    how Level 23 lost a whole tier for a whole level (Level 27, decision D-2).
    """

    chunk: CodeChunk
    score: float

    @property
    def is_scored(self) -> bool:
        return self.score is not UNSCORED and self.score == self.score


def render_chunks(chunks: Sequence[CodeChunk], separator: str = "\n\n") -> str:
    """Retrieved chunks under their citations.

    The citation matters as much as the code: a reviewer told "this pattern
    already exists" has to be able to go and look, and a claim with no
    `path:line` behind it is an assertion rather than evidence.

    One renderer, because the prompt and the `search_related_code` tool show
    the same thing and two formats would eventually disagree about what a
    citation looks like.
    """
    return separator.join(f"--- {chunk}" for chunk in chunks)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[CodeChunk]], k: int = DEFAULT_RANK_CONSTANT
) -> list[ScoredChunk]:
    """Combines rankings by position, ignoring the scores that produced them.

    Each ranking contributes ``1 / (k + rank)`` to every chunk it names, with
    rank counted from one. A chunk placed second in both rankings therefore
    beats one placed first in one and twentieth in the other — which is the
    behaviour that makes fusing two retrievers worth the code, and it arrives
    without a weight anyone has to choose.

    ``k`` smooths how sharply first place dominates: small values make rank 1
    worth much more than rank 2, large values flatten the curve.
    """
    if k <= 0:
        raise ValueError("The rank constant must be positive; it is added to a rank, not to a score.")

    totals: dict[CodeChunk, float] = {}
    for ranking in rankings:
        seen: set[CodeChunk] = set()
        rank = 0
        for chunk in ranking:
            # A retriever that returns the same chunk twice gets one vote for
            # it, not two.
            if chunk in seen:
                continue
            seen.add(chunk)
            rank += 1
            totals[chunk] = totals.get(chunk, 0.0) + 1.0 / (k + rank)

    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0].citation))
    return [ScoredChunk(chunk=chunk, score=score) for chunk, score in ordered]


def cosine_similarity(left: Vector, right: Vector) -> float:
    """Cosine of the angle between two vectors, and 0.0 for a zero vector.

    Zero rather than an exception: a zero vector means "this text embedded to
    nothing", which is a fact about the input, and retrieval degrades on it
    rather than failing the review (decision D-5).
    """
    if len(left) != len(right):
        raise ValueError(f"Vectors of different sizes cannot be compared: {len(left)} and {len(right)}")

    magnitude = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if magnitude == 0.0:
        return 0.0

    product = sum(a * b for a, b in zip(left, right, strict=True))
    # Floating-point arithmetic can put an identical pair a hair above 1.0,
    # and a similarity outside its own range is a bug waiting to be found by
    # something downstream.
    return max(-1.0, min(1.0, product / magnitude))


def maximal_marginal_relevance(
    ranked: Sequence[ScoredChunk],
    vectors: Mapping[CodeChunk, Vector],
    limit: int,
    relevance_weight: float = 0.7,
) -> list[CodeChunk]:
    """Selects ``limit`` chunks, trading relevance against novelty.

    At each step the chunk maximising
    ``λ · relevance − (1 − λ) · (similarity to the most similar chunk already
    chosen)`` is taken. At ``λ = 1`` that is the ranking unchanged; at
    ``λ = 0`` it is whatever is least like what has been selected so far.

    The first pick is always the most relevant, whatever ``λ`` says: with
    nothing selected there is nothing to be diverse from, and leaving that
    to a tie-break would make the whole result depend on dictionary order.

    Relevance is rescaled against the best score in ``ranked``, because the
    fused scores are around 1/60 while similarities are around 1, and
    subtracting one from the other unscaled would make ``λ`` meaningless.

    A chunk with no vector is treated as similar to nothing. Retrieval
    degrades; it does not drop evidence because an embedding is missing.
    """
    if not 0.0 <= relevance_weight <= 1.0:
        raise ValueError("The relevance weight is a proportion between 0 and 1.")
    if limit <= 0 or not ranked:
        return []

    best_score = max(scored.score for scored in ranked) or 1.0
    remaining = list(ranked)
    selected: list[CodeChunk] = []

    while remaining and len(selected) < limit:
        if not selected:
            chosen = max(remaining, key=lambda scored: scored.score)
        else:
            chosen = max(
                remaining,
                key=lambda scored: (
                    relevance_weight * (scored.score / best_score)
                    - (1.0 - relevance_weight) * _closest(scored.chunk, selected, vectors)
                ),
            )
        remaining.remove(chosen)
        selected.append(chosen.chunk)

    return selected


def _closest(
    candidate: CodeChunk, selected: Sequence[CodeChunk], vectors: Mapping[CodeChunk, Vector]
) -> float:
    """How like the most similar already-selected chunk this candidate is."""
    candidate_vector = vectors.get(candidate)
    if candidate_vector is None:
        return 0.0

    similarities = [
        cosine_similarity(candidate_vector, vectors[chunk]) for chunk in selected if chunk in vectors
    ]
    return max(similarities) if similarities else 0.0
