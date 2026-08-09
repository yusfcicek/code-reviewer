"""Step 3 — grading a corpus, and what the report says."""

from code_reviewer.application.narration_evaluation import NarrationEvaluator
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.narration import CHECKS, REQUIRED_SECTIONS, NarrationCase
from code_reviewer.domain.severity import Severity

SECTIONS = "\n".join(f"## {section}" for section in REQUIRED_SECTIONS)
GOOD = f"{SECTIONS}\n\nThe SQL Injection at `src/app.py:11` is CRITICAL."
BAD = f"{SECTIONS}\n\nSee `src/auth.py:900`. I approve this merge request."

CURRENT = "b6b17025f0c5"


def _finding() -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.CRITICAL,
        file_path="src/app.py",
        line_number=11,
        title="SQL Injection",
        description="concatenated",
        remediation="parameterise",
        rule_id="SAST.SQL_INJECTION",
    )


def _case(name: str, review: str, fingerprint: str = CURRENT) -> NarrationCase:
    return NarrationCase(
        name=name,
        file_path="src/app.py",
        line_count=40,
        review=review,
        findings=(_finding(),),
        prompt_fingerprint=fingerprint,
    )


def _evaluate(cases, fingerprint: str = CURRENT):
    return NarrationEvaluator().evaluate(cases, current_fingerprint=fingerprint)


# -- one case ----------------------------------------------------------------


def test_a_case_is_graded_by_every_check():
    report = _evaluate([_case("good", GOOD)])

    assert len(report.graded) == 1
    assert len(report.graded[0].results) == len(CHECKS)


def test_a_review_that_passes_everything_scores_one():
    report = _evaluate([_case("good", GOOD)])

    assert report.score == 1.0
    assert report.failures == ()


def test_a_review_that_fails_a_check_is_named_with_the_reason():
    report = _evaluate([_case("bad", BAD)])

    assert report.score < 1.0
    details = [failure.detail for failure in report.failures if failure.case == "bad"]
    checks = {failure.check for failure in report.failures if failure.case == "bad"}
    assert "citations_are_grounded" in checks
    assert any("src/auth.py:900" in detail for detail in details)


# -- the corpus --------------------------------------------------------------


def test_the_score_is_the_share_of_checks_that_passed():
    """Per check rather than per case: a review with one flaw is not as wrong
    as a review with five, and a per-case score cannot say so."""
    report = _evaluate([_case("good", GOOD), _case("bad", BAD)])

    total = 2 * len(CHECKS)
    passed = sum(1 for graded in report.graded for result in graded.results if result.passed)
    assert report.score == passed / total


def test_each_check_has_its_own_rate():
    report = _evaluate([_case("good", GOOD), _case("bad", BAD)])

    assert report.rate_for("citations_are_grounded") == 0.5
    assert report.rate_for("required_sections_are_present") == 1.0


def test_an_empty_corpus_scores_nothing_and_says_so():
    """Not 1.0. A corpus of nothing passing everything is the failure mode a
    floor exists to catch."""
    report = _evaluate([])

    assert report.score == 0.0
    assert report.case_count == 0


def test_two_runs_over_one_corpus_produce_the_same_report():
    cases = [_case("good", GOOD), _case("bad", BAD)]

    assert _evaluate(cases) == _evaluate(cases)


def test_the_cases_are_reported_in_the_order_they_were_given():
    report = _evaluate([_case("b", GOOD), _case("a", GOOD)])

    assert [graded.case for graded in report.graded] == ["b", "a"]


# -- staleness ---------------------------------------------------------------


def test_a_case_recorded_under_another_prompt_is_counted_as_stale():
    report = _evaluate([_case("old", GOOD, fingerprint="0000deadbeef"), _case("new", GOOD)])

    assert report.stale == ("old",)


def test_a_corpus_recorded_under_the_current_prompt_is_not_stale():
    assert _evaluate([_case("new", GOOD)]).stale == ()


def test_a_case_with_no_fingerprint_is_stale_rather_than_current():
    """ "Recorded under an unknown prompt" is not evidence that it was this
    one, and a floor held by unattributable recordings holds nothing."""
    assert _evaluate([_case("unattributed", GOOD, fingerprint="")]).stale == ("unattributed",)


def test_staleness_does_not_change_the_score():
    """The checks are about groundedness, which an old prompt does not make
    less true. It changes what the number is evidence *of*, and that is
    reported rather than folded into it."""
    fresh = _evaluate([_case("a", GOOD)])
    stale = _evaluate([_case("a", GOOD, fingerprint="0000deadbeef")])

    assert fresh.score == stale.score


# -- cases that are meant to fail --------------------------------------------


def _declared(name: str, review: str, expected) -> NarrationCase:
    return NarrationCase(
        name=name,
        file_path="src/app.py",
        line_count=40,
        review=review,
        findings=(_finding(),),
        prompt_fingerprint=CURRENT,
        expected_failures=tuple(expected),
    )


def test_a_case_that_fails_the_check_it_declared_scores_as_agreement():
    """The instrument proving it can fail. Without a case like this, a corpus
    of clean reviews cannot distinguish working checks from absent ones."""
    hallucinating = f"{SECTIONS}\n\nThe SQL Injection at `src/auth.py:900` is CRITICAL."

    report = _evaluate([_declared("hallucinated", hallucinating, ["citations_are_grounded"])])

    assert report.score == 1.0
    assert report.failures == ()


def test_a_case_that_passes_a_check_it_was_meant_to_fail_is_a_failure():
    """The check stopped working, or somebody fixed the case and forgot to
    say so. Either way the corpus no longer means what it says."""
    report = _evaluate([_declared("supposedly-bad", GOOD, ["citations_are_grounded"])])

    assert report.score < 1.0
    assert report.failures[0].check == "citations_are_grounded"
    assert "was expected to fail" in report.failures[0].detail


def test_an_undeclared_failure_is_still_a_failure():
    report = _evaluate([_declared("bad", BAD, ["citations_are_grounded"])])

    checks = {failure.check for failure in report.failures}
    assert "the_prose_claims_no_verdict" in checks
    assert "citations_are_grounded" not in checks
