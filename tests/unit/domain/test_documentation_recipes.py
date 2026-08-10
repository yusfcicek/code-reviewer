"""Step 6 — the one documentation edit that is arithmetic.

Level 23 refused to suggest documentation prose, and that refusal holds: a
model-authored sentence in a README is a claim nobody reviewed, in the exact
position that level exists to distrust.

A rename is different. The diff knows the old name and the new one, so
substituting one for the other in a document is a substitution — not a
generation, and not a judgement. It is the only documentation edit this
repository will offer.
"""

import pytest

from code_reviewer.domain.documentation import Rename, documentation_suggestion, rename_in

RENAME = "@@ -1,3 +1,3 @@\n-def start_app(config):\n+def create_app(config):\n     return config\n"
TWO_RENAMES = (
    "@@ -1,6 +1,6 @@\n"
    "-def start_app(config):\n"
    "-def start_worker(config):\n"
    "+def create_app(config):\n"
    "+def create_worker(config):\n"
)


class TestReadingARenameFromADiff:
    def test_one_removal_and_one_addition_is_a_rename(self):
        assert rename_in(RENAME) == Rename(old="start_app", new="create_app")

    def test_two_of_each_is_ambiguous(self):
        """AC-13. Which old name became which new one is not in the diff, and
        guessing is how a suggestion renames the wrong thing."""
        assert rename_in(TWO_RENAMES) is None

    def test_a_removal_with_no_addition_is_not_a_rename(self):
        assert rename_in("@@ -1,2 +1,1 @@\n-def start_app(config):\n") is None

    def test_an_addition_with_no_removal_is_not_a_rename(self):
        assert rename_in("@@ -1,1 +1,2 @@\n+def create_app(config):\n") is None

    def test_a_changed_signature_is_not_a_rename(self):
        diff = "@@ -1,2 +1,2 @@\n-def create_app(config):\n+def create_app(config, worker):\n"

        assert rename_in(diff) is None

    def test_an_empty_diff_is_not_a_rename(self):
        assert rename_in("") is None


class TestTheSuggestion:
    DOCUMENT = "# Guide\n\nBoot with `start_app`, then configure it.\n"

    def test_it_substitutes_the_old_name_for_the_new_one(self):
        """AC-12."""
        suggestion = documentation_suggestion(
            path="README.md", text=self.DOCUMENT, line=3, rename=Rename("start_app", "create_app")
        )

        applied = suggestion.applied_to(self.DOCUMENT)

        assert "`create_app`" in applied
        assert "start_app" not in applied

    def test_it_keeps_everything_else_on_the_line(self):
        suggestion = documentation_suggestion(
            path="README.md", text=self.DOCUMENT, line=3, rename=Rename("start_app", "create_app")
        )

        assert "then configure it." in suggestion.applied_to(self.DOCUMENT)

    def test_it_names_the_recipe(self):
        suggestion = documentation_suggestion(
            path="README.md", text=self.DOCUMENT, line=3, rename=Rename("start_app", "create_app")
        )

        assert suggestion.recipe == "rename-in-documentation"

    def test_it_answers_the_dead_reference_rule(self):
        suggestion = documentation_suggestion(
            path="README.md", text=self.DOCUMENT, line=3, rename=Rename("start_app", "create_app")
        )

        assert suggestion.rule_id == "DOCS.DEAD_REFERENCE"

    def test_a_line_that_does_not_contain_the_old_name_yields_nothing(self):
        assert (
            documentation_suggestion(
                path="README.md", text=self.DOCUMENT, line=1, rename=Rename("start_app", "create_app")
            )
            is None
        )

    def test_a_line_past_the_end_yields_nothing(self):
        assert (
            documentation_suggestion(
                path="README.md", text=self.DOCUMENT, line=99, rename=Rename("start_app", "create_app")
            )
            is None
        )

    def test_a_partial_word_is_not_substituted(self):
        """`start_application` is not `start_app`, and a substring rename is how
        a document acquires `create_applicationlication`."""
        text = "# Guide\n\nCall `start_application` first.\n"

        assert (
            documentation_suggestion(
                path="README.md", text=text, line=3, rename=Rename("start_app", "create_app")
            )
            is None
        )

    def test_every_occurrence_on_the_line_is_substituted(self):
        """The lesson from self-review 26: fixing the first of two is half a fix
        a reader reads as a whole one."""
        text = "# Guide\n\n`start_app` calls `start_app` again.\n"

        applied = documentation_suggestion(
            path="README.md", text=text, line=3, rename=Rename("start_app", "create_app")
        ).applied_to(text)

        assert applied.count("create_app") == 2
        assert "start_app" not in applied


def test_a_rename_needs_two_different_names():
    with pytest.raises(ValueError):
        Rename(old="same", new="same")


def test_a_rename_needs_both_names():
    with pytest.raises(ValueError):
        Rename(old="", new="create_app")
