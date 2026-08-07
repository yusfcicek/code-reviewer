"""Unit tests for the static analysis suite.

The analyzers were only reachable as agent tools, so a model that answered
from the diff alone produced a review with no security scan behind it and
nothing said so. The suite runs them unconditionally and returns the shared
domain `Finding` type, which is what lets the gate decide from evidence
instead of from prose (finding F-32).
"""

import textwrap
import unittest

from code_reviewer.domain.finding import FindingCategory
from code_reviewer.domain.policy import QualityPolicy, ReviewPolicy
from code_reviewer.domain.severity import Severity
from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite

VULNERABLE = "def run(payload):\n    return eval(payload)\n"

CLEAN = "def add(left: int, right: int) -> int:\n    return left + right\n"


def _categories(findings):
    return {finding.category for finding in findings}


class TestSecurityFindings(unittest.TestCase):
    def setUp(self):
        self.suite = StaticAnalysisSuite()

    def test_an_eval_call_produces_a_critical_security_finding(self):
        findings = self.suite.analyze("src/app.py", VULNERABLE)

        security = [f for f in findings if f.category is FindingCategory.SECURITY]
        self.assertTrue(security)
        self.assertIs(security[0].severity, Severity.CRITICAL)

    def test_security_findings_carry_their_location(self):
        findings = self.suite.analyze("src/app.py", VULNERABLE)

        security = next(f for f in findings if f.category is FindingCategory.SECURITY)
        self.assertEqual(security.file_path, "src/app.py")
        self.assertEqual(security.line_number, 2)

    def test_security_findings_carry_the_cwe(self):
        findings = self.suite.analyze("src/app.py", VULNERABLE)

        security = next(f for f in findings if f.category is FindingCategory.SECURITY)
        self.assertTrue(security.cwe_id.startswith("CWE-"))

    def test_security_findings_carry_a_remediation(self):
        findings = self.suite.analyze("src/app.py", VULNERABLE)

        security = next(f for f in findings if f.category is FindingCategory.SECURITY)
        self.assertTrue(security.remediation)


class TestQualityFindings(unittest.TestCase):
    def test_an_empty_except_produces_a_quality_finding(self):
        source = "def run():\n    try:\n        work()\n    except ValueError:\n        pass\n"

        findings = StaticAnalysisSuite().analyze("src/app.py", source)

        self.assertIn(FindingCategory.QUALITY, _categories(findings))

    def test_the_suite_honours_the_quality_policy(self):
        policy = ReviewPolicy()
        policy.quality = QualityPolicy(max_class_methods=1)
        source = "class Narrow:\n    def one(self): pass\n    def two(self): pass\n"

        strict = StaticAnalysisSuite(policy).analyze("src/app.py", source)
        default = StaticAnalysisSuite().analyze("src/app.py", source)

        self.assertIn(FindingCategory.QUALITY, _categories(strict))
        self.assertNotIn(FindingCategory.QUALITY, _categories(default))


class TestPerformanceFindings(unittest.TestCase):
    def test_nested_loops_produce_a_performance_finding(self):
        source = textwrap.dedent(
            """
            def pairs(items):
                for a in items:
                    for b in items:
                        print(a, b)
            """
        )

        findings = StaticAnalysisSuite().analyze("src/app.py", source)

        self.assertIn(FindingCategory.PERFORMANCE, _categories(findings))


class TestSemanticFindings(unittest.TestCase):
    def test_a_removed_public_function_produces_a_semantic_finding(self):
        diff = "@@ -1,4 +1,1 @@\n-def public_api(value):\n-    return value\n"

        findings = StaticAnalysisSuite().analyze("src/app.py", "", diff=diff)

        self.assertIn(FindingCategory.SEMANTIC, _categories(findings))

    def test_semantic_analysis_is_skipped_without_a_diff(self):
        findings = StaticAnalysisSuite().analyze("src/app.py", CLEAN)

        self.assertNotIn(FindingCategory.SEMANTIC, _categories(findings))


class TestCleanAndBrokenInput(unittest.TestCase):
    def test_a_clean_file_produces_nothing(self):
        self.assertEqual(StaticAnalysisSuite().analyze("src/app.py", CLEAN), [])

    def test_unparseable_source_does_not_raise(self):
        findings = StaticAnalysisSuite().analyze("src/broken.py", "def (((\n")

        self.assertIsInstance(findings, list)

    def test_an_empty_file_produces_nothing(self):
        self.assertEqual(StaticAnalysisSuite().analyze("src/empty.py", ""), [])

    def test_a_non_python_file_is_still_scanned_for_secrets(self):
        findings = StaticAnalysisSuite().analyze("config/app.yml", 'api_key = "AKIAIOSFODNN7EXAMPLE"\n')

        self.assertIn(FindingCategory.SECURITY, _categories(findings))


class TestOrdering(unittest.TestCase):
    def test_findings_come_back_most_severe_first(self):
        source = VULNERABLE + "\nurl = 'http://example.com'\n"

        findings = StaticAnalysisSuite().analyze("src/app.py", source)

        severities = [finding.severity for finding in findings]
        self.assertEqual(severities, sorted(severities))


if __name__ == "__main__":
    unittest.main()
