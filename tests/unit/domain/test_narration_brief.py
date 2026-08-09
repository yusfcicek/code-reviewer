"""Step 1 — what a review was written about, and what it cited."""

import pytest

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.narration import Citation, NarrationCase
from code_reviewer.domain.severity import Severity


def _finding(severity=Severity.CRITICAL, line=11, rule="SAST.SQL_INJECTION") -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path="src/app.py",
        line_number=line,
        title="SQL Injection",
        description="A query built by concatenation",
        remediation="Parameterise it",
        rule_id=rule,
    )


def _case(**overrides) -> NarrationCase:
    defaults = {
        "name": "sql-injection",
        "file_path": "src/app.py",
        "line_count": 40,
        "review": "# Review\nSomething about `src/app.py:11`.",
        "findings": (_finding(),),
        "prompt_fingerprint": "b6b17025f0c5",
    }
    return NarrationCase(**{**defaults, **overrides})


# -- the case ----------------------------------------------------------------


def test_a_case_carries_the_facts_a_check_can_be_answered_against():
    case = _case()

    assert case.file_path == "src/app.py"
    assert case.line_count == 40
    assert case.findings[0].rule_id == "SAST.SQL_INJECTION"


def test_a_case_with_no_recorded_review_is_refused():
    """There is nothing to grade, and a corpus entry that grades nothing
    inflates the denominator of every rate in the report."""
    with pytest.raises(ValueError):
        _case(review="   ")


def test_a_case_with_no_name_is_refused():
    with pytest.raises(ValueError):
        _case(name="")


def test_a_case_with_no_lines_is_refused():
    """A file of zero lines cannot be cited, so every citation check would
    pass vacuously — which reads as a clean review."""
    with pytest.raises(ValueError):
        _case(line_count=0)


def test_a_case_is_a_value():
    assert _case() == _case()


def test_the_severities_the_findings_carry_are_available_as_a_set():
    case = _case(findings=(_finding(Severity.CRITICAL), _finding(Severity.LOW, line=12)))

    assert case.severities == {Severity.CRITICAL, Severity.LOW}


# -- citations ---------------------------------------------------------------


def test_a_bare_citation_is_found():
    assert Citation.parse("see src/app.py:11 for the query") == (Citation("src/app.py", 11),)


def test_a_citation_inside_backticks_is_found():
    """Which is how this project's own renderer writes them."""
    assert Citation.parse("at `src/app.py:11` the query") == (Citation("src/app.py", 11),)


def test_a_citation_inside_a_table_cell_is_found():
    row = "| critical | SQL Injection | `src/app.py:11` | Parameterise it |"

    assert Citation.parse(row) == (Citation("src/app.py", 11),)


def test_a_line_range_is_read_as_its_first_line():
    """`path:11-14` is one citation about line 11, not a citation of line 14."""
    assert Citation.parse("`src/app.py:11-14`") == (Citation("src/app.py", 11),)


def test_every_citation_is_found_and_the_order_is_kept():
    prose = "first `a/b.py:3`, then c/d.py:9, then `a/b.py:3` again"

    assert Citation.parse(prose) == (
        Citation("a/b.py", 3),
        Citation("c/d.py", 9),
        Citation("a/b.py", 3),
    )


def test_prose_with_a_colon_is_not_a_citation():
    assert Citation.parse("Risk Assessment: Low - contained change") == ()


def test_a_url_is_not_a_citation():
    """`https://example.com:8080/x` has a colon and a number and is not a
    reference to a line of code."""
    assert Citation.parse("see https://example.com:8080/guide") == ()


def test_a_time_is_not_a_citation():
    assert Citation.parse("the run took 12:30 minutes") == ()


def test_a_citation_needs_a_file_extension():
    """`TODO:12` is a note, not a location."""
    assert Citation.parse("TODO:12 fix this") == ()


# -- a case that is meant to fail --------------------------------------------


def test_a_case_may_declare_the_checks_it_is_meant_to_fail():
    """A corpus of reviews that all pass cannot show that the harness is able
    to fail one. A case that declares its own defect makes the instrument
    testable by the same run that uses it."""
    case = _case(expected_failures=("citations_are_grounded",))

    assert case.expected_failures == ("citations_are_grounded",)


def test_a_case_declaring_an_unknown_check_is_refused():
    """A typo would otherwise be an expectation nothing can ever meet, which
    scores as a permanent failure nobody can fix."""
    with pytest.raises(ValueError) as error:
        _case(expected_failures=("citations_are_grouded",))

    assert "citations_are_grouded" in str(error.value)


def test_by_default_a_case_is_meant_to_pass_everything():
    assert _case().expected_failures == ()
