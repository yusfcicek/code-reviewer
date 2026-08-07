"""Unit tests for the code quality analyzer."""

import ast
import textwrap
import unittest

from code_reviewer.domain.policy import QualityPolicy
from code_reviewer.domain.severity import Severity
from code_reviewer.infrastructure.analyzers.quality import (
    IssueCategory,
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
        source = "\n".join(f"def wide_{i}(a, b, c, d, e, f, g):\n    return a" for i in range(40))

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
    def test_issues_carry_the_shared_domain_severity(self):
        source = "try:\n    risky()\nexcept ValueError:\n    pass\n"

        report = QualityAnalyzer().analyze(source, "m.py")

        self.assertIsInstance(report.all_issues[0].severity, Severity)

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


class TestPolicyDrivenThresholds(unittest.TestCase):
    """Regression for F-31.

    QualityPolicy existed, was loaded from YAML, and was then ignored in
    favour of class constants — so configuring a threshold changed nothing.
    """

    def _class_with(self, method_count):
        methods = "\n".join(f"    def method_{i}(self): pass" for i in range(method_count))
        return f"class Wide:\n{methods}\n"

    def test_default_policy_reports_a_wide_class(self):
        report = QualityAnalyzer(QualityPolicy()).analyze(self._class_with(20), "m.py")

        self.assertIn(IssueCategory.SOLID_SRP, _categories(report))

    def test_raising_the_method_limit_silences_it(self):
        policy = QualityPolicy(max_class_methods=30)

        report = QualityAnalyzer(policy).analyze(self._class_with(20), "m.py")

        self.assertNotIn(IssueCategory.SOLID_SRP, _categories(report))

    def test_lowering_the_method_limit_reports_a_narrow_class(self):
        policy = QualityPolicy(max_class_methods=1)
        source = "class Narrow:\n    def one(self): pass\n    def two(self): pass\n"

        report = QualityAnalyzer(policy).analyze(source, "m.py")

        self.assertIn(IssueCategory.SOLID_SRP, _categories(report))

    def test_function_length_limit_is_configurable(self):
        body = "\n".join(f"    step_{i} = {i}" for i in range(30))
        source = f"def long_one():\n{body}\n"

        strict = QualityAnalyzer(QualityPolicy(max_function_lines=10)).analyze(source, "m.py")
        lenient = QualityAnalyzer(QualityPolicy(max_function_lines=200)).analyze(source, "m.py")

        self.assertIn(IssueCategory.SOLID_SRP, _categories(strict))
        self.assertNotIn(IssueCategory.SOLID_SRP, _categories(lenient))

    def test_complexity_limit_is_configurable(self):
        branches = "\n".join(f"    if value == {i}: return {i}" for i in range(8))
        source = f"def classify(value):\n{branches}\n    return None\n"

        strict = QualityAnalyzer(QualityPolicy(max_cyclomatic_complexity=3)).analyze(source, "m.py")
        lenient = QualityAnalyzer(QualityPolicy(max_cyclomatic_complexity=50)).analyze(source, "m.py")

        self.assertIn(IssueCategory.MAINTAINABILITY, _categories(strict))
        self.assertNotIn(IssueCategory.MAINTAINABILITY, _categories(lenient))

    def test_duplicate_block_size_is_configurable(self):
        block = "\n".join(f"value_{i} = compute({i})" for i in range(4))
        source = f"{block}\nprint('gap')\n{block}\n"

        strict = QualityAnalyzer(QualityPolicy(min_duplicate_lines=3)).analyze(source, "m.py")
        lenient = QualityAnalyzer(QualityPolicy(min_duplicate_lines=20)).analyze(source, "m.py")

        self.assertIn(IssueCategory.DRY, _categories(strict))
        self.assertNotIn(IssueCategory.DRY, _categories(lenient))

    def test_srp_enforcement_can_be_switched_off(self):
        policy = QualityPolicy(max_class_methods=1, enforce_srp=False)

        report = QualityAnalyzer(policy).analyze(self._class_with(20), "m.py")

        self.assertNotIn(IssueCategory.SOLID_SRP, _categories(report))

    def test_dip_enforcement_can_be_switched_off(self):
        source = "class Holder:\n    def __init__(self):\n        self.dep = Service()\n"

        enabled = QualityAnalyzer(QualityPolicy()).analyze(source, "m.py")
        disabled = QualityAnalyzer(QualityPolicy(enforce_dip=False)).analyze(source, "m.py")

        self.assertIn(IssueCategory.SOLID_DIP, _categories(enabled))
        self.assertNotIn(IssueCategory.SOLID_DIP, _categories(disabled))


if __name__ == "__main__":
    unittest.main()
