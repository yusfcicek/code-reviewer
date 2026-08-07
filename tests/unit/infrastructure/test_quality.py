"""Unit tests for the code quality analyzer."""

import ast
import textwrap
import unittest

from code_reviewer.infrastructure.analyzers.quality import (
    IssueCategory,
    IssueSeverity,
    QualityAnalyzer,
    check_code_quality,
)


def _categories(report):
    return {issue.category for issue in report.all_issues}


class TestSRP(unittest.TestCase):
    def setUp(self):
        self.analyzer = QualityAnalyzer()

    def test_class_with_too_many_public_methods_is_reported(self):
        methods = "\n".join(f"    def method_{i}(self): pass" for i in range(12))
        source = f"class Fat:\n{methods}\n"

        report = self.analyzer.analyze(source, "m.py")

        self.assertIn(IssueCategory.SOLID_SRP, _categories(report))

    def test_small_class_is_not_reported(self):
        source = "class Slim:\n    def one(self): pass\n    def two(self): pass\n"

        report = self.analyzer.analyze(source, "m.py")

        self.assertNotIn(IssueCategory.SOLID_SRP, _categories(report))

    def test_private_methods_do_not_count_towards_the_limit(self):
        methods = "\n".join(f"    def _helper_{i}(self): pass" for i in range(12))
        source = f"class Slim:\n{methods}\n"

        report = self.analyzer.analyze(source, "m.py")

        self.assertNotIn(IssueCategory.SOLID_SRP, _categories(report))


class TestComplexity(unittest.TestCase):
    def test_high_cyclomatic_complexity_is_reported(self):
        branches = "\n".join(f"    if value == {i}: return {i}" for i in range(15))
        source = f"def classify(value):\n{branches}\n    return None\n"

        report = QualityAnalyzer().analyze(source, "m.py")

        self.assertIn(IssueCategory.MAINTAINABILITY, _categories(report))

    def test_complexity_counts_boolean_operators(self):
        analyzer = QualityAnalyzer()
        tree = ast.parse("def f(a, b, c):\n    return a and b and c\n")
        function = tree.body[0]

        self.assertEqual(analyzer._calculate_cyclomatic_complexity(function), 3)


class TestErrorHandling(unittest.TestCase):
    def setUp(self):
        self.analyzer = QualityAnalyzer()

    def test_empty_except_is_reported(self):
        source = "try:\n    risky()\nexcept ValueError:\n    pass\n"

        report = self.analyzer.analyze(source, "m.py")

        self.assertEqual(report.error_handling.empty_catches, 1)

    def test_bare_except_is_reported(self):
        source = "try:\n    risky()\nexcept:\n    log()\n"

        report = self.analyzer.analyze(source, "m.py")

        self.assertEqual(report.error_handling.generic_exceptions, 1)

    def test_specific_handled_exception_is_clean(self):
        source = "try:\n    risky()\nexcept ValueError as exc:\n    log(exc)\n"

        report = self.analyzer.analyze(source, "m.py")

        self.assertEqual(report.error_handling.empty_catches, 0)
        self.assertEqual(report.error_handling.generic_exceptions, 0)


class TestTestability(unittest.TestCase):
    def test_global_usage_is_reported(self):
        source = "COUNTER = 0\ndef bump():\n    global COUNTER\n    COUNTER += 1\n"

        report = QualityAnalyzer().analyze(source, "m.py")

        self.assertIn(IssueCategory.TESTABILITY, _categories(report))

    def test_long_parameter_list_is_reported(self):
        source = "def wide(a, b, c, d, e, f, g):\n    return a\n"

        report = QualityAnalyzer().analyze(source, "m.py")

        self.assertIn(IssueCategory.TESTABILITY, _categories(report))

    def test_score_never_goes_negative(self):
        source = "\n".join(
            f"def wide_{i}(a, b, c, d, e, f, g):\n    return a" for i in range(40)
        )

        report = QualityAnalyzer().analyze(source, "m.py")

        self.assertGreaterEqual(report.testability.score, 0)


class TestDuplicates(unittest.TestCase):
    def test_repeated_block_is_reported(self):
        block = "\n".join(f"value_{i} = compute({i})" for i in range(6))
        source = f"{block}\nprint('separator')\n{block}\n"

        report = QualityAnalyzer().analyze(source, "m.py")

        self.assertIn(IssueCategory.DRY, _categories(report))

    def test_distinct_code_is_not_reported_as_duplicate(self):
        source = "\n".join(f"value_{i} = compute({i})" for i in range(20))

        report = QualityAnalyzer().analyze(source, "m.py")

        self.assertNotIn(IssueCategory.DRY, _categories(report))


class TestSeverityOrdering(unittest.TestCase):
    def test_severities_have_an_explicit_rank(self):
        self.assertLess(IssueSeverity.HIGH.rank, IssueSeverity.MEDIUM.rank)
        self.assertLess(IssueSeverity.MEDIUM.rank, IssueSeverity.LOW.rank)
        self.assertLess(IssueSeverity.LOW.rank, IssueSeverity.INFO.rank)

    def test_report_lists_high_severity_issues_first(self):
        """Regression for F-07."""
        source = textwrap.dedent(
            """
            class Holder:
                def __init__(self):
                    self.dependency = Service()

            def risky():
                try:
                    work()
                except ValueError:
                    pass
            """
        )

        rendered = check_code_quality(source, "m.py")
        details = rendered.split("### Quality Issues:")[1]

        self.assertLess(details.index("error_handling"), details.index("solid_dip"))


class TestScore(unittest.TestCase):
    def test_clean_module_scores_full_marks(self):
        report = QualityAnalyzer().analyze("VALUE = 1\n", "m.py")

        self.assertEqual(report.quality_score, 100)

    def test_non_python_files_are_still_scanned_for_duplicates(self):
        block = "\n".join(f"int value_{i} = compute({i});" for i in range(6))
        report = QualityAnalyzer().analyze(f"{block}\n// gap\n{block}\n", "main.cpp")

        self.assertIn(IssueCategory.DRY, _categories(report))


if __name__ == "__main__":
    unittest.main()
