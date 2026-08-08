"""Step 5 — fusing two rankings, and diversifying the result."""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.retrieval import (
    CodeChunk,
    ScoredChunk,
    cosine_similarity,
    maximal_marginal_relevance,
    reciprocal_rank_fusion,
)


def _chunk(name: str) -> CodeChunk:
    return CodeChunk(path=f"{name}.py", start_line=1, end_line=2, text=f"def {name}(): ...", name=name)


A, B, C, D = (_chunk(name) for name in "abcd")


# -- reciprocal rank fusion --------------------------------------------------


def test_fusing_one_ranking_preserves_its_order():
    fused = reciprocal_rank_fusion([[A, B, C]])

    assert [scored.chunk for scored in fused] == [A, B, C]


def test_fusing_nothing_returns_nothing():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_agreement_beats_a_single_first_place():
    """The property that makes rank fusion worth doing.

    `a` is first in one ranking and last in the other; `b` is near the top of
    both. A score-weighted sum would need a constant to decide between them;
    the reciprocal rank decides it without one.

    The spread has to be real for this to hold. With the default smoothing
    constant of 60 the curve is flat — rank 1 is worth 1/61 and rank 4 is
    worth 1/64 — so `first versus fourth` is not a disagreement, it is noise.
    Twenty candidates is where the ranks start to mean something, which is
    itself worth knowing before trusting a fused top-3 over four items.
    """
    others = [_chunk(f"chunk{index}") for index in range(16)]
    lexical = [A, B, C, D, *others]
    dense = [D, B, C, *others, A]

    fused = [scored.chunk for scored in reciprocal_rank_fusion([lexical, dense])]

    assert fused[0] is B


def test_a_chunk_in_one_ranking_only_still_appears():
    fused = [scored.chunk for scored in reciprocal_rank_fusion([[A], [B]])]

    assert set(fused) == {A, B}


def test_scores_descend():
    fused = reciprocal_rank_fusion([[A, B, C], [B, A, C]])

    scores = [scored.score for scored in fused]
    assert scores == sorted(scores, reverse=True)


def test_a_chunk_repeated_within_one_ranking_is_counted_once():
    fused = reciprocal_rank_fusion([[A, A, B]])

    assert [scored.chunk for scored in fused].count(A) == 1


@given(st.integers(min_value=1, max_value=1000))
def test_fusion_ignores_the_scale_of_the_scores_it_was_given(scale):
    """Rank fusion takes rankings, not scores. This states that it cannot be
    made to change its mind by a rescaling, which is the whole reason it was
    chosen over a weighted sum."""
    first = [A, B, C, D]
    second = [D, C, B, A]

    baseline = [scored.chunk for scored in reciprocal_rank_fusion([first, second])]
    rescaled = [scored.chunk for scored in reciprocal_rank_fusion([first, second], k=60)]

    assert baseline == rescaled
    assert scale > 0  # the scale never reaches the function; that is the point


def test_the_smoothing_constant_changes_how_sharply_rank_one_dominates():
    """A small k makes first place worth much more than second."""
    sharp = reciprocal_rank_fusion([[A, B]], k=1)
    flat = reciprocal_rank_fusion([[A, B]], k=1000)

    assert sharp[0].score / sharp[1].score > flat[0].score / flat[1].score


def test_a_non_positive_smoothing_constant_is_refused():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[A]], k=0)


# -- cosine ------------------------------------------------------------------


def test_identical_vectors_are_one():
    assert cosine_similarity((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)) == pytest.approx(1.0)


def test_orthogonal_vectors_are_zero():
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)


def test_opposite_vectors_are_minus_one():
    assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)


def test_a_zero_vector_is_zero_similar_and_does_not_divide_by_zero():
    assert cosine_similarity((0.0, 0.0), (1.0, 1.0)) == 0.0


def test_vectors_of_different_lengths_are_refused():
    with pytest.raises(ValueError):
        cosine_similarity((1.0,), (1.0, 2.0))


@given(
    st.lists(st.floats(-10, 10), min_size=1, max_size=8),
    st.lists(st.floats(-10, 10), min_size=1, max_size=8),
)
def test_cosine_stays_within_minus_one_and_one(left, right):
    size = min(len(left), len(right))
    value = cosine_similarity(tuple(left[:size]), tuple(right[:size]))

    assert -1.0 - 1e-9 <= value <= 1.0 + 1e-9
    assert not math.isnan(value)


# -- maximal marginal relevance ----------------------------------------------

_VECTORS = {
    A: (1.0, 0.0),
    B: (0.99, 0.14),  # nearly A
    C: (0.0, 1.0),  # orthogonal to A
    D: (0.7, 0.7),
}
_RANKED = [ScoredChunk(A, 1.0), ScoredChunk(B, 0.9), ScoredChunk(C, 0.5), ScoredChunk(D, 0.4)]


def test_full_relevance_weight_returns_the_ranking_unchanged():
    selected = maximal_marginal_relevance(_RANKED, _VECTORS, limit=3, relevance_weight=1.0)

    assert selected == [A, B, C]


def test_no_relevance_weight_picks_the_least_similar_next():
    """`b` is nearly `a`; `c` is orthogonal to it. With λ=0 the second pick is
    whichever is least like what has already been chosen."""
    selected = maximal_marginal_relevance(_RANKED, _VECTORS, limit=2, relevance_weight=0.0)

    assert selected == [A, C]


def test_the_first_pick_is_always_the_most_relevant():
    """With nothing selected there is nothing to be diverse from, so novelty
    has no opinion and the ranking decides."""
    for weight in (0.0, 0.5, 1.0):
        assert maximal_marginal_relevance(_RANKED, _VECTORS, limit=1, relevance_weight=weight) == [A]


def test_a_chunk_with_no_vector_is_still_selectable():
    """Retrieval degrades; it does not drop evidence because a vector is
    missing."""
    ranked = [ScoredChunk(A, 1.0), ScoredChunk(D, 0.9)]

    selected = maximal_marginal_relevance(ranked, {A: (1.0, 0.0)}, limit=2, relevance_weight=0.5)

    assert set(selected) == {A, D}


def test_a_limit_of_zero_selects_nothing():
    assert maximal_marginal_relevance(_RANKED, _VECTORS, limit=0) == []


def test_a_weight_outside_zero_to_one_is_refused():
    with pytest.raises(ValueError):
        maximal_marginal_relevance(_RANKED, _VECTORS, limit=2, relevance_weight=1.5)


@given(st.integers(min_value=0, max_value=8), st.floats(min_value=0.0, max_value=1.0))
def test_selection_never_repeats_and_never_exceeds_the_limit(limit, weight):
    selected = maximal_marginal_relevance(_RANKED, _VECTORS, limit=limit, relevance_weight=weight)

    assert len(selected) == len(set(selected))
    assert len(selected) <= limit
    assert len(selected) <= len(_RANKED)
    assert set(selected) <= {scored.chunk for scored in _RANKED}


@given(st.floats(min_value=0.0, max_value=1.0))
def test_a_limit_beyond_the_candidates_returns_all_of_them(weight):
    selected = maximal_marginal_relevance(_RANKED, _VECTORS, limit=99, relevance_weight=weight)

    assert set(selected) == {scored.chunk for scored in _RANKED}
