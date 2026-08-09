"""Step 1 — what a suggestion is, and what it refuses to be."""

import pytest

from code_reviewer.domain.remediation import MAX_SUGGESTION_LINES, Suggestion

SOURCE = "\n".join(
    [
        "import hashlib",
        "",
        "def digest(value):",
        "    return hashlib.md5(value).hexdigest()",
        "",
    ]
)


def _suggestion(**overrides) -> Suggestion:
    defaults = {
        "rule_id": "SAST.WEAK_CRYPTO",
        "file_path": "src/hashing.py",
        "start_line": 4,
        "end_line": 4,
        "replacement": ("    return hashlib.sha256(value).hexdigest()",),
        "recipe": "md5-to-sha256",
    }
    return Suggestion(**{**defaults, **overrides})


# -- what it carries ---------------------------------------------------------


def test_a_suggestion_names_the_finding_the_file_and_the_recipe():
    suggestion = _suggestion()

    assert suggestion.rule_id == "SAST.WEAK_CRYPTO"
    assert suggestion.file_path == "src/hashing.py"
    assert suggestion.recipe == "md5-to-sha256"


def test_a_suggestion_is_a_value():
    assert _suggestion() == _suggestion()


def test_the_line_span_is_what_the_platform_needs():
    """GitLab's block is anchored on a line and told how far above and below
    it reaches."""
    suggestion = _suggestion(start_line=4, end_line=6)

    assert suggestion.lines_above == 0
    assert suggestion.lines_below == 2


# -- what it refuses ---------------------------------------------------------


def test_a_range_that_ends_before_it_starts_is_refused():
    with pytest.raises(ValueError):
        _suggestion(start_line=6, end_line=4)


def test_a_range_starting_before_the_first_line_is_refused():
    with pytest.raises(ValueError):
        _suggestion(start_line=0, end_line=1)


def test_a_suggestion_with_no_recipe_is_refused():
    """ "Something proposed this" is not provenance — the same sentence
    Level 20 refused for a producer."""
    with pytest.raises(ValueError):
        _suggestion(recipe="  ")


def test_a_suggestion_longer_than_the_bound_is_refused():
    """Past a handful of lines it is a refactor, and a refactor arriving as a
    one-click button is how a reviewer stops reading."""
    with pytest.raises(ValueError):
        _suggestion(replacement=tuple(f"line {i}" for i in range(MAX_SUGGESTION_LINES + 1)))


def test_a_suggestion_that_changes_nothing_is_refused():
    with pytest.raises(ValueError):
        _suggestion(start_line=4, end_line=4, replacement=())


# -- applying it -------------------------------------------------------------


def test_applying_it_replaces_the_named_range():
    applied = _suggestion().applied_to(SOURCE)

    assert "hashlib.sha256(value)" in applied
    assert "md5" not in applied


def test_applying_it_leaves_every_other_line_alone():
    applied = _suggestion().applied_to(SOURCE)

    assert applied.splitlines()[0] == "import hashlib"
    assert len(applied.splitlines()) == len(SOURCE.splitlines())


def test_a_range_past_the_end_of_the_file_does_not_apply():
    """`None` rather than a truncated edit: a suggestion that silently applies
    to fewer lines than it claimed is a suggestion nobody can predict."""
    assert _suggestion(start_line=40, end_line=41).applied_to(SOURCE) is None


def test_replacing_several_lines_with_one_is_applied_as_written():
    suggestion = _suggestion(start_line=3, end_line=4, replacement=("def digest(value): ...",))

    applied = suggestion.applied_to(SOURCE)

    assert applied.splitlines() == ["import hashlib", "", "def digest(value): ..."]
    assert applied.endswith("\n"), "the file's trailing newline survives the edit"


def test_the_replaced_text_is_available_for_a_check():
    """The service compares it against what the recipe said it matched."""
    assert _suggestion().replaced_in(SOURCE) == ("    return hashlib.md5(value).hexdigest()",)


def test_nothing_is_replaced_when_the_range_is_outside_the_file():
    assert _suggestion(start_line=99, end_line=99).replaced_in(SOURCE) == ()
