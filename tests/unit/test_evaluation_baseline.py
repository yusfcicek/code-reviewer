"""Steps 7 and 9 — the shipped dataset, and the floor it holds.

This is the test that turns the dataset from documentation into a gate. It runs
the real :class:`StaticAnalysisSuite` over the real cases, so it fails when an
analyzer changes what it reports — which is the entire point of building the
harness.
"""

import pytest

from code_reviewer.application.evaluation_service import EvaluationService
from code_reviewer.domain.evaluation import EVERYTHING, EvaluationThreshold
from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite
from code_reviewer.infrastructure.evaluation.dataset import FileSystemDataset

#: The floors committed to CI. **These are applied to the lower bound of a 95 %
#: interval, not to the point estimate** (Level 25, decision D-2), and that
#: change is why the numbers here went down while the measurement did not.
#:
#: 0.80 since Level 28, which is the first time a floor in this repository has
#: gone **up** by somebody writing cases rather than by somebody choosing a
#: number. Ten graded findings supported 0.72; twenty support 0.84, and the
#: floor takes 0.80 of it.
#:
#: The six cases that got it there each cover a rule that had none — including
#: three that Level 26 had written a recipe or a written refusal for without
#: anything measuring the rule underneath. Two of them found real false
#: positives on their first run, and both were fixed rather than annotated
#: away (Level 28, decision D-3).
#:
#: 0.90 needs thirty-five graded findings and 0.95 needs seventy-three. Those
#: are a later level's work, and the numbers are here so nobody has to
#: re-derive them.
MIN_PRECISION = 0.80
MIN_RECALL = 0.80
MIN_F1 = 0.80

#: Namespaces the dataset must exercise. A harness that grades only the SAST
#: rules would report a healthy F1 while three analyzers went unmeasured.
REQUIRED_NAMESPACES = ("SAST", "QUALITY", "PERFORMANCE", "SEMANTIC")


@pytest.fixture(scope="module")
def dataset():
    return FileSystemDataset("evaluation")


@pytest.fixture(scope="module")
def report(dataset):
    return EvaluationService(StaticAnalysisSuite()).evaluate(dataset)


def test_the_shipped_dataset_loads(dataset):
    assert len(dataset.cases()) >= 17


def test_every_fixture_on_disk_is_referenced_by_a_case(dataset):
    """An unreferenced fixture is a case someone deleted half of."""
    from pathlib import Path

    referenced = {fixture.case.file_path for fixture in dataset.cases()}
    # A `.diff` belongs to the source of the same stem. The case names it in
    # its own key, which `CaseFixture` deliberately does not carry — it holds
    # the *content*, so the workflow never learns where a fixture lives.
    referenced |= {path.replace(".py", ".diff") for path in referenced}
    on_disk = {f"fixtures/{path.name}" for path in Path("evaluation/fixtures").iterdir() if path.is_file()}

    assert on_disk - referenced == set()


def test_every_analyzer_namespace_is_exercised(dataset):
    graded = {selector.split(".")[0] for fixture in dataset.cases() for selector in fixture.case.scope}

    for namespace in REQUIRED_NAMESPACES:
        assert namespace in graded, f"no case grades {namespace}"


def test_at_least_one_case_expects_nothing_and_grades_everything(dataset):
    """The case that catches an analyzer becoming enthusiastic.

    Without it, every case is scoped to the rule it is about, and a rule that
    fires on ordinary code is never charged for it.
    """
    assert any(not fixture.case.expected and EVERYTHING in fixture.case.scope for fixture in dataset.cases())


def test_at_least_one_case_forbids_a_rule(dataset):
    """A fixed false positive is only fixed while something pins it."""
    assert any(fixture.case.forbidden for fixture in dataset.cases())


def test_no_case_could_be_graded_only_because_the_analyzer_crashed(report):
    assert report.errors == ()


def test_the_suite_holds_the_committed_floors(report):
    threshold = EvaluationThreshold(min_precision=MIN_PRECISION, min_recall=MIN_RECALL, min_f1=MIN_F1)

    assert threshold.shortfalls(report) == []


def test_the_recorded_baseline_says_what_the_floors_actually_are(dataset):
    """Level 20 records the baseline in every decision record, and two numbers
    in two files drift. This is the pair somebody would forget."""
    from code_reviewer.infrastructure.governance.identity import EVALUATION_BASELINE

    expected = (
        f"precision >= {MIN_PRECISION:.2f}, recall >= {MIN_RECALL:.2f}, "
        f"f1 >= {MIN_F1:.2f} (lower bound) over {len(dataset.cases())} cases"
    )

    assert expected == EVALUATION_BASELINE


def test_the_ungraded_count_is_small_enough_to_read(report):
    """Ungraded findings are allowed and counted. They are not allowed to be
    the bulk of the output — at that point the dataset is grading a corner of
    what the suite does and calling it a score."""
    graded = report.overall.true_positives + report.overall.false_positives
    assert report.ungraded_count <= graded


def test_the_corpus_reaches_the_count_the_floor_needs(report):
    """Level 28, AC-1. Sixteen graded observations support 0.80, and the floor
    is a claim about the corpus rather than about the analyzers' ambition."""
    graded = report.overall.true_positives + report.overall.false_positives

    assert graded >= 16, f"{graded} graded findings will not carry a floor of {MIN_PRECISION}"


def test_no_two_cases_grade_the_same_rule_on_the_same_line(dataset):
    """AC-5. A duplicate is a number, and three self-reviews have found that a
    bigger number is the easiest thing to fake."""
    seen = set()
    for fixture in dataset.cases():
        for expectation in fixture.case.expected:
            key = (fixture.case.file_path, expectation.rule_id, expectation.line_number)

            assert key not in seen, key
            seen.add(key)
