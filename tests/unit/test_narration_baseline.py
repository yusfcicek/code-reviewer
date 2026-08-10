"""Step 6 — the shipped corpus, graded by the real checks.

The test that turns the corpus from a directory of YAML into a gate. It runs
every check over every recorded review, so a rewritten check or an edited case
fails a build rather than quietly changing what the number means.
"""

from pathlib import Path

import pytest

from code_reviewer.application.narration_evaluation import NarrationEvaluator
from code_reviewer.domain.narration import CHECKS
from code_reviewer.evaluate import DEFAULT_NARRATION_FLOOR
from code_reviewer.infrastructure.evaluation.narration_dataset import NarrationCorpus


@pytest.fixture(scope="module")
def cases():
    return NarrationCorpus("evaluation").cases()


@pytest.fixture(scope="module")
def report(cases):
    return NarrationEvaluator().evaluate(cases, current_fingerprint="unknown")


def test_the_corpus_loads(cases):
    assert len(cases) >= 15


def test_the_corpus_holds_the_committed_floor(report):
    assert report.score >= DEFAULT_NARRATION_FLOOR, "\n".join(
        f"{failure.case}: {failure.check} — {failure.detail}" for failure in report.failures
    )


def test_every_check_is_exercised_by_a_case_that_fails_it(cases):
    """A corpus of clean reviews cannot show that a check is able to fire. One
    deliberately broken case per check is what makes this an instrument rather
    than a filing system."""
    declared = {check for case in cases for check in case.expected_failures}

    for check in CHECKS:
        assert check.__name__ in declared, f"no case demonstrates {check.__name__} failing"


def test_every_check_is_passed_by_most_of_the_corpus(cases):
    """The concern the raw ratio was a proxy for, measured directly.

    This used to assert that fewer than half the cases declared a failure, on
    the reasoning that a corpus of broken reviews measures the harness rather
    than the reviews. Level 25 made the concern measurable per check, and the
    ratio turned out to be the wrong proxy: a case declaring one failure still
    passes the other four, so a corpus that is sixty per cent deliberately
    broken can still exercise every check overwhelmingly in the passing
    direction. This asserts that instead.
    """
    from code_reviewer.application.narration_evaluation import NarrationEvaluator

    for entry in NarrationEvaluator().evaluate(cases).coverage:
        assert entry.passing > len(cases) / 2, entry


def test_every_check_is_demonstrated_firing_enough_times(cases):
    """AC-9. One example pins one author's idea of a check — which is how a
    check catching three phrasings of eight survived the corpus built to
    demonstrate it (self-review 21-22, S-01)."""
    from code_reviewer.application.narration_evaluation import (
        MINIMUM_DEMONSTRATIONS,
        NarrationEvaluator,
    )

    for entry in NarrationEvaluator().evaluate(cases).coverage:
        assert entry.firing >= MINIMUM_DEMONSTRATIONS, entry


def test_every_fixture_the_corpus_names_exists(cases):
    for case in cases:
        assert (Path("evaluation") / case.file_path).is_file(), case.file_path


def test_the_corpus_reuses_the_analyzer_datasets_fixtures(cases):
    """Two corpora, one set of subject files. A second copy of the same code
    would drift from the first and grade a file nobody analyses."""
    for case in cases:
        assert case.file_path.startswith("fixtures/")


def test_every_case_declares_the_findings_its_prose_is_graded_against(cases):
    """A case with no findings is legitimate — a clean file — but a case whose
    prose reports a vulnerability and lists no findings is a case grading
    nothing."""
    for case in cases:
        if "FAIL" in case.review:
            assert case.findings, f"{case.name} narrates a failure and lists no findings"
