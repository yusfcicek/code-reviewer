"""Step 3 — aggregating case results, and the threshold that judges them."""

from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.evaluation import (
    CaseError,
    ConfusionMatrix,
    EvaluationCase,
    EvaluationReport,
    EvaluationThreshold,
    ExpectedFinding,
    grade,
)
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity

_RULES = ["SAST.SQL_INJECTION", "SAST.WEAK_CRYPTO", "QUALITY.GOD_CLASS", "PERFORMANCE.N_PLUS_ONE"]


def _finding(rule_id: str, line: int) -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.HIGH,
        file_path="fixture.py",
        line_number=line,
        title=rule_id,
        description="",
        remediation="",
        rule_id=rule_id,
    )


def _case(name: str, *expected: ExpectedFinding) -> EvaluationCase:
    return EvaluationCase(name=name, file_path=f"{name}.py", expected=tuple(expected))


def test_the_overall_matrix_is_the_sum_of_the_cases():
    hit = grade(_case("hit", ExpectedFinding("SAST.SQL_INJECTION", 1)), [_finding("SAST.SQL_INJECTION", 1)])
    miss = grade(_case("miss", ExpectedFinding("SAST.WEAK_CRYPTO", 2)), [])

    report = EvaluationReport(results=(hit, miss))

    assert report.overall == ConfusionMatrix(true_positives=1, false_negatives=1)
    assert report.case_count == 2


def test_a_rule_seen_only_as_a_false_positive_still_gets_a_row():
    result = grade(_case("noisy"), [_finding("QUALITY.GOD_CLASS", 7)])

    report = EvaluationReport(results=(result,))

    assert report.by_rule == {"QUALITY.GOD_CLASS": ConfusionMatrix(false_positives=1)}


def test_a_rule_seen_only_as_a_false_negative_still_gets_a_row():
    result = grade(_case("silent", ExpectedFinding("SAST.WEAK_CRYPTO", 3)), [])

    report = EvaluationReport(results=(result,))

    assert report.by_rule == {"SAST.WEAK_CRYPTO": ConfusionMatrix(false_negatives=1)}


def test_ungraded_findings_are_counted_across_the_run():
    scoped = EvaluationCase(name="scoped", file_path="a.py", scope=("SAST.*",))
    result = grade(scoped, [_finding("QUALITY.GOD_CLASS", 1), _finding("PERFORMANCE.N_PLUS_ONE", 2)])

    report = EvaluationReport(results=(result,))

    assert report.ungraded_count == 2
    assert report.ungraded_rule_ids == ("PERFORMANCE.N_PLUS_ONE", "QUALITY.GOD_CLASS")


@given(
    st.lists(
        st.tuples(
            st.lists(st.tuples(st.sampled_from(_RULES), st.integers(1, 40)), max_size=4),
            st.lists(st.tuples(st.sampled_from(_RULES), st.integers(1, 40)), max_size=4),
        ),
        max_size=5,
    )
)
def test_the_per_rule_matrices_sum_to_the_overall_matrix(cases):
    results = [
        grade(
            EvaluationCase(
                name=f"case-{index}",
                file_path=f"case-{index}.py",
                expected=tuple(ExpectedFinding(rule, line) for rule, line in expected),
            ),
            [_finding(rule, line) for rule, line in produced],
        )
        for index, (expected, produced) in enumerate(cases)
    ]

    report = EvaluationReport(results=tuple(results))

    assert ConfusionMatrix.total(report.by_rule.values()) == report.overall


# -- the threshold -----------------------------------------------------------


def _report_scoring(true_positives: int, false_positives: int, false_negatives: int) -> EvaluationReport:
    expected = tuple(ExpectedFinding("SAST.SQL_INJECTION", line) for line in range(1, true_positives + 1))
    missing = tuple(ExpectedFinding("SAST.WEAK_CRYPTO", line) for line in range(100, 100 + false_negatives))
    produced = [_finding("SAST.SQL_INJECTION", line) for line in range(1, true_positives + 1)]
    produced += [_finding("QUALITY.GOD_CLASS", line) for line in range(200, 200 + false_positives)]

    case = EvaluationCase(name="synthetic", file_path="s.py", expected=expected + missing)
    return EvaluationReport(results=(grade(case, produced),))


def test_a_report_meeting_every_bound_has_no_shortfalls():
    """The floor is on the interval's lower bound since Level 25, so a floor a
    five-finding sample can actually support is a low one."""
    threshold = EvaluationThreshold(min_precision=0.3, min_recall=0.3, min_f1=0.3)

    assert threshold.shortfalls(_report_scoring(4, 1, 1)) == []


def test_a_small_sample_cannot_support_a_high_floor_however_well_it_scores():
    """Level 25's whole point, at the level of one report: 4 of 5 is 0.80, and
    0.80 over five findings is consistent with a real rate under a half."""
    threshold = EvaluationThreshold(min_precision=0.5)

    assert threshold.shortfalls(_report_scoring(4, 1, 1)) != []


def test_the_shortfall_says_which_of_the_two_problems_it_is():
    reason = EvaluationThreshold(min_precision=0.5).shortfalls(_report_scoring(4, 1, 1))[0]

    assert "too small" in reason


def test_each_breached_bound_is_named_with_its_floor_and_its_value():
    threshold = EvaluationThreshold(min_precision=0.99, min_recall=0.99, min_f1=0.99)

    shortfalls = threshold.shortfalls(_report_scoring(2, 2, 2))

    assert len(shortfalls) == 3
    assert any("precision" in text and "0.99" in text and "0.50" in text for text in shortfalls)
    assert any("recall" in text for text in shortfalls)
    assert any("f1" in text for text in shortfalls)


def test_only_the_breached_bound_is_named():
    threshold = EvaluationThreshold(min_precision=0.99, min_recall=0.0, min_f1=0.0)

    shortfalls = threshold.shortfalls(_report_scoring(2, 2, 0))

    assert [text.split()[0] for text in shortfalls] == ["precision"]


def test_a_case_error_puts_the_report_below_any_threshold():
    """A perfect score over the cases that ran is not a perfect score.

    The scored subset is exactly the subset that did not crash, so letting
    the numbers stand would reward a change that broke an analyzer on the
    hardest fixture.
    """
    report = EvaluationReport(
        results=_report_scoring(4, 0, 0).results,
        errors=(CaseError(name="weak-crypto", reason="RecursionError in the AST walk"),),
    )
    threshold = EvaluationThreshold(min_precision=0.0, min_recall=0.0, min_f1=0.0)

    assert not threshold.is_met(report)
    assert any("weak-crypto" in text for text in threshold.shortfalls(report))
    assert report.has_errors


def test_a_report_with_no_cases_at_all_is_not_a_pass():
    """An empty dataset scores 1.0 on every ratio, which is meaningless."""
    threshold = EvaluationThreshold(min_precision=0.9, min_recall=0.9, min_f1=0.9)

    assert not threshold.is_met(EvaluationReport())
    assert any("no cases" in text for text in threshold.shortfalls(EvaluationReport()))
