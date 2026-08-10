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
            # Case-insensitively and across line breaks, for the two reasons
            # the search itself is: the prompt capitalises the first word of a
            # bullet, and it wraps its paragraphs (self-review 29, S-04).
            pattern = r"\s+".join(re.escape(word) for word in phrase.split())
            stripped = re.sub(pattern, "", stripped, flags=re.I)

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


def test_the_output_format_alone_backs_only_the_check_about_the_output_format():
    """Self-review 29, S-02.

    `severe_findings_are_mentioned` declared itself satisfied by the string
    `Vulnerabilities Found` — a field label in the output format, which states
    none of the rule about naming every critical finding. So the check was
    reported as backed for eight levels' worth of prompt that never asked for
    it, and Level 29's own first run listed it under "checks the prompt backs".

    Stated as a property rather than as a fix to one expectation: an
    instruction is a sentence telling the model what to do, and the output
    format is a shape. The only check the shape may back is the one about the
    shape.
    """
    format_only = ReviewAgent.SYSTEM_TEMPLATE[ReviewAgent.SYSTEM_TEMPLATE.index("OUTPUT FORMAT") :]

    backed = [expectation.check for expectation in EXPECTATIONS if expectation.met_by(format_only)]

    assert backed == ["required_sections_are_present"]


def test_the_specialists_inherit_the_instructions_they_are_graded_on():
    """Self-review 29, S-05.

    Level 29's spec put the specialists out of scope on the grounds that "a
    specialist writes a section, not a review". That is not why they are safe.
    They are safe because `system_prompt_for` composes the generalist template
    and adds a subject brief on top, so every instruction measured here reaches
    them verbatim.

    A real reason nothing pinned. If that composition ever changed — a
    specialism built from its own template — the alignment claim would silently
    narrow to one of five prompts, and this measurement would go on printing
    **Aligned**.
    """
    from code_reviewer.domain.orchestration import Specialism
    from code_reviewer.infrastructure.llm.specialist_agent import system_prompt_for

    for specialism in Specialism:
        prompt = system_prompt_for(specialism)

        assert ReviewAgent.SYSTEM_TEMPLATE in prompt, specialism
        for expectation in EXPECTATIONS:
            assert expectation.met_by(prompt), (specialism, expectation.check)
