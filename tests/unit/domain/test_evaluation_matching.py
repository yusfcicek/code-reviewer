"""Step 2 — what satisfies an expectation, and what counts against the suite."""

from code_reviewer.domain.evaluation import (
    ConfusionMatrix,
    EvaluationCase,
    ExpectedFinding,
    ForbiddenFinding,
    grade,
)
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity


def _finding(rule_id: str, line: int, severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path="fixture.py",
        line_number=line,
        title=rule_id,
        description="",
        remediation="",
        rule_id=rule_id,
    )


def _case(**overrides) -> EvaluationCase:
    return EvaluationCase(**{"name": "case", "file_path": "fixture.py", **overrides})


# -- AC-1 --------------------------------------------------------------------


def test_an_exact_match_is_one_true_positive_and_nothing_else():
    case = _case(expected=(ExpectedFinding("SAST.SQL_INJECTION", 12),))

    result = grade(case, [_finding("SAST.SQL_INJECTION", 12)])

    assert result.matrix == ConfusionMatrix(true_positives=1)
    assert result.missed == ()
    assert result.spurious == ()
    assert result.ungraded == ()


def test_a_different_rule_at_the_same_line_satisfies_nothing():
    case = _case(expected=(ExpectedFinding("SAST.SQL_INJECTION", 12),))

    result = grade(case, [_finding("SAST.HARDCODED_SECRET", 12)])

    assert result.matrix == ConfusionMatrix(false_positives=1, false_negatives=1)
    assert [expectation.rule_id for expectation in result.missed] == ["SAST.SQL_INJECTION"]
    assert [finding.rule_id for finding in result.spurious] == ["SAST.HARDCODED_SECRET"]


# -- AC-2 --------------------------------------------------------------------


def test_a_line_within_tolerance_matches():
    case = _case(expected=(ExpectedFinding("SAST.SQL_INJECTION", 12),), line_tolerance=2)

    result = grade(case, [_finding("SAST.SQL_INJECTION", 14)])

    assert result.matrix == ConfusionMatrix(true_positives=1)


def test_a_line_outside_tolerance_is_both_a_miss_and_a_false_positive():
    """The rule fired, but not where the case says the defect is.

    Charged twice on purpose, and this is the one place the spec allows it:
    unlike a severity mismatch, there is no evidence the two are the same
    event. A rule that reports the wrong line has failed at the job the
    report exists to do, which is to point at something.
    """
    case = _case(expected=(ExpectedFinding("SAST.SQL_INJECTION", 12),), line_tolerance=2)

    result = grade(case, [_finding("SAST.SQL_INJECTION", 15)])

    assert result.matrix == ConfusionMatrix(false_positives=1, false_negatives=1)


# -- AC-3 --------------------------------------------------------------------


def test_the_closest_line_wins_and_the_order_findings_arrive_in_does_not_matter():
    case = _case(expected=(ExpectedFinding("PERF.NESTED_LOOP", 12),), line_tolerance=3)
    near = _finding("PERF.NESTED_LOOP", 11)
    far = _finding("PERF.NESTED_LOOP", 14)

    for arrival in ([near, far], [far, near]):
        result = grade(case, list(arrival))

        assert result.matrix == ConfusionMatrix(true_positives=1, false_positives=1)
        assert result.spurious == (far,)


def test_equidistant_findings_resolve_to_the_lower_line():
    case = _case(expected=(ExpectedFinding("PERF.NESTED_LOOP", 12),), line_tolerance=3)
    below = _finding("PERF.NESTED_LOOP", 10)
    above = _finding("PERF.NESTED_LOOP", 14)

    for arrival in ([below, above], [above, below]):
        result = grade(case, list(arrival))

        assert result.spurious == (above,)


# -- AC-4 --------------------------------------------------------------------


def test_a_severity_mismatch_is_a_miss_and_consumes_the_finding():
    case = _case(expected=(ExpectedFinding("SAST.SQL_INJECTION", 12, Severity.CRITICAL),))

    result = grade(case, [_finding("SAST.SQL_INJECTION", 12, Severity.HIGH)])

    assert result.matrix == ConfusionMatrix(false_negatives=1)
    assert result.spurious == ()
    assert [(item.expected.rule_id, item.found.severity) for item in result.mismatched] == [
        ("SAST.SQL_INJECTION", Severity.HIGH)
    ]


def test_an_expectation_without_a_severity_accepts_any():
    case = _case(expected=(ExpectedFinding("SAST.SQL_INJECTION", 12),))

    result = grade(case, [_finding("SAST.SQL_INJECTION", 12, Severity.INFO)])

    assert result.matrix == ConfusionMatrix(true_positives=1)


def test_a_correctly_graded_finding_is_preferred_over_a_misgraded_one_at_the_same_distance():
    """Severity is part of what is being matched, not a filter applied after.

    With a right-severity finding available, claiming the wrong-severity one
    would report a false negative on a suite that behaved correctly.
    """
    case = _case(expected=(ExpectedFinding("SAST.SQL_INJECTION", 12, Severity.CRITICAL),))
    wrong = _finding("SAST.SQL_INJECTION", 11, Severity.HIGH)
    right = _finding("SAST.SQL_INJECTION", 13, Severity.CRITICAL)

    result = grade(_replace_tolerance(case, 2), [wrong, right])

    assert result.matrix == ConfusionMatrix(true_positives=1, false_positives=1)
    assert result.spurious == (wrong,)


def _replace_tolerance(case: EvaluationCase, tolerance: int) -> EvaluationCase:
    return EvaluationCase(
        name=case.name,
        file_path=case.file_path,
        expected=case.expected,
        forbidden=case.forbidden,
        scope=case.scope,
        line_tolerance=tolerance,
    )


# -- AC-5 and AC-6 -----------------------------------------------------------


def test_an_unexpected_in_scope_finding_is_a_false_positive():
    case = _case(scope=("SAST.*",))

    result = grade(case, [_finding("SAST.WEAK_CRYPTO", 4)])

    assert result.matrix == ConfusionMatrix(false_positives=1)
    assert result.ungraded == ()


def test_an_out_of_scope_finding_is_ungraded_and_named():
    case = _case(scope=("SAST.*",))

    result = grade(case, [_finding("QUALITY.GOD_CLASS", 4)])

    assert result.matrix == ConfusionMatrix()
    assert [finding.rule_id for finding in result.ungraded] == ["QUALITY.GOD_CLASS"]
    assert result.ungraded_rule_ids == ("QUALITY.GOD_CLASS",)


def test_the_default_scope_grades_everything():
    result = grade(_case(), [_finding("QUALITY.GOD_CLASS", 4)])

    assert result.matrix == ConfusionMatrix(false_positives=1)
    assert result.ungraded == ()


def test_an_exact_rule_id_in_scope_grades_only_that_rule():
    case = _case(scope=("SAST.SQL_INJECTION",))

    result = grade(case, [_finding("SAST.SQL_INJECTION", 4), _finding("SAST.WEAK_CRYPTO", 9)])

    assert result.matrix == ConfusionMatrix(false_positives=1)
    assert [finding.rule_id for finding in result.ungraded] == ["SAST.WEAK_CRYPTO"]


def test_an_expected_finding_is_graded_even_when_the_scope_excludes_its_rule():
    """Writing an expectation is the strongest possible statement of intent.

    A case that expects a rule and then leaves it out of scope is
    contradicting itself; honouring the expectation is the reading that
    cannot hide a defect.
    """
    case = _case(expected=(ExpectedFinding("QUALITY.GOD_CLASS", 3),), scope=("SAST.*",))

    result = grade(case, [_finding("QUALITY.GOD_CLASS", 3)])

    assert result.matrix == ConfusionMatrix(true_positives=1)


# -- AC-7 --------------------------------------------------------------------


def test_a_forbidden_finding_is_a_false_positive_even_when_out_of_scope():
    case = _case(scope=("SAST.*",), forbidden=(ForbiddenFinding("PERFORMANCE.N_PLUS_ONE"),))

    result = grade(case, [_finding("PERFORMANCE.N_PLUS_ONE", 21)])

    assert result.matrix == ConfusionMatrix(false_positives=1)
    assert result.ungraded == ()
    assert [finding.rule_id for finding in result.forbidden_seen] == ["PERFORMANCE.N_PLUS_ONE"]


def test_a_forbidden_finding_pinned_to_a_line_ignores_the_rule_elsewhere():
    case = _case(scope=("SAST.*",), forbidden=(ForbiddenFinding("PERFORMANCE.N_PLUS_ONE", 21),))

    result = grade(case, [_finding("PERFORMANCE.N_PLUS_ONE", 40)])

    assert result.matrix == ConfusionMatrix()
    assert [finding.rule_id for finding in result.ungraded] == ["PERFORMANCE.N_PLUS_ONE"]


def test_a_forbidden_rule_that_never_fires_costs_nothing():
    case = _case(forbidden=(ForbiddenFinding("PERFORMANCE.N_PLUS_ONE"),))

    result = grade(case, [])

    assert result.matrix == ConfusionMatrix()
    assert result.forbidden_seen == ()


# -- assignment is one-to-one ------------------------------------------------


def test_one_finding_cannot_satisfy_two_expectations():
    case = _case(
        expected=(
            ExpectedFinding("SAST.SQL_INJECTION", 12),
            ExpectedFinding("SAST.SQL_INJECTION", 12),
        )
    )

    result = grade(case, [_finding("SAST.SQL_INJECTION", 12)])

    assert result.matrix == ConfusionMatrix(true_positives=1, false_negatives=1)


def test_one_expectation_cannot_be_satisfied_twice():
    case = _case(expected=(ExpectedFinding("SAST.SQL_INJECTION", 12),))

    result = grade(case, [_finding("SAST.SQL_INJECTION", 12), _finding("SAST.SQL_INJECTION", 12)])

    assert result.matrix == ConfusionMatrix(true_positives=1, false_positives=1)


def test_a_case_expecting_nothing_on_a_quiet_fixture_is_a_perfect_score():
    result = grade(_case(), [])

    assert result.matrix == ConfusionMatrix()
    assert result.matrix.f1 == 1.0
