"""Step 2 — the checks. Each one is answerable and recomputable by hand."""

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.narration import (
    REQUIRED_SECTIONS,
    NarrationCase,
    citations_are_grounded,
    required_sections_are_present,
    severe_findings_are_mentioned,
    severity_claims_are_backed,
    the_prose_claims_no_verdict,
)
from code_reviewer.domain.severity import Severity

WELL_FORMED = "\n".join(f"## {section}\n- something" for section in REQUIRED_SECTIONS)


def _finding(severity=Severity.CRITICAL, line=11, title="SQL Injection") -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path="src/app.py",
        line_number=line,
        title=title,
        description="A query built by concatenation",
        remediation="Parameterise it",
        rule_id="SAST.SQL_INJECTION",
    )


def _case(review: str, findings=(), line_count=40) -> NarrationCase:
    return NarrationCase(
        name="case",
        file_path="src/app.py",
        line_count=line_count,
        review=review,
        findings=tuple(findings),
    )


# -- citations ---------------------------------------------------------------


def test_a_citation_of_the_reviewed_file_passes():
    assert citations_are_grounded(_case("the query at `src/app.py:11`")).passed


def test_a_citation_of_a_file_that_is_not_under_review_fails():
    """The failure mode a language model actually has: a confident sentence
    about a file the review never saw."""
    result = citations_are_grounded(_case("see `src/auth.py:412` for the token"))

    assert not result.passed
    assert "src/auth.py:412" in result.detail


def test_a_line_past_the_end_of_the_file_fails():
    result = citations_are_grounded(_case("at `src/app.py:412`", line_count=40))

    assert not result.passed
    assert "412" in result.detail


def test_a_review_that_cites_nothing_passes():
    """An empty denominator is not a failure. Level 12's rule, here."""
    assert citations_are_grounded(_case("Nothing of note.")).passed


def test_every_bad_citation_is_named_not_only_the_first():
    result = citations_are_grounded(_case("`a/b.py:1` and `src/app.py:900`"))

    assert "a/b.py:1" in result.detail
    assert "src/app.py:900" in result.detail


# -- the verdict the prose may not claim -------------------------------------


def test_prose_that_claims_the_pipeline_is_blocked_fails():
    """ADR 0004: findings decide, prose warns. Level 20 made the record
    unable to say otherwise; this makes the text measurable."""
    result = the_prose_claims_no_verdict(_case("This will block the pipeline."))

    assert not result.passed
    assert "block the pipeline" in result.detail.lower()


def test_prose_that_approves_the_merge_fails():
    assert not the_prose_claims_no_verdict(_case("I approve this merge request.")).passed


def test_the_sast_scan_result_field_is_not_a_verdict_claim():
    """`**SAST Scan Result**: PASS - Low` is the format the prompt asks for.
    A check that failed the shape it demanded would be unusable."""
    assert the_prose_claims_no_verdict(_case("- **SAST Scan Result**: PASS - Low")).passed


def test_describing_what_a_finding_would_do_is_not_a_verdict():
    """ "a critical finding fails the pipeline" is a true statement about the
    policy, not this review claiming to have decided."""
    assert the_prose_claims_no_verdict(
        _case("A critical finding fails the pipeline under the current policy.")
    ).passed


# -- severity discipline -----------------------------------------------------


def test_calling_something_critical_with_no_critical_finding_fails():
    result = severity_claims_are_backed(_case("This is a CRITICAL problem.", [_finding(Severity.LOW)]))

    assert not result.passed
    assert "critical" in result.detail.lower()


def test_calling_something_critical_with_a_critical_finding_passes():
    assert severity_claims_are_backed(_case("A CRITICAL injection.", [_finding()])).passed


def test_a_low_claim_needs_nothing_to_back_it():
    """Deliberately asymmetric. Claiming severity upward invents evidence;
    claiming it downward is an opinion the gate ignores anyway."""
    assert severity_claims_are_backed(_case("- **Risk Assessment**: Low", [])).passed


def test_a_critical_finding_the_prose_never_mentions_fails_its_own_check():
    """A different defect from inventing one, and counted separately."""
    result = severe_findings_are_mentioned(_case("Looks fine to me.", [_finding()]))

    assert not result.passed
    assert "SQL Injection" in result.detail


def test_mentioning_the_finding_by_title_is_enough():
    assert severe_findings_are_mentioned(_case("There is a SQL Injection here.", [_finding()])).passed


def test_citing_the_finding_s_line_is_enough():
    assert severe_findings_are_mentioned(_case("Look at `src/app.py:11`.", [_finding()])).passed


def test_a_file_with_no_severe_findings_passes():
    assert severe_findings_are_mentioned(_case("Fine.", [_finding(Severity.MEDIUM)])).passed


# -- structure ---------------------------------------------------------------


def test_a_review_with_every_section_passes():
    assert required_sections_are_present(_case(WELL_FORMED)).passed


def test_a_missing_section_fails_and_is_named():
    without_security = WELL_FORMED.replace("## Security Analysis", "## Something Else")

    result = required_sections_are_present(_case(without_security))

    assert not result.passed
    assert "Security Analysis" in result.detail


def test_the_heading_is_matched_whatever_decoration_it_carries():
    """The prompt's own format writes `## 🔒 Security Analysis`."""
    decorated = "\n".join(f"## 🔒 {section}" for section in REQUIRED_SECTIONS)

    assert required_sections_are_present(_case(decorated)).passed


# -- every check ------------------------------------------------------------


def test_every_check_names_itself():
    for check in (
        citations_are_grounded,
        the_prose_claims_no_verdict,
        severity_claims_are_backed,
        severe_findings_are_mentioned,
        required_sections_are_present,
    ):
        assert check(_case(WELL_FORMED)).check


# -- S-01: the phrasings a model actually writes -----------------------------
#
# The patterns were written against the phrasings that came to mind while
# writing them, and the corpus case built to demonstrate the check uses one of
# the three that happened to work. So the corpus proved the check can fire and
# nothing about what it covers.

CLAIMS_A_VERDICT = (
    "This blocks the pipeline.",
    "This merge request is blocked.",
    "LGTM, approved.",
    "The pipeline will be blocked by this.",
    "Recommendation: do not merge.",
    "Approving this change.",
    "This will block the pipeline.",
    "I reject this merge request.",
    "Do not merge until the key is rotated.",
    "This change is approved.",
    "Blocking the merge.",
    "Ship it.",
)

STATES_A_FACT = (
    "- **SAST Scan Result**: PASS - Low",
    "A critical finding fails the pipeline under the current policy.",
    "A critical finding blocks the pipeline under the current policy.",
    "The gate blocks on critical findings; this one is medium.",
    "The blocking severity is configured as critical.",
    "This function is not approved for reuse elsewhere in the codebase.",
    "The merge conflict marker on line 4 was left in.",
)


def test_every_phrasing_that_claims_a_verdict_is_caught():
    for phrasing in CLAIMS_A_VERDICT:
        result = the_prose_claims_no_verdict(_case(phrasing))

        assert not result.passed, f"not caught: {phrasing}"
        assert result.detail, phrasing


def test_no_statement_of_fact_is_mistaken_for_a_verdict():
    """The other half. A check that fires on "the gate blocks on critical
    findings" would make the true sentence unwritable, and a reviewer who
    cannot describe the policy writes worse reviews."""
    for phrasing in STATES_A_FACT:
        assert the_prose_claims_no_verdict(_case(phrasing)).passed, f"wrongly caught: {phrasing}"


# -- S-04: a severity word is not always a severity claim --------------------


def test_ordinary_prose_about_complexity_is_not_a_severity_claim():
    """Real reviews say "high complexity" and "high coupling". A check that
    fails those fails reviews that said nothing wrong."""
    for phrasing in (
        "The function has high complexity and should be split.",
        "This introduces high coupling between the two modules.",
        "A high number of branches makes this hard to test.",
        "The critical path through this function is the loop.",
        "This is a critical section guarded by the lock.",
    ):
        assert severity_claims_are_backed(_case(phrasing)).passed, f"wrongly caught: {phrasing}"


def test_a_severity_claim_in_the_shape_a_review_writes_it_is_caught():
    for phrasing in (
        "- **Risk Assessment**: Critical - the credential is live",
        "- **SAST Scan Result**: FAIL - Critical",
        "Severity: HIGH",
        "This is a CRITICAL vulnerability.",
        "**Vulnerabilities Found**: SQL Injection (critical)",
    ):
        result = severity_claims_are_backed(_case(phrasing))

        assert not result.passed, f"not caught: {phrasing}"
