"""Unit tests for the performance analyzer.

The string-concatenation rule could never fire: it tested `'for ' in lines[a:b]`,
a membership check against a **list**, which requires an element to equal the
string exactly (finding F-05). Report ordering had the same alphabetical
severity bug as the other analyzers (F-07).
"""

import textwrap
import unittest

from code_reviewer.domain.severity import Severity
from code_reviewer.infrastructure.analyzers.performance import (
    PerformanceAnalyzer,
    PerformanceIssueType,
    analyze_performance,
)


def _issue_types(report):
    return {issue.issue_type for issue in report.issues}


class TestComplexity(unittest.TestCase):
    def setUp(self):
        self.analyzer = PerformanceAnalyzer()

    def test_nested_loops_are_reported_as_quadratic(self):
        source = textwrap.dedent(
            """
            def pairs(items):
                for a in items:
                    for b in items:
                        print(a, b)
            """
        )

        report = self.analyzer.analyze(source, "m.py")

        complexities = {r.function_name: r.estimated_complexity for r in report.complexity_reports}
        self.assertEqual(complexities["pairs"], "O(n²)")

    def test_single_loop_is_not_flagged(self):
        source = textwrap.dedent(
            """
            def walk(items):
                for a in items:
                    print(a)
            """
        )

        report = self.analyzer.analyze(source, "m.py")

        self.assertNotIn(PerformanceIssueType.HIGH_COMPLEXITY, _issue_types(report))

    def test_recursion_is_reported(self):
        source = textwrap.dedent(
            """
            def fib(n):
                return n if n < 2 else fib(n - 1) + fib(n - 2)
            """
        )

        report = self.analyzer.analyze(source, "m.py")

        self.assertIn(PerformanceIssueType.RECURSIVE_RISK, _issue_types(report))


class TestStringConcatenationInLoop(unittest.TestCase):
    """Regression for F-05."""

    def setUp(self):
        self.analyzer = PerformanceAnalyzer()

    def test_concatenation_inside_a_for_loop_is_reported(self):
        source = textwrap.dedent(
            """
            def join(items):
                out = ""
                for item in items:
                    out += "," + item
                return out
            """
        )

        report = self.analyzer.analyze(source, "m.py")

        self.assertIn(PerformanceIssueType.INEFFICIENT_LOOP, _issue_types(report))

    def test_concatenation_inside_a_while_loop_is_reported(self):
        source = textwrap.dedent(
            """
            def build(n):
                out = ""
                while n:
                    out += "x"
                    n -= 1
                return out
            """
        )

        report = self.analyzer.analyze(source, "m.py")

        self.assertIn(PerformanceIssueType.INEFFICIENT_LOOP, _issue_types(report))

    def test_concatenation_outside_a_loop_is_not_reported(self):
        source = 'greeting = "hello"\ngreeting += " world"\n'

        report = self.analyzer.analyze(source, "m.py")

        self.assertNotIn(PerformanceIssueType.INEFFICIENT_LOOP, _issue_types(report))

    def test_numeric_accumulation_in_a_loop_is_not_reported(self):
        source = textwrap.dedent(
            """
            def total(items):
                acc = 0
                for item in items:
                    acc += item
                return acc
            """
        )

        report = self.analyzer.analyze(source, "m.py")

        self.assertNotIn(PerformanceIssueType.INEFFICIENT_LOOP, _issue_types(report))


class TestNPlusOne(unittest.TestCase):
    def test_query_inside_a_loop_is_reported(self):
        source = textwrap.dedent(
            """
            def load(ids, session):
                for identifier in ids:
                    session.query(identifier)
            """
        )

        report = PerformanceAnalyzer().analyze(source, "m.py")

        self.assertTrue(report.n_plus_one_patterns)


class TestResourceLeaks(unittest.TestCase):
    def test_unclosed_resource_is_reported(self):
        source = 'handle = open("data.txt")\nprint(handle)\n'

        report = PerformanceAnalyzer().analyze(source, "m.py")

        self.assertTrue(report.memory_leak_risks)

    def test_closed_resource_is_not_reported_as_unclosed(self):
        source = 'handle = open("data.txt")\nhandle.close()\n'

        report = PerformanceAnalyzer().analyze(source, "m.py")

        descriptions = " ".join(r.description for r in report.memory_leak_risks)
        self.assertNotIn("may not be properly closed", descriptions)


class TestSeverityOrdering(unittest.TestCase):
    def test_issues_carry_the_shared_domain_severity(self):
        report = PerformanceAnalyzer().analyze('h = open("f")\n', "m.py")

        self.assertIsInstance(report.issues[0].severity, Severity)

    def test_report_lists_high_severity_issues_before_low_ones(self):
        """Regression for F-07."""
        source = textwrap.dedent(
            """
            import time

            def scan(items, session):
                time.sleep(1)
                for a in items:
                    for b in items:
                        session.query(a, b)
            """
        )

        rendered = analyze_performance(source, "m.py")
        details = rendered.split("### Performance Issues:")[1]

        self.assertLess(details.index("n_plus_one"), details.index("blocking_operation"))


class TestScore(unittest.TestCase):
    def test_clean_file_scores_full_marks(self):
        report = PerformanceAnalyzer().analyze("VALUE = 1\n", "m.py")

        self.assertEqual(report.performance_score, 100)

    def test_score_never_goes_negative(self):
        source = "\n".join(f'handle{i} = open("f{i}")' for i in range(40))

        report = PerformanceAnalyzer().analyze(source, "m.py")

        self.assertGreaterEqual(report.performance_score, 0)


if __name__ == "__main__":
    unittest.main()
