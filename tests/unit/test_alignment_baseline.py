"""Step 5 — the shipped prompt against the shipped checks.

The gate. Every other baseline test in this repository pins a number; this one
pins a relationship, because the thing it measures has an exact answer: either
the prompt says what a check enforces or it does not.

What it found on its first run, and what the level exists to close:

    citations_are_grounded          nothing in the prompt about citing anything
    the_prose_claims_no_verdict     nothing about a verdict
    severity_claims_are_backed      severity words demanded, backing never asked for

Three of five checks graded twenty-four recorded reviews to 1.00 for eight
levels while the prompt asked for none of it.
"""

import re

import pytest

from code_reviewer.application.alignment_report import NEEDS_AN_ENDPOINT, render_alignment_report
from code_reviewer.domain.alignment import alignment
from code_reviewer.domain.narration import (
    CHECKS,
    EXPECTATIONS,
    REQUIRED_SECTIONS,
    UNCHECKED_SECTIONS,
)
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent


@pytest.fixture(scope="module")
def report():
    return alignment(
        ReviewAgent.SYSTEM_TEMPLATE,
        EXPECTATIONS,
        checked=tuple(REQUIRED_SECTIONS),
        declined=dict(UNCHECKED_SECTIONS),
    )


def test_no_check_grades_a_rule_the_prompt_never_states(report):
    """AC-9, and the reason the level exists."""
    assert [gap.check for gap in report.unbacked] == []


def test_no_heading_the_prompt_demands_is_graded_by_nothing(report):
    """The other direction. A model that dropped the whole Refactoring Roadmap
    passed every check this repository had, for eight levels."""
    assert report.ungoverned == ()


def test_the_shipped_prompt_is_aligned(report):
    assert report.is_aligned


def test_every_check_is_accounted_for(report):
    assert len(report.aligned) + len(report.unbacked) == len(CHECKS)


def test_the_measurement_can_fail(report):
    """Self-review 27's rule, applied before it has to be applied again.

    A prompt with the instructions removed must come back unaligned. Without
    this, a bug that made every expectation vacuously true would look exactly
    like a well-written prompt.
    """
    stripped = ReviewAgent.SYSTEM_TEMPLATE
    for expectation in EXPECTATIONS:
        for phrase in expectation.phrases:
            # Case-insensitively, because the match is: the prompt writes
            # "Name every CRITICAL finding" at the start of a bullet and the
            # expectation is written in lower case.
            stripped = re.sub(re.escape(phrase), "", stripped, flags=re.I)

    broken = alignment(
        stripped, EXPECTATIONS, checked=tuple(REQUIRED_SECTIONS), declined=dict(UNCHECKED_SECTIONS)
    )

    assert len(broken.unbacked) == len(EXPECTATIONS)
    assert not broken.is_aligned


def test_the_report_says_what_needs_an_endpoint(report):
    """AC-5. The number is not a verdict on the prose, and the report says so
    in the same words whether or not anything is wrong."""
    assert NEEDS_AN_ENDPOINT in render_alignment_report(report)


def test_the_declined_headings_are_still_demanded_by_the_prompt(report):
    """A reason for a section the prompt stopped asking for is a note that
    outlived its subject. `alignment` refuses one, and this is where that
    refusal would be seen."""
    assert set(UNCHECKED_SECTIONS) <= set(report.demanded)
