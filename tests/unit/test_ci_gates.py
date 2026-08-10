"""Self-review 28, S-01 and S-04 — what CI actually runs, pinned to the code.

Level 25 changed what a floor means: from that level on, a floor is compared
against the lower bound of a 95 % interval rather than against the ratio. Every
constant in the repository moved. The workflow did not, so CI went on asking for
0.95 and 1.00 on numbers that are now bounds, and the gate has been failing ever
since — through four levels whose reports each said *eval floors: exit 0*,
because each of those runs was a local command with different arguments than the
one CI runs.

Level 28 then earned two more floors, for corpora CI has never run at all.

Both are the same defect: a claim about a gate, checked by reading something
that is not the gate. So the workflow is now read by a test.
"""

import re
from pathlib import Path

import pytest
import yaml

from code_reviewer.evaluate import (
    DEFAULT_ANALYZER_FLOOR,
    DEFAULT_DOCUMENTATION_FLOOR,
    DEFAULT_FIRST_PLACE_FLOOR,
    DEFAULT_NARRATION_FLOOR,
    DEFAULT_RETRIEVAL_FLOOR,
)

WORKFLOW = Path(".github/workflows/ci.yml")

#: The entry point the workflow invokes. One name, so a step that grades
#: anything is found by looking for it.
COMMAND = "ai-code-review-eval"


def _steps() -> list[str]:
    """Every `run:` in the workflow that invokes the evaluation command."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    runs = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if isinstance(step.get("run"), str)
    ]
    return [" ".join(run.split()) for run in runs if COMMAND in run]


def _floors(step: str) -> dict[str, float]:
    return {name: float(value) for name, value in re.findall(r"--min-([a-z-]+)\s+([0-9.]+)", step)}


@pytest.fixture(scope="module")
def steps():
    return _steps()


def test_the_workflow_grades_something(steps):
    assert steps, f"no step in {WORKFLOW} runs {COMMAND}"


def test_every_harness_the_command_offers_is_run(steps):
    """Level 28 earned two floors. A floor nothing runs gates nothing."""
    modes = {
        flag for step in steps for flag in ("--narration", "--documentation", "--retrieval") if flag in step
    }

    assert modes == {"--narration", "--documentation", "--retrieval"}
    assert any(
        not any(flag in step for flag in ("--narration", "--documentation", "--retrieval")) for step in steps
    ), "no step grades the analyzers"


def test_no_step_asks_for_a_floor_the_shipped_corpora_do_not_hold(steps):
    """The defect itself. A workflow asking for 0.95 on a bound of 0.84 is a
    red build that says nothing, and the whole point of a floor is that its
    failure means something."""
    shipped = {
        "precision": DEFAULT_ANALYZER_FLOOR,
        "recall": DEFAULT_ANALYZER_FLOOR,
        "f1": DEFAULT_ANALYZER_FLOOR,
        "narration": DEFAULT_NARRATION_FLOOR,
        "retrieval": DEFAULT_RETRIEVAL_FLOOR,
    }

    for step in steps:
        for name, value in _floors(step).items():
            assert name in shipped, f"{name} is not a floor this command has"
            assert value == pytest.approx(shipped[name]), (
                f"CI asks for {name} >= {value}; the shipped floor is {shipped[name]}"
            )


def test_the_documentation_corpus_is_graded_against_its_own_floor(steps):
    """The two corpora share the precision/recall/f1 flags and happen to hold
    the same number today. If they diverge, the step that does not name its
    floor is the one that will quietly grade against the other's."""
    documentation = [step for step in steps if "--documentation" in step]

    assert documentation
    for step in documentation:
        for value in _floors(step).values():
            assert value == pytest.approx(DEFAULT_DOCUMENTATION_FLOOR)


def test_the_first_place_floor_has_no_flag_and_so_cannot_drift(steps):
    """It is not overridable, which is why it needs no line in the workflow.
    Stated as a test so that adding the flag adds the pin."""
    assert DEFAULT_FIRST_PLACE_FLOOR > 0
    assert not any("--min-first-place" in step for step in steps)
