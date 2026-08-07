"""Unit tests for the single severity type.

Three enums used to describe this one concept — `sast_analyzer.Severity`,
`performance_analyzer.Severity` and `quality_analyzer.IssueSeverity` — so
nothing could aggregate findings across analyzers (finding F-28). Level 1 gave
each a `rank` property as the minimal fix; with one type, ordering belongs on
the type itself.
"""

import unittest

from code_reviewer.domain.severity import Severity


class TestOrdering(unittest.TestCase):
    def test_more_severe_compares_as_less_than(self):
        """`CRITICAL < HIGH` so that `sorted()` puts the worst first."""
        self.assertLess(Severity.CRITICAL, Severity.HIGH)
        self.assertLess(Severity.HIGH, Severity.MEDIUM)
        self.assertLess(Severity.MEDIUM, Severity.LOW)
        self.assertLess(Severity.LOW, Severity.INFO)

    def test_sorting_a_mixed_list_needs_no_key_function(self):
        unsorted = [Severity.LOW, Severity.CRITICAL, Severity.MEDIUM, Severity.INFO]

        self.assertEqual(
            sorted(unsorted),
            [Severity.CRITICAL, Severity.MEDIUM, Severity.LOW, Severity.INFO],
        )

    def test_worst_of_a_list_is_the_minimum(self):
        self.assertEqual(min([Severity.LOW, Severity.CRITICAL, Severity.MEDIUM]), Severity.CRITICAL)

    def test_comparison_with_a_non_severity_is_not_supported(self):
        with self.assertRaises(TypeError):
            Severity.HIGH < 3


class TestValues(unittest.TestCase):
    def test_value_is_the_lowercase_name(self):
        self.assertEqual(Severity.CRITICAL.value, "critical")
        self.assertEqual(Severity.INFO.value, "info")

    def test_parsing_accepts_any_casing(self):
        self.assertIs(Severity.parse("CRITICAL"), Severity.CRITICAL)
        self.assertIs(Severity.parse("  High "), Severity.HIGH)

    def test_parsing_an_unknown_value_returns_the_fallback(self):
        self.assertIs(Severity.parse("catastrophic"), Severity.INFO)
        self.assertIs(Severity.parse(None, default=Severity.MEDIUM), Severity.MEDIUM)

    def test_string_form_is_the_value(self):
        self.assertEqual(str(Severity.HIGH), "high")


class TestBlocking(unittest.TestCase):
    def test_critical_and_high_are_blocking_by_default(self):
        self.assertTrue(Severity.CRITICAL.is_at_least(Severity.HIGH))
        self.assertTrue(Severity.HIGH.is_at_least(Severity.HIGH))

    def test_medium_is_not_as_severe_as_high(self):
        self.assertFalse(Severity.MEDIUM.is_at_least(Severity.HIGH))


class TestWeights(unittest.TestCase):
    def test_weight_decreases_with_severity(self):
        self.assertGreater(Severity.CRITICAL.weight, Severity.HIGH.weight)
        self.assertGreater(Severity.HIGH.weight, Severity.MEDIUM.weight)
        self.assertGreater(Severity.MEDIUM.weight, Severity.LOW.weight)

    def test_info_carries_no_weight(self):
        self.assertEqual(Severity.INFO.weight, 0)


if __name__ == "__main__":
    unittest.main()
