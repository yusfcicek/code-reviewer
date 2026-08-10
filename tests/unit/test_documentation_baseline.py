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

#: The floors committed to CI, applied to the **lower bound** of a 95 %
#: interval since Level 25 rather than to the point estimate.
#:
#: The rules still score 1.00. They do so over **six graded findings** — seven
#: of the thirteen cases expect nothing, which is deliberate and is where this
#: tier's failure mode lives — and six of six is consistent with a real rate of
#: 0.61. The floor says what that supports and not a decimal more.
MIN_PRECISION = 0.60
MIN_RECALL = 0.60
MIN_F1 = 0.60

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


def test_the_corpus_is_found_from_the_dataset_root_as_well():
    """`--dataset evaluation` is what the other two harnesses are given. One
    flag meaning two things across three harnesses is a trap, not a feature."""
    assert len(DocumentationCorpus("evaluation").cases()) == len(
        DocumentationCorpus("evaluation/documentation").cases()
    )


def test_a_missing_corpus_is_refused_rather_than_scored_as_empty():
    from code_reviewer.infrastructure.evaluation.documentation_dataset import DocumentationDatasetError

    with pytest.raises(DocumentationDatasetError):
        DocumentationCorpus("evaluation/nothing-here").cases()


def test_this_repository_has_no_docstring_drift():
    """The rule's own repository is its hardest corpus, and the only one that
    was not authored to make it look good.

    Written after self-review S-04: the rule produced three findings here, one
    of them false (an abstract method documenting the contract its empty body
    cannot fulfil) and two of them real parameters nobody had documented. This
    test is what keeps the count at zero.
    """
    from pathlib import Path

    from code_reviewer.domain.documentation import docstring_defects

    found = [
        f"{path}:{defect.line} {defect.subject} — {defect.detail}"
        for path in sorted(Path("code_reviewer").rglob("*.py"))
        for defect in docstring_defects(path.read_text(encoding="utf-8"))
    ]

    assert found == [], found


def test_the_corpus_does_not_support_a_blocking_floor(report):
    """Level 27, step 7 — the blocking question, answered by the number.

    Level 23 left `DOCS` blocking nothing because the rules were unmeasured, and
    this project's rule since Level 12 is that a floor is earned by the level
    that measured it. Level 27 measured, and the answer is still no:

        6 graded findings, all correct -> lower bound 0.61
       20                              -> 0.84
       60                              -> 0.94
      100                              -> 0.96

    A blocking gate wants at least the 0.95 the analyzers are held to on their
    point estimate, and on a lower bound that needs about a hundred graded
    findings. The corpus has six. So the severity stays where it is, and this
    test is the record of why rather than a preference nobody wrote down.
    """
    from code_reviewer.domain.confidence import wilson

    assert report.overall.precision_interval.lower < 0.95
    assert wilson(100, 100).lower >= 0.95, "the target this corpus would have to reach"


def test_no_documentation_finding_is_above_the_warning_threshold():
    """The consequence, asserted rather than trusted: whatever the rules find,
    none of it can block until a level earns the floor."""
    from code_reviewer.application.documentation_service import DocumentationService
    from code_reviewer.application.ports import FileChange
    from code_reviewer.domain.documentation import SymbolIndex
    from code_reviewer.domain.severity import Severity

    index = SymbolIndex(names=frozenset({"kept"}), signatures={"kept": ()})
    documents = [("README.md", "# Guide\n\nBoot with `start_app`.\n")]
    change = FileChange(path="app.py", diff="@@ -1,2 +1,1 @@\n-def start_app(config):\n")

    outcome = DocumentationService(index=index, documents=documents).review([change], {})

    assert outcome.findings
    assert all(finding.severity is Severity.LOW for finding in outcome.findings)
