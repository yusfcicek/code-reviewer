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
    # `single` rather than the set constructor: these tests are the regression
    # suite for the Level 22 shape, and they are deliberately not rewritten
    # against the Level 26 one.
    return Suggestion.single(**{**defaults, **overrides})


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


class TestASuggestionIsASetOfEdits:
    """Level 26, step 1 — the one-range rule excluded a whole shape of fix.

    A fix that needs an import at the top and a call in the middle was not
    offerable at all, and it was excluded by an accident of format rather than
    by judgement: every guarantee that mattered was about *validation*, and
    validating a set is the same operation as validating one.
    """

    SOURCE = "import random\n\n\ndef token():\n    return random.random()\n"

    def _edit(self, start, end, replacement):
        from code_reviewer.domain.remediation import SuggestionEdit

        return SuggestionEdit(start_line=start, end_line=end, replacement=tuple(replacement))

    def _suggestion(self, *edits):
        from code_reviewer.domain.remediation import Suggestion

        return Suggestion(
            rule_id="SAST.INSECURE_RANDOM",
            file_path="app.py",
            edits=tuple(edits),
            recipe="insecure_random",
        )

    def test_two_edits_are_both_applied(self):
        """AC-1."""
        suggestion = self._suggestion(
            self._edit(1, 1, ["import secrets"]),
            self._edit(5, 5, ["    return secrets.SystemRandom().random()"]),
        )

        applied = suggestion.applied_to(self.SOURCE)

        assert "import secrets" in applied
        assert "secrets.SystemRandom" in applied

    def test_edits_apply_bottom_up_so_an_earlier_one_does_not_move_a_later_one(self):
        """AC-3. Applying top-down invalidates every later line number — the
        arithmetic that is wrong once and then wrong everywhere."""
        suggestion = self._suggestion(
            self._edit(1, 1, ["import secrets", "import os"]),  # grows the file by a line
            self._edit(5, 5, ["    return secrets.SystemRandom().random()"]),
        )

        applied = suggestion.applied_to(self.SOURCE).splitlines()

        assert applied[0] == "import secrets"
        assert applied[1] == "import os"
        assert applied[-1] == "    return secrets.SystemRandom().random()"

    def test_overlapping_edits_are_refused_at_construction(self):
        """AC-2. Two edits claiming one line produce a result nobody can
        predict, so they are refused rather than resolved by ordering."""
        import pytest

        with pytest.raises(ValueError):
            self._suggestion(self._edit(3, 5, ["a"]), self._edit(4, 6, ["b"]))

    def test_adjacent_edits_are_allowed(self):
        assert self._suggestion(self._edit(1, 1, ["a"]), self._edit(2, 2, ["b"])).edits

    def test_the_line_bound_counts_every_edit_together(self):
        """AC-5. Otherwise five edits of twelve lines is a sixty-line button."""
        import pytest

        from code_reviewer.domain.remediation import MAX_SUGGESTION_LINES

        half = ["x"] * (MAX_SUGGESTION_LINES // 2 + 1)
        with pytest.raises(ValueError):
            self._suggestion(self._edit(1, 1, half), self._edit(10, 10, half))

    def test_an_empty_edit_set_is_refused(self):
        import pytest

        with pytest.raises(ValueError):
            self._suggestion()

    def test_an_edit_past_the_end_of_the_file_yields_nothing(self):
        suggestion = self._suggestion(self._edit(1, 1, ["import secrets"]), self._edit(99, 99, ["x"]))

        assert suggestion.applied_to(self.SOURCE) is None

    def test_a_single_edit_still_behaves_as_it_did(self):
        suggestion = self._suggestion(self._edit(1, 1, ["import secrets"]))

        assert suggestion.applied_to(self.SOURCE).startswith("import secrets\n")
