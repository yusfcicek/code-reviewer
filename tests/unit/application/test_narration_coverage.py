"""Step 4 — coverage per check, in both directions.

An aggregate over five checks is five different questions averaged, and the
average moves by a fifth when one of them breaks completely. The self-review of
levels 21–22 found a check that caught three phrasings of eight and the score
never moved.

The direction that matters is the one nobody counts. Every check here is
*passed* by thirteen or fourteen cases; four of the five are **demonstrated
firing** by exactly one. A check whose firing behaviour is pinned by a single
example is pinned by whatever example its author had in mind — which is how the
three-of-eight defect survived a corpus built to demonstrate the check.
"""

from code_reviewer.application.narration_evaluation import (
    MINIMUM_DEMONSTRATIONS,
    CheckCoverage,
    NarrationEvaluator,
)
from code_reviewer.domain.narration import CHECK_NAMES, NarrationCase


def _case(name, review="## 🔒 Security Analysis\nfine\n", expected_failures=()):
    return NarrationCase(
        name=name,
        file_path="fixtures/subject.py",
        line_count=10,
        review=review,
        findings=(),
        expected_failures=tuple(expected_failures),
    )


def _coverage(cases):
    report = NarrationEvaluator().evaluate(cases)
    return {entry.check: entry for entry in report.coverage}


class TestWhatIsCounted:
    def test_every_check_appears(self):
        coverage = _coverage([_case("one")])

        assert set(coverage) == set(CHECK_NAMES)

    def test_a_case_that_passes_a_check_counts_towards_passing(self):
        coverage = _coverage([_case("one")])

        assert coverage["citations_are_grounded"].passing == 1

    def test_a_case_built_to_break_a_check_counts_as_a_demonstration(self):
        """The direction nobody counts, and the one a corpus is usually thin in."""
        broken = _case(
            "bad", review="I reject this merge request.\n", expected_failures=["the_prose_claims_no_verdict"]
        )

        assert _coverage([broken])["the_prose_claims_no_verdict"].firing == 1

    def test_a_case_that_breaks_a_check_by_accident_is_not_a_demonstration(self):
        """A case that fails a check it did not declare is a corpus defect, not
        evidence the check works."""
        accidental = _case("oops", review="I reject this merge request.\n")

        assert _coverage([accidental])["the_prose_claims_no_verdict"].firing == 0

    def test_the_two_directions_are_counted_separately(self):
        entry = _coverage([_case("one"), _case("two")])["citations_are_grounded"]

        assert entry.passing == 2
        assert entry.firing == 0


class TestWhatCountsAsUncovered:
    def test_a_check_nothing_demonstrates_is_uncovered(self):
        assert _coverage([_case("one")])["citations_are_grounded"].is_uncovered

    def test_a_check_nothing_passes_is_uncovered_too(self):
        """A check that only ever fires has never been shown to stay quiet, and
        a check that fires on everything is the failure mode of a checker."""
        broken = _case("bad", review="I reject this.\n", expected_failures=["the_prose_claims_no_verdict"])

        entry = CheckCoverage(check="x", passing=0, firing=3)

        assert entry.is_uncovered
        assert _coverage([broken])["the_prose_claims_no_verdict"].passing == 0

    def test_a_check_with_both_directions_is_covered(self):
        assert not CheckCoverage(check="x", passing=10, firing=3).is_uncovered

    def test_a_check_below_the_minimum_demonstration_count_is_thin(self):
        assert CheckCoverage(check="x", passing=10, firing=MINIMUM_DEMONSTRATIONS - 1).is_thin

    def test_a_check_at_the_minimum_is_not_thin(self):
        assert not CheckCoverage(check="x", passing=10, firing=MINIMUM_DEMONSTRATIONS).is_thin

    def test_the_minimum_is_more_than_one(self):
        """One example pins one author's idea of the check. That is exactly how
        the three-of-eight defect survived its own corpus."""
        assert MINIMUM_DEMONSTRATIONS > 1


class TestTheReportSaysIt:
    def test_coverage_is_reported_per_check(self):
        from code_reviewer.application.narration_report import render_narration_report

        text = render_narration_report(NarrationEvaluator().evaluate([_case("one")]), 0.0)

        assert "coverage" in text.lower()
        for name in CHECK_NAMES:
            assert name in text

    def test_a_thin_check_is_named_rather_than_averaged_away(self):
        from code_reviewer.application.narration_report import render_narration_report

        text = render_narration_report(NarrationEvaluator().evaluate([_case("one")]), 0.0)

        assert "citations_are_grounded" in text
        assert "demonstrat" in text.lower()

    def test_the_score_carries_its_interval(self):
        """AC-1 — no bare score survives this level."""
        from code_reviewer.application.narration_report import render_narration_report

        text = render_narration_report(NarrationEvaluator().evaluate([_case("one")]), 0.0)

        assert "[" in text and "]" in text

    def test_the_report_never_claims_the_corpus_is_adequate(self):
        """AC-17."""
        from code_reviewer.application.narration_report import render_narration_report

        text = render_narration_report(NarrationEvaluator().evaluate([_case("one")]), 0.0).lower()

        for word in ("large enough", "adequate", "representative", "statistically significant"):
            assert word not in text


WHOLE = """## 🔒 Security Analysis
- **SAST Scan Result**: PASS

## 🔍 Semantic Change Analysis
- **Change Type**: REFACTOR

## 🔗 Impact Analysis
- **Dependencies Checked**: `fixtures/subject.py`

## 📊 Code Quality
- **SOLID Compliance**: 90/100

## ⚡ Performance Analysis
- **Complexity Issues**: None
"""


class TestTheIntervalCountsIndependentUnits:
    """Self-review S-01 — 120 observations that were 24.

    The score counted 24 cases times 5 checks and handed 120 to Wilson as
    though they were independent trials. They are not, and the corpus makes it
    obvious: a review with no sections fails `required_sections_are_present`
    *and* usually `severe_findings_are_mentioned`, because the sections that
    would have mentioned the finding are the missing ones. Level 25's own
    `only-a-security-section` is exactly that shape.

    Treating them as independent narrowed the interval from [0.86, …] to
    [0.97, …] — and the narration floor was chosen from the narrow number, in
    the level built to remove overclaims.
    """

    def test_the_interval_is_over_cases_rather_than_checks(self):
        report = NarrationEvaluator().evaluate([_case("a"), _case("b")])

        assert report.score_interval.total == 2

    def test_a_case_counts_once_however_many_checks_it_has(self):
        report = NarrationEvaluator().evaluate([_case("a")])

        assert report.score_interval.total == 1

    def test_a_case_agreeing_everywhere_is_a_success(self):
        report = NarrationEvaluator().evaluate([_case("a", review=WHOLE)])

        assert report.score_interval.point == 1.0

    def test_a_case_disagreeing_anywhere_is_not_a_success(self):
        """Conservative on purpose: the unit is a review, and a review with one
        wrong claim in it is a review with a wrong claim in it."""
        broken = _case("bad", review="I reject this merge request.\n")

        assert NarrationEvaluator().evaluate([broken]).score_interval.point == 0.0

    def test_the_per_check_rates_are_unchanged(self):
        """They are descriptive and stay descriptive. Only the interval — the
        thing a floor is applied to — moved to an independent unit."""
        broken = _case("bad", review="I reject this merge request.\n")
        report = NarrationEvaluator().evaluate([_case("a", review=WHOLE), broken])

        assert report.rate_for("citations_are_grounded") == 1.0

    def test_the_score_itself_is_still_per_check(self):
        """A review with one flaw is not as wrong as a review with five, and
        the headline score should keep saying so."""
        broken = _case("bad", review="I reject this merge request.\n")
        report = NarrationEvaluator().evaluate([broken])

        assert 0.0 < report.score < 1.0

    def test_the_report_says_which_unit_the_interval_is_over(self):
        from code_reviewer.application.narration_report import render_narration_report

        text = render_narration_report(NarrationEvaluator().evaluate([_case("a")]), 0.0)

        assert "case" in text.lower()
