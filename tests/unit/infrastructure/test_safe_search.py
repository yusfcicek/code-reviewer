"""Building a `grep` command out of a pattern the model produced.

The pattern's provenance is the diff: whoever opened the merge request wrote
the code the model is reading, and the model turns that into a search term. So
the term is untrusted, and two things follow (finding G-06).

It must be a *fixed string*. Without ``-F`` it is a basic regular expression,
which gives wrong matches for any symbol containing ``.`` or ``*``, and gives
catastrophic backtracking inside a blocking CI job.

And the search must not read credentials. Excluding build directories is about
noise; excluding ``.env`` and ``*.pem`` is about what comes back in the
observation and, from there, into a public merge-request comment.
"""

import unittest

from code_reviewer.infrastructure.tools.safe_search import (
    MAX_PATTERN_LENGTH,
    InvalidPatternError,
    build_grep_command,
    validate_pattern,
)


class TestCommandShape(unittest.TestCase):
    def setUp(self):
        self.command = build_grep_command("handle_request", ["/repo"])

    def test_the_pattern_is_a_fixed_string(self):
        """Without -F the pattern is a BRE: wrong matches and a ReDoS surface."""
        self.assertIn("-F", self.command)

    def test_the_pattern_comes_after_the_separator(self):
        """`--` is what stops a pattern from being read as a flag."""
        separator = self.command.index("--")
        pattern = self.command.index("handle_request")

        self.assertLess(separator, pattern)

    def test_the_match_count_is_bounded(self):
        self.assertTrue(any(argument.startswith("--max-count=") for argument in self.command))

    def test_binary_files_are_skipped(self):
        self.assertIn("-rnI", self.command)

    def test_the_search_paths_come_last(self):
        self.assertEqual(self.command[-1], "/repo")

    def test_several_paths_are_all_included(self):
        command = build_grep_command("x", ["/a", "/b"])

        self.assertEqual(command[-2:], ["/a", "/b"])

    def test_no_path_is_rejected(self):
        with self.assertRaises(ValueError):
            build_grep_command("x", [])


class TestExclusions(unittest.TestCase):
    def setUp(self):
        self.command = build_grep_command("x", ["/repo"])

    def test_build_output_is_excluded(self):
        for directory in ("build", ".git", "node_modules", "__pycache__", ".venv"):
            with self.subTest(directory=directory):
                self.assertIn(f"--exclude-dir={directory}", self.command)

    def test_secret_bearing_files_are_excluded(self):
        """A matching line from .env goes into a public comment otherwise."""
        for pattern in (".env", ".env.*", "*.pem", "*.key", "id_rsa"):
            with self.subTest(pattern=pattern):
                self.assertIn(f"--exclude={pattern}", self.command)

    def test_lock_files_and_minified_bundles_are_excluded(self):
        for pattern in ("*.lock", "*.min.js"):
            with self.subTest(pattern=pattern):
                self.assertIn(f"--exclude={pattern}", self.command)


class TestPatternValidation(unittest.TestCase):
    def test_an_ordinary_symbol_is_accepted(self):
        for symbol in ("handle_request", "MyClass", "_private", "a.b.c", "My::Type", "file-name.h"):
            with self.subTest(symbol=symbol):
                self.assertEqual(validate_pattern(symbol), symbol)

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(validate_pattern("  handle  "), "handle")

    def test_an_empty_pattern_is_refused(self):
        for value in ("", "   ", "\t"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(InvalidPatternError):
                    validate_pattern(value)

    def test_a_leading_dash_is_refused(self):
        """`--` makes it safe, but a leading dash is still an injection attempt."""
        with self.assertRaises(InvalidPatternError):
            validate_pattern("--include=*.env")

    def test_control_characters_are_refused(self):
        for value in ("a\nb", "a\rb", "a\x00b"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(InvalidPatternError):
                    validate_pattern(value)

    def test_path_traversal_is_refused(self):
        with self.assertRaises(InvalidPatternError):
            validate_pattern("../../etc/passwd")

    def test_an_over_long_pattern_is_refused(self):
        with self.assertRaises(InvalidPatternError):
            validate_pattern("a" * (MAX_PATTERN_LENGTH + 1))

    def test_shell_metacharacters_are_refused(self):
        """`shell=False` already makes these inert; refusing them says so."""
        for value in ("a;rm -rf /", "a|b", "a$(id)", "a`id`"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(InvalidPatternError):
                    validate_pattern(value)

    def test_a_non_string_is_refused(self):
        with self.assertRaises(InvalidPatternError):
            validate_pattern(None)  # type: ignore[arg-type]

    def test_the_refusal_names_the_pattern(self):
        """The message goes back to the model, so it has to be actionable."""
        with self.assertRaises(InvalidPatternError) as caught:
            validate_pattern("-c")

        self.assertIn("-c", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
