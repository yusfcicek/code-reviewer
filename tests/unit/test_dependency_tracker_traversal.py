"""AST traversal and reporting in the dependency tracker.

Complements `test_dependency_tracker.py`, which specifies usage
classification. Everything here works on temporary files rather than the
repository, so the tests do not depend on the project's own layout.
"""

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openhands.agent.analyzers.dependency_tracker import (
    AffectedCode,
    DependencyTracker,
    DependencyType,
    find_ripple_effects,
)

MODULE = textwrap.dedent(
    """
    def outer(value):
        helper(value)
        return transform(value)


    def helper(value):
        return value + 1


    def transform(value):
        return value * 2
    """
).strip()


class _Module:
    """Writes MODULE to a temporary file and yields its path."""

    def __enter__(self):
        self._directory = TemporaryDirectory()
        path = Path(self._directory.name) / "sample.py"
        path.write_text(MODULE, encoding="utf-8")
        return str(path)

    def __exit__(self, *exc_info):
        self._directory.cleanup()
        return False


class TestContainingFunction(unittest.TestCase):
    def setUp(self):
        self.tracker = DependencyTracker(".")

    def test_line_inside_a_function_resolves_to_that_function(self):
        with _Module() as path:
            self.assertEqual(self.tracker._find_containing_function(path, 2), "outer")

    def test_line_inside_a_later_function_resolves_correctly(self):
        with _Module() as path:
            self.assertEqual(self.tracker._find_containing_function(path, 7), "helper")

    def test_non_python_file_yields_no_function(self):
        self.assertEqual(self.tracker._find_containing_function("notes.txt", 1), "")

    def test_unreadable_file_yields_no_function(self):
        self.assertEqual(self.tracker._find_containing_function("/nope/missing.py", 1), "")


class TestCallees(unittest.TestCase):
    def setUp(self):
        self.tracker = DependencyTracker(".")

    def test_calls_made_by_a_function_are_listed(self):
        with _Module() as path:
            callees = self.tracker._find_callees("outer", path)

        self.assertEqual(set(callees), {"helper", "transform"})

    def test_unknown_function_has_no_callees(self):
        with _Module() as path:
            self.assertEqual(self.tracker._find_callees("absent", path), [])

    def test_non_python_file_has_no_callees(self):
        self.assertEqual(self.tracker._find_callees("outer", "notes.txt"), [])


class TestFileCache(unittest.TestCase):
    def test_second_read_comes_from_the_cache(self):
        tracker = DependencyTracker(".")
        with _Module() as path:
            first = tracker._read_file_cached(path)
            Path(path).write_text("changed", encoding="utf-8")
            second = tracker._read_file_cached(path)

        self.assertEqual(first, second)

    def test_missing_file_reads_as_none(self):
        self.assertIsNone(DependencyTracker(".")._read_file_cached("/nope/missing.py"))


class TestRippleEffects(unittest.TestCase):
    def test_second_level_usages_are_labelled_as_indirect(self):
        tracker = DependencyTracker(".")

        def usages(symbol):
            if symbol == "Target":
                return [AffectedCode("a.py", "caller", 3, DependencyType.DIRECT_CALL)]
            return [AffectedCode("b.py", "outer_caller", 9, DependencyType.DIRECT_CALL)]

        tracker._find_all_usages = usages
        affected = tracker.find_ripple_effects("Target")

        reasons = [code.reason for code in affected]
        self.assertIn("Directly uses 'Target'", reasons)
        self.assertTrue(any("Indirectly affected" in reason for reason in reasons))

    def test_wrapper_reports_the_symbol_and_the_count(self):
        rendered = find_ripple_effects("DefinitelyNotPresentSymbolXYZ", ".")

        self.assertIn("DefinitelyNotPresentSymbolXYZ", rendered)
        self.assertIn("Total affected locations", rendered)


class TestImpactSummary(unittest.TestCase):
    def test_summary_breaks_usages_down_by_type(self):
        tracker = DependencyTracker(".")
        tracker._find_all_usages = lambda _symbol: [
            AffectedCode("a.py", "fn", 1, DependencyType.DIRECT_CALL),
            AffectedCode("b.py", "fn", 2, DependencyType.IMPORT),
        ]

        rendered = tracker.get_affected_by_struct_change("Target")

        self.assertIn("direct_call: 1", rendered)
        self.assertIn("import: 1", rendered)


if __name__ == "__main__":
    unittest.main()
