"""Step 1 — the confusion matrix and the three ratios derived from it."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.evaluation import ConfusionMatrix

_COUNTS = st.integers(min_value=0, max_value=50)


def test_precision_recall_and_f1_of_a_hand_computed_matrix():
    matrix = ConfusionMatrix(true_positives=6, false_positives=2, false_negatives=3)

    assert matrix.precision == pytest.approx(6 / 8)
    assert matrix.recall == pytest.approx(6 / 9)
    assert matrix.f1 == pytest.approx(2 * (6 / 8) * (6 / 9) / ((6 / 8) + (6 / 9)))


def test_a_case_with_nothing_to_find_and_nothing_found_scores_one():
    """Not a ZeroDivisionError, and not zero.

    A clean fixture on which the suite stays quiet is the behaviour the
    dataset wants most. Scoring it 0.0 would make adding such a case lower
    the run's F1, which is precisely backwards.
    """
    empty = ConfusionMatrix()

    assert empty.precision == 1.0
    assert empty.recall == 1.0
    assert empty.f1 == 1.0


def test_only_false_positives_scores_zero_precision_and_perfect_recall():
    matrix = ConfusionMatrix(true_positives=0, false_positives=4, false_negatives=0)

    assert matrix.precision == 0.0
    assert matrix.recall == 1.0
    assert matrix.f1 == 0.0


def test_only_false_negatives_scores_zero_recall_and_perfect_precision():
    matrix = ConfusionMatrix(true_positives=0, false_positives=0, false_negatives=4)

    assert matrix.precision == 1.0
    assert matrix.recall == 0.0
    assert matrix.f1 == 0.0


def test_matrices_add_component_wise():
    total = ConfusionMatrix(1, 2, 3) + ConfusionMatrix(10, 20, 30)

    assert total == ConfusionMatrix(11, 22, 33)


def test_summing_a_list_of_matrices_starts_from_the_empty_one():
    matrices = [ConfusionMatrix(1, 0, 0), ConfusionMatrix(0, 1, 0), ConfusionMatrix(0, 0, 1)]

    assert ConfusionMatrix.total(matrices) == ConfusionMatrix(1, 1, 1)
    assert ConfusionMatrix.total([]) == ConfusionMatrix()


@given(_COUNTS, _COUNTS, _COUNTS)
def test_f1_lies_between_precision_and_recall(true_positives, false_positives, false_negatives):
    matrix = ConfusionMatrix(true_positives, false_positives, false_negatives)

    low, high = sorted((matrix.precision, matrix.recall))
    assert low - 1e-9 <= matrix.f1 <= high + 1e-9


@given(_COUNTS, _COUNTS, _COUNTS)
def test_every_ratio_is_a_probability(true_positives, false_positives, false_negatives):
    matrix = ConfusionMatrix(true_positives, false_positives, false_negatives)

    assert 0.0 <= matrix.precision <= 1.0
    assert 0.0 <= matrix.recall <= 1.0
    assert 0.0 <= matrix.f1 <= 1.0


@given(st.lists(st.tuples(_COUNTS, _COUNTS, _COUNTS), max_size=8))
def test_addition_is_associative(triples):
    matrices = [ConfusionMatrix(*triple) for triple in triples]

    left = ConfusionMatrix()
    for matrix in matrices:
        left = left + matrix

    assert left == ConfusionMatrix.total(matrices)


def test_counts_may_not_be_negative():
    with pytest.raises(ValueError):
        ConfusionMatrix(true_positives=-1)
