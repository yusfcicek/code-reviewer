"""Step 3 — the floor moves to the interval's lower bound.

This makes the gate **harder**, on purpose. Before, a corpus of fifteen cases
scoring 1.00 cleared a 0.95 floor — and 1.00 over fifteen is consistent with a
real pass rate of eighty per cent. The way to clear a floor becomes writing more
cases rather than having a better afternoon.

The alternative was to floor the point estimate and print the interval beside
it. That leaves the gate exactly as permissive as it was and adds decoration.
"""

from code_reviewer.domain.evaluation import (
    CaseResult,
    EvaluationCase,
    EvaluationReport,
    EvaluationThreshold,
    ExpectedFinding,
)
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity


def _finding(rule="R.A", line=1):
    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.HIGH,
        file_path="x.py",
        line_number=line,
        title="t",
        description="",
        remediation="",
        rule_id=rule,
    )


def _report(cases: int, hits: int, misses: int = 0):
    """`cases` graded cases carrying `hits` true positives and `misses` misses.

    Built out of real `CaseResult`s so the matrix is derived the way the
    production one is, rather than asserted into place.
    """
    expectation = ExpectedFinding("R.A", 1)
    results = []
    for index in range(cases):
        case = EvaluationCase(name=f"case-{index}", file_path="x", expected=(expectation,))
        if index < hits:
            results.append(CaseResult(case=case, matched=((expectation, _finding()),)))
        elif index < hits + misses:
            results.append(CaseResult(case=case, missed=(expectation,)))
        else:
            results.append(CaseResult(case=case))
    return EvaluationReport(results=tuple(results))


class TestTheFloorIsAppliedToTheLowerBound:
    def test_a_small_perfect_corpus_no_longer_clears_a_high_floor(self):
        """AC-5, and the finding this level is built on: 15/15 is consistent
        with a real rate of 0.80."""
        threshold = EvaluationThreshold(min_precision=0.95, min_recall=0.95, min_f1=0.95)

        assert threshold.shortfalls(_report(15, hits=15)) != []

    def test_a_large_perfect_corpus_clears_the_same_floor(self):
        threshold = EvaluationThreshold(min_precision=0.95, min_recall=0.95, min_f1=0.95)

        assert threshold.shortfalls(_report(200, hits=200)) == []

    def test_the_shortfall_names_the_bound_the_floor_and_the_sample(self):
        """So the reader knows whether to fix the reviewer or write more cases."""
        threshold = EvaluationThreshold(min_precision=0.95)

        reason = threshold.shortfalls(_report(15, hits=15))[0]

        assert "0.95" in reason
        assert "15" in reason
        assert "lower bound" in reason.lower()

    def test_an_empty_report_still_fails_for_being_empty(self):
        assert EvaluationThreshold().shortfalls(EvaluationReport()) != []

    def test_a_floor_of_zero_is_cleared_by_anything(self):
        assert EvaluationThreshold().shortfalls(_report(3, hits=1, misses=2)) == []
