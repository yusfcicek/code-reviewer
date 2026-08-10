"""Step 2 — putting an import where imports go.

An insertion is expressed as a replacement of the line it follows, because a
`SuggestionEdit` replaces a range and an empty replacement is refused. That is
not a workaround: "the import goes after this line" is exactly what the edit
says, and the platform renders it as one block.
"""

from code_reviewer.domain.fix_recipes import import_edit

WITH_IMPORTS = "import os\nimport sys\n\n\ndef f():\n    return 1\n"
WITH_DOCSTRING = '"""What this is."""\n\n\ndef f():\n    return 1\n'
MULTILINE_DOCSTRING = '"""Line one.\n\nLine two.\n"""\n\n\ndef f():\n    return 1\n'
BARE = "def f():\n    return 1\n"


def _applied(source, module="secrets"):
    edit = import_edit(source, module)
    if edit is None:
        return None
    lines = source.splitlines()
    return "\n".join([*lines[: edit.start_line - 1], *edit.replacement, *lines[edit.end_line :]])


class TestWhereItLands:
    def test_after_the_last_import(self):
        """AC-8."""
        assert _applied(WITH_IMPORTS).startswith("import os\nimport sys\nimport secrets\n")

    def test_after_a_module_docstring_when_there_are_no_imports(self):
        """Never before it: a docstring that is no longer the first statement
        is no longer a docstring."""
        applied = _applied(WITH_DOCSTRING)

        assert applied.startswith('"""What this is."""')
        assert "import secrets" in applied

    def test_after_a_multi_line_docstring(self):
        applied = _applied(MULTILINE_DOCSTRING)

        assert applied.splitlines()[3] == '"""'
        assert "import secrets" in applied.splitlines()[4]

    def test_at_the_top_when_there_is_neither(self):
        assert _applied(BARE).startswith("import secrets\ndef f():")


class TestWhenItDeclines:
    def test_an_import_already_there_is_not_added(self):
        """AC-7."""
        assert import_edit("import secrets\n\nx = 1\n", "secrets") is None

    def test_a_from_import_counts_as_present(self):
        assert import_edit("from secrets import SystemRandom\n\nx = 1\n", "secrets") is None

    def test_an_aliased_import_counts_as_present(self):
        assert import_edit("import secrets as s\n\nx = 1\n", "secrets") is None

    def test_a_submodule_import_counts_as_present(self):
        assert import_edit("import os.path\n\nx = 1\n", "os.path") is None

    def test_a_similarly_named_module_does_not_count(self):
        """`secretstuff` is not `secrets`."""
        assert import_edit("import secretstuff\n\nx = 1\n", "secrets") is not None

    def test_a_file_that_does_not_parse_yields_nothing(self):
        """A guess about where imports go in a file nobody can parse is a guess."""
        assert import_edit("def (:\n", "secrets") is None

    def test_an_empty_file_yields_nothing(self):
        assert import_edit("", "secrets") is None


class TestWhatItProduces:
    def test_it_is_an_edit_the_suggestion_type_accepts(self):
        from code_reviewer.domain.remediation import Suggestion

        edit = import_edit(WITH_IMPORTS, "secrets")

        assert Suggestion(rule_id="R.A", file_path="a.py", edits=(edit,), recipe="x").edits

    def test_it_keeps_the_line_it_follows(self):
        """The insertion replaces a line with itself and the import, so nothing
        the file already had is lost."""
        edit = import_edit(WITH_IMPORTS, "secrets")

        assert edit.replacement[0] == "import sys"
        assert edit.replacement[1] == "import secrets"

    def test_it_composes_with_another_edit_further_down(self):
        from code_reviewer.domain.remediation import Suggestion, SuggestionEdit

        suggestion = Suggestion(
            rule_id="SAST.INSECURE_RANDOM",
            file_path="a.py",
            edits=(
                import_edit(WITH_IMPORTS, "secrets"),
                SuggestionEdit(6, 6, ("    return 2",)),
            ),
            recipe="x",
        )

        applied = suggestion.applied_to(WITH_IMPORTS)

        assert "import secrets" in applied
        assert "return 2" in applied
