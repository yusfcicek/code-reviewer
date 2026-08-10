"""Step 1 — an interval, and what it does at the boundary.

The boundary is the whole reason this module exists. Fifteen successes out of
fifteen has a normal-approximation interval of exactly `[1.00, 1.00]`, and that
is how a fifteen-case corpus came to be quoted like a measurement — in this
repository's README, its CHANGELOG and every level report since Level 21.

Wilson does not do that. It answers the question actually being asked: given
what was observed, what pass rates are still consistent with it?
"""

from code_reviewer.domain.confidence import Interval, wilson


class TestTheBoundary:
    def test_fifteen_of_fifteen_is_not_certainty(self):
        """The number this level exists for."""
        interval = wilson(15, 15)

        assert interval.point == 1.0
        assert interval.lower < 0.85

    def test_more_cases_narrow_it(self):
        assert wilson(150, 150).lower > wilson(15, 15).lower

    def test_many_more_narrow_it_further(self):
        assert wilson(1500, 1500).lower > wilson(150, 150).lower

    def test_it_never_reaches_certainty(self):
        """No finite sample proves a rate of 1.0, and the number should not
        imply one."""
        assert wilson(100_000, 100_000).lower < 1.0

    def test_zero_of_many_is_symmetric(self):
        """The interval refuses to conclude in both directions."""
        assert wilson(0, 15).upper > 0.15
        assert wilson(0, 15).upper < 0.30


class TestTheEdges:
    def test_no_cases_yields_the_whole_range(self):
        interval = wilson(0, 0)

        assert interval.lower == 0.0
        assert interval.upper == 1.0

    def test_no_cases_has_no_point_estimate_to_report(self):
        assert wilson(0, 0).point == 0.0

    def test_one_of_one_is_almost_uninformative(self):
        assert wilson(1, 1).lower < 0.35

    def test_bounds_stay_inside_zero_and_one(self):
        for successes, total in ((0, 1), (1, 1), (1, 2), (7, 9), (0, 1000), (1000, 1000)):
            interval = wilson(successes, total)

            assert 0.0 <= interval.lower <= interval.upper <= 1.0, (successes, total)

    def test_the_point_estimate_sits_inside_the_interval(self):
        for successes, total in ((1, 1), (1, 2), (7, 9), (14, 15)):
            interval = wilson(successes, total)

            assert interval.lower <= interval.point <= interval.upper, (successes, total)

    def test_more_successes_never_lower_the_bound(self):
        for total in (5, 15, 50):
            bounds = [wilson(successes, total).lower for successes in range(total + 1)]

            assert bounds == sorted(bounds), total

    def test_more_than_the_total_is_refused(self):
        import pytest

        with pytest.raises(ValueError):
            wilson(16, 15)

    def test_a_negative_count_is_refused(self):
        import pytest

        with pytest.raises(ValueError):
            wilson(-1, 15)


class TestSayingWhichConventionProducedIt:
    def test_the_interval_names_its_method(self):
        """Nobody should have to guess which convention produced a number they
        are about to quote."""
        assert "wilson" in wilson(15, 15).method.lower()

    def test_the_interval_names_its_confidence(self):
        assert wilson(15, 15).confidence == 0.95

    def test_it_renders_as_a_point_and_a_range(self):
        rendered = str(wilson(15, 15))

        assert "1.00" in rendered
        assert "[" in rendered and "]" in rendered

    def test_the_rendering_carries_the_sample_size(self):
        assert "15" in str(wilson(15, 15))

    def test_an_interval_can_be_built_directly(self):
        interval = Interval(point=0.5, lower=0.3, upper=0.7, total=10)

        assert interval.point == 0.5
        assert interval.total == 10


class TestF1HasNoSampleOfItsOwn:
    """Self-review S-02 — an interval around a different number.

    F1 is a harmonic mean, not a proportion, so there is no sample of successes
    to put an interval around. The first version manufactured one and printed
    it in the same column as precision and recall, where its bounds belonged to
    0.83 while the number beside them read 0.80.

    F1 is monotone increasing in both inputs, so a conservative bound is
    available honestly: the harmonic mean of the two bounds.
    """

    def test_the_bound_is_the_harmonic_mean_of_the_two_bounds(self):
        from code_reviewer.domain.confidence import f1_interval, harmonic

        interval = f1_interval(wilson(8, 10), wilson(8, 10))

        assert interval.lower == harmonic(wilson(8, 10).lower, wilson(8, 10).lower)

    def test_the_point_is_the_harmonic_mean_of_the_two_points(self):
        from code_reviewer.domain.confidence import f1_interval

        interval = f1_interval(wilson(8, 10), wilson(6, 10))

        assert abs(interval.point - 2 * 0.8 * 0.6 / (0.8 + 0.6)) < 1e-9

    def test_the_point_sits_inside_its_own_bounds(self):
        """The defect, stated as a property: it did not."""
        from code_reviewer.domain.confidence import f1_interval

        for successes in range(11):
            interval = f1_interval(wilson(successes, 10), wilson(10 - successes, 10))

            assert interval.lower <= interval.point <= interval.upper, successes

    def test_it_says_it_is_derived_rather_than_sampled(self):
        from code_reviewer.domain.confidence import f1_interval

        assert "derived" in f1_interval(wilson(8, 10), wilson(8, 10)).method.lower()

    def test_two_perfect_inputs_give_a_bound_below_one(self):
        from code_reviewer.domain.confidence import f1_interval

        assert f1_interval(wilson(10, 10), wilson(10, 10)).lower < 1.0

    def test_a_zero_input_gives_a_zero_point(self):
        from code_reviewer.domain.confidence import f1_interval

        assert f1_interval(wilson(0, 10), wilson(10, 10)).point == 0.0

    def test_the_total_is_the_smaller_of_the_two_samples(self):
        """The measurement is only as strong as its weaker half."""
        from code_reviewer.domain.confidence import f1_interval

        assert f1_interval(wilson(8, 10), wilson(3, 4)).total == 4


class TestCorrelatedObservations:
    """Self-review S-01 — 120 observations that were 24."""

    def test_the_helper_takes_the_number_of_independent_units(self):
        from code_reviewer.domain.confidence import wilson

        assert wilson(24, 24).total == 24
        assert wilson(24, 24).lower < wilson(120, 120).lower
