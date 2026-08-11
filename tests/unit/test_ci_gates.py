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

#: Both pipelines. The first version of this test read the GitHub workflow only
#: and would have left the GitLab one drifting alone — a pin over half the thing
#: it pins, which is the shape of the defect it was written for.
PIPELINES = (Path(".github/workflows/ci.yml"), Path(".gitlab-ci.yml"))

#: The entry point the workflow invokes. One name, so a step that grades
#: anything is found by looking for it.
COMMAND = "ai-code-review-eval"


def _commands(pipeline: Path) -> list[str]:
    """Every shell line in one pipeline that invokes the evaluation command.

    Both files are read as YAML and then as text: a GitHub workflow puts its
    commands under `jobs.*.steps[].run` and a GitLab pipeline under
    `<job>.script[]`, and neither structure is worth teaching this test twice
    when what it needs is the command lines.

    Both invocation styles fold their arguments onto following lines, so a
    command is gathered until a line that is neither a flag nor a continuation.
    Stripping the YAML list marker with `lstrip("-")` ate the flags' own dashes
    and produced commands with no floors in them at all — a pin that passed by
    finding nothing, in the test written to stop exactly that.
    """
    text = pipeline.read_text(encoding="utf-8")
    yaml.safe_load(text)  # a pipeline that will not parse is a failure here too
    commands: list[str] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if not line or line.startswith("#"):
            continue
        if COMMAND in line:
            current = [line]
            commands.append(line)
        elif current and line.startswith("--"):
            current.append(line)
            commands[-1] = " ".join(current)
        else:
            current = []
    return commands


def _steps() -> list[str]:
    """Every evaluation command run by any pipeline in this repository."""
    return [command for pipeline in PIPELINES for command in _commands(pipeline)]


def _floors(step: str) -> dict[str, float]:
    return {name: float(value) for name, value in re.findall(r"--min-([a-z-]+)\s+([0-9.]+)", step)}


@pytest.fixture(scope="module")
def steps():
    return _steps()


def test_the_workflow_grades_something(steps):
    for pipeline in PIPELINES:
        assert _commands(pipeline), f"no step in {pipeline} runs {COMMAND}"


MODES = ("--narration", "--documentation", "--retrieval", "--alignment")


def test_every_harness_the_command_offers_is_run(steps):
    """Level 28 earned two floors. A floor nothing runs gates nothing."""
    for pipeline in PIPELINES:
        commands = _commands(pipeline)
        graded = {flag for command in commands for flag in MODES if flag in command}

        assert graded == set(MODES), f"{pipeline} does not run {set(MODES) - graded}"
        assert any(not any(flag in command for flag in MODES) for command in commands), (
            f"{pipeline} does not grade the analyzers"
        )


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

    found = 0
    for step in steps:
        for name, value in _floors(step).items():
            found += 1
            assert name in shipped, f"{name} is not a floor this command has"
            assert value == pytest.approx(shipped[name]), (
                f"CI asks for {name} >= {value}; the shipped floor is {shipped[name]}"
            )

    # Without this the test passes by finding no floors, which is how the first
    # version of it passed: the line parser ate the flags' dashes and every
    # command came back bare. A pin that cannot fail is the defect, not the fix.
    assert found >= 2 * len(shipped), f"only {found} floor(s) found in {len(steps)} command(s)"


def test_the_documentation_corpus_is_graded_against_its_own_floor(steps):
    """The two corpora share the precision/recall/f1 flags and happen to hold
    the same number today. If they diverge, the step that does not name its
    floor is the one that will quietly grade against the other's."""
    documentation = [step for step in steps if "--documentation" in step]

    assert documentation
    for step in documentation:
        for value in _floors(step).values():
            assert value == pytest.approx(DEFAULT_DOCUMENTATION_FLOOR)


def test_the_alignment_step_carries_no_floor(steps):
    """Level 29, contract C-5. Every other harness is a sample and takes a
    floor on an interval's lower bound; this one compares two texts, so a floor
    would be borrowed authority. A number appearing here would mean somebody
    had started scoring it."""
    for step in steps:
        if "--alignment" in step:
            assert _floors(step) == {}


def test_the_first_place_floor_has_no_flag_and_so_cannot_drift(steps):
    """It is not overridable, which is why it needs no line in the workflow.
    Stated as a test so that adding the flag adds the pin."""
    assert DEFAULT_FIRST_PLACE_FLOOR > 0
    assert not any("--min-first-place" in step for step in steps)
