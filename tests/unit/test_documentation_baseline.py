"""Step 9 — the documentation corpus, and the floor it holds.

The same bargain `test_evaluation_baseline.py` makes for the analyzers: the
dataset stops being documentation and becomes a gate, so a rule that changes
what it reports fails a build rather than a reader.

Half of these cases expect nothing. That is where this tier's real failure mode
lives — the first implementation reported twenty-five findings in one README,
of which almost all were a library call, a Kubernetes noun or another tool's
flag. A case that forbids a rule is how a fixed false positive stays fixed.
"""

import pytest

from code_reviewer.application.documentation_evaluation import evaluate_documentation
from code_reviewer.domain.evaluation import EvaluationThreshold
from code_reviewer.infrastructure.evaluation.documentation_dataset import DocumentationCorpus

#: The floors committed to CI. Level 23 opens at 1.00 across the board over
#: thirteen cases and floors at 0.95, matching the analyzers' margin.
#:
#: Raising a floor is what a level earns. Lowering one to make a build green is
#: the thing the harness exists to prevent.
MIN_PRECISION = 0.95
MIN_RECALL = 0.95
MIN_F1 = 0.95

#: Rules the corpus must exercise. A harness grading only dead references would
#: report a healthy F1 while four rules went unmeasured.
REQUIRED_RULES = (
    "DOCS.DEAD_REFERENCE",
    "DOCS.SIGNATURE_MISMATCH",
    "DOCS.UNKNOWN_OPTION",
    "DOCS.BROKEN_EXAMPLE",
    "DOCS.DOCSTRING_DRIFT",
)


@pytest.fixture(scope="module")
def fixtures():
    return DocumentationCorpus("evaluation/documentation").cases()


@pytest.fixture(scope="module")
def report(fixtures):
    return evaluate_documentation(fixtures)


def test_the_corpus_loads(fixtures):
    assert len(fixtures) >= 13


def test_every_rule_is_exercised(fixtures):
    expected = {expectation.rule_id for fixture in fixtures for expectation in fixture.case.expected}

    for rule in REQUIRED_RULES:
        assert rule in expected, f"no case expects {rule}"


def test_at_least_half_the_cases_expect_nothing(fixtures):
    """The precision half. A corpus of positives measures enthusiasm."""
    quiet = [fixture for fixture in fixtures if not fixture.case.expected]

    assert len(quiet) * 2 >= len(fixtures)


def test_several_cases_forbid_a_rule(fixtures):
    """A fixed false positive is only fixed while something pins it."""
    forbidding = [fixture for fixture in fixtures if fixture.case.forbidden]

    assert len(forbidding) >= 5


def test_no_case_failed_to_run(report):
    assert report.errors == ()


def test_the_rules_hold_the_committed_floors(report):
    threshold = EvaluationThreshold(min_precision=MIN_PRECISION, min_recall=MIN_RECALL, min_f1=MIN_F1)

    assert threshold.shortfalls(report) == []


def test_nothing_is_reported_that_no_case_grades(report):
    """An ungraded finding here is a rule firing on a case nobody wrote for
    it, which on a corpus this small is a defect rather than a gap."""
    assert report.ungraded_count == 0


def test_the_retrieved_tier_is_not_graded_here(fixtures):
    """`DRIFT` cannot be measured by a corpus: its answer comes from a model,
    and pinning a model's answers measures the recording. Stated as a test so
    that adding a `DRIFT` case is a conversation rather than an accident."""
    graded = {expectation.rule_id for fixture in fixtures for expectation in fixture.case.expected}

    assert not any(rule.startswith("DRIFT.") for rule in graded)
