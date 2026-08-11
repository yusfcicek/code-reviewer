"""Step 3 — the alignment report, and the two things it refuses to say."""

import re

from code_reviewer.application.alignment_report import NEEDS_AN_ENDPOINT, render_alignment_report
from code_reviewer.domain.alignment import AlignmentReport, UnbackedCheck

GAPPED = AlignmentReport(
    unbacked=(UnbackedCheck(check="the_prose_claims_no_verdict", missing=("never state a verdict",)),),
    ungoverned=("Refactoring Roadmap",),
    ungrounded=("Threat Model",),
    declined=("Architectural Review Summary",),
    aligned=("citations_are_grounded",),
    demanded=("Refactoring Roadmap", "Architectural Review Summary"),
)

CLEAN = AlignmentReport(aligned=("citations_are_grounded",), demanded=("Security Analysis",))


def test_the_unbacked_check_is_named_with_what_was_looked_for():
    text = render_alignment_report(GAPPED)

    assert "the_prose_claims_no_verdict" in text
    assert "never state a verdict" in text


def test_the_ungoverned_heading_is_named():
    assert "Refactoring Roadmap" in render_alignment_report(GAPPED)


def test_a_declined_heading_is_listed_separately_from_a_gap():
    text = render_alignment_report(GAPPED)
    ungraded = text.index("Headings nothing grades")
    declined = text.index("Headings deliberately ungraded")

    assert ungraded < declined
    assert "1 ungoverned heading(s)" in text


def test_an_ungrounded_heading_is_named(report_text=None):
    """Self-review 29, S-01. The direction the level forgot to look in."""
    text = render_alignment_report(GAPPED)

    assert "Threat Model" in text
    assert "1 ungrounded name(s)" in text


def test_a_clean_report_says_so():
    text = render_alignment_report(CLEAN)

    assert "**Aligned**" in text
    assert "NOT ALIGNED" not in text


def test_a_gapped_report_says_so():
    assert "NOT ALIGNED" in render_alignment_report(GAPPED)


def test_what_needs_an_endpoint_is_printed_every_time():
    """The sentence that keeps this from being read as a verdict on the prose.
    Both reports print it, including the one with nothing wrong."""
    for report in (GAPPED, CLEAN):
        assert NEEDS_AN_ENDPOINT in render_alignment_report(report)


def test_the_report_prints_no_ratio():
    """Level 29, decision D-2. This is not a sample, so a rate over it would be
    a number pretending to be a measurement — and every reader in this
    repository has been taught that a decimal is an interval's point estimate.
    """
    text = render_alignment_report(GAPPED)

    assert not re.search(r"\b0\.\d\d\b", text)
    assert "%" not in text
