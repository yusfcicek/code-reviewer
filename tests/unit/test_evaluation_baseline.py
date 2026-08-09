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

#: The floors committed to CI, per decision D-4: the measured baseline with a
#: margin. Level 12 opened at precision 1.00, recall 0.89, F1 0.94 and floored
#: at 0.95 / 0.85 / 0.90 — the recall gap being the one defect the dataset
#: recorded and the suite could not find. Level 13 closed it (E-01) and
#: narrowed the rule that was firing on ordinary code (E-02), so the baseline
#: is 1.00 across the board over ten cases and the floors rise with it.
#:
#: Raising a floor is what a level earns. Lowering one to make a build green is
#: the thing the harness exists to prevent.
MIN_PRECISION = 0.95
MIN_RECALL = 0.95
MIN_F1 = 0.95

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
    assert len(dataset.cases()) >= 11


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
        f"f1 >= {MIN_F1:.2f} over {len(dataset.cases())} cases"
    )

    assert expected == EVALUATION_BASELINE


def test_the_ungraded_count_is_small_enough_to_read(report):
    """Ungraded findings are allowed and counted. They are not allowed to be
    the bulk of the output — at that point the dataset is grading a corner of
    what the suite does and calling it a score."""
    graded = report.overall.true_positives + report.overall.false_positives
    assert report.ungraded_count <= graded
