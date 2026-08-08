"""Unit tests for the static analysis suite.

The analyzers were only reachable as agent tools, so a model that answered
from the diff alone produced a review with no security scan behind it and
nothing said so. The suite runs them unconditionally and returns the shared
domain `Finding` type, which is what lets the gate decide from evidence
instead of from prose (finding F-32).
"""

import textwrap
import unittest

from code_reviewer.domain.finding import Finding, FindingCategory
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
        findings = self.suite.analyze("src/app.py", VULNERABLE).findings

        security = [f for f in findings if f.category is FindingCategory.SECURITY]
        self.assertTrue(security)
        self.assertIs(security[0].severity, Severity.CRITICAL)

    def test_security_findings_carry_their_location(self):
        findings = self.suite.analyze("src/app.py", VULNERABLE).findings

        security = next(f for f in findings if f.category is FindingCategory.SECURITY)
        self.assertEqual(security.file_path, "src/app.py")
        self.assertEqual(security.line_number, 2)

    def test_security_findings_carry_the_cwe(self):
        findings = self.suite.analyze("src/app.py", VULNERABLE).findings

        security = next(f for f in findings if f.category is FindingCategory.SECURITY)
        self.assertTrue(security.cwe_id.startswith("CWE-"))

    def test_security_findings_carry_a_remediation(self):
        findings = self.suite.analyze("src/app.py", VULNERABLE).findings

        security = next(f for f in findings if f.category is FindingCategory.SECURITY)
        self.assertTrue(security.remediation)


class TestQualityFindings(unittest.TestCase):
    def test_an_empty_except_produces_a_quality_finding(self):
        source = "def run():\n    try:\n        work()\n    except ValueError:\n        pass\n"

        findings = StaticAnalysisSuite().analyze("src/app.py", source).findings

        self.assertIn(FindingCategory.QUALITY, _categories(findings))

    def test_the_suite_honours_the_quality_policy(self):
        policy = ReviewPolicy()
        policy.quality = QualityPolicy(max_class_methods=1)
        source = "class Narrow:\n    def one(self): pass\n    def two(self): pass\n"

        strict = StaticAnalysisSuite(policy).analyze("src/app.py", source).findings
        default = StaticAnalysisSuite().analyze("src/app.py", source).findings

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

        findings = StaticAnalysisSuite().analyze("src/app.py", source).findings

        self.assertIn(FindingCategory.PERFORMANCE, _categories(findings))


class TestSemanticFindings(unittest.TestCase):
    def test_a_removed_public_function_produces_a_semantic_finding(self):
        diff = "@@ -1,4 +1,1 @@\n-def public_api(value):\n-    return value\n"

        findings = StaticAnalysisSuite().analyze("src/app.py", "", diff=diff).findings

        self.assertIn(FindingCategory.SEMANTIC, _categories(findings))

    def test_semantic_analysis_is_skipped_without_a_diff(self):
        findings = StaticAnalysisSuite().analyze("src/app.py", CLEAN).findings

        self.assertNotIn(FindingCategory.SEMANTIC, _categories(findings))


class TestCleanAndBrokenInput(unittest.TestCase):
    def test_a_clean_file_produces_nothing(self):
        self.assertEqual(StaticAnalysisSuite().analyze("src/app.py", CLEAN).findings, [])

    def test_unparseable_source_does_not_raise(self):
        findings = StaticAnalysisSuite().analyze("src/broken.py", "def (((\n").findings

        self.assertIsInstance(findings, list)

    def test_an_empty_file_produces_nothing(self):
        self.assertEqual(StaticAnalysisSuite().analyze("src/empty.py", "").findings, [])

    def test_a_non_python_file_is_still_scanned_for_secrets(self):
        findings = (
            StaticAnalysisSuite().analyze("config/app.yml", 'api_key = "AKIAIOSFODNN7EXAMPLE"\n').findings
        )

        self.assertIn(FindingCategory.SECURITY, _categories(findings))


class TestOrdering(unittest.TestCase):
    def test_findings_come_back_most_severe_first(self):
        source = VULNERABLE + "\nurl = 'http://example.com'\n"

        findings = StaticAnalysisSuite().analyze("src/app.py", source).findings

        severities = [finding.severity for finding in findings]
        self.assertEqual(severities, sorted(severities))


if __name__ == "__main__":
    unittest.main()


class TestRuleIdsAreNamespaced(unittest.TestCase):
    """A bare id has no namespace for a suppression glob to match (G-08).

    The namespace is added here rather than inside the analyzers: this class is
    already the anti-corruption layer that translates five private vocabularies
    into one domain type, and the namespace is part of that translation
    (decision D-1).
    """

    SOURCE = textwrap.dedent(
        """
        import sqlite3

        class Handler:
            def run(self, name, rows):
                query = "SELECT * FROM users WHERE name = '" + name + "'"
                cursor = sqlite3.connect("db").cursor()
                cursor.execute(query)
                for row in rows:
                    for other in rows:
                        cursor.execute("SELECT 1")
                return query
        """
    ).strip()

    def setUp(self):
        self.findings = StaticAnalysisSuite(ReviewPolicy()).analyze("app.py", self.SOURCE).findings

    def test_the_source_produces_something_to_check(self):
        self.assertTrue(self.findings, "the fixture stopped triggering any analyzer")

    def test_every_rule_id_carries_a_namespace(self):
        unnamespaced = [f.rule_id for f in self.findings if not f.namespace]

        self.assertEqual(unnamespaced, [], f"un-namespaced rule ids: {unnamespaced}")

    def test_every_namespace_is_one_of_the_declared_ones(self):
        declared = {"SAST", "QUALITY", "PERFORMANCE", "SEMANTIC"}
        seen = {f.namespace for f in self.findings}

        self.assertTrue(seen <= declared, f"unexpected namespaces: {seen - declared}")

    def test_the_namespace_matches_the_category(self):
        expected = {
            FindingCategory.SECURITY: "SAST",
            FindingCategory.QUALITY: "QUALITY",
            FindingCategory.PERFORMANCE: "PERFORMANCE",
            FindingCategory.SEMANTIC: "SEMANTIC",
        }

        for finding in self.findings:
            with self.subTest(rule=finding.rule_id):
                self.assertEqual(finding.namespace, expected[finding.category])

    def test_rule_ids_are_upper_case(self):
        """So `SAST.*` reads the same way in a policy file and in a report."""
        for finding in self.findings:
            with self.subTest(rule=finding.rule_id):
                self.assertEqual(finding.rule_id, finding.rule_id.upper())


class TestDeduplication(unittest.TestCase):
    """One problem at one place under one rule is one finding.

    Found against a live model: a database cursor reported both as "used
    without `with`" and as "may not be properly closed" — one line, one rule,
    two findings. Duplicates are noise in the report and they inflate the
    per-severity counts the metrics export and the quality score are computed
    from (G-08).
    """

    @staticmethod
    def _finding(rule="SAST.X", line=10, severity=Severity.MEDIUM, description="a"):
        return Finding(
            category=FindingCategory.SECURITY,
            severity=severity,
            file_path="app.py",
            line_number=line,
            title="T",
            description=description,
            remediation="fix",
            rule_id=rule,
        )

    def test_the_same_rule_at_the_same_line_collapses(self):
        pair = [
            self._finding(description="used without 'with'"),
            self._finding(description="may not be properly closed"),
        ]

        self.assertEqual(len(StaticAnalysisSuite.deduplicate(pair)), 1)

    def test_the_more_severe_report_survives(self):
        pair = [
            self._finding(severity=Severity.LOW),
            self._finding(severity=Severity.CRITICAL),
        ]

        self.assertEqual(StaticAnalysisSuite.deduplicate(pair)[0].severity, Severity.CRITICAL)

    def test_severity_order_within_the_pair_does_not_matter(self):
        first = [self._finding(severity=Severity.CRITICAL), self._finding(severity=Severity.LOW)]

        self.assertEqual(StaticAnalysisSuite.deduplicate(first)[0].severity, Severity.CRITICAL)

    def test_on_a_tie_the_first_report_wins(self):
        pair = [self._finding(description="first"), self._finding(description="second")]

        self.assertEqual(StaticAnalysisSuite.deduplicate(pair)[0].description, "first")

    def test_different_lines_both_survive(self):
        pair = [self._finding(line=10), self._finding(line=11)]

        self.assertEqual(len(StaticAnalysisSuite.deduplicate(pair)), 2)

    def test_different_rules_both_survive(self):
        pair = [self._finding(rule="SAST.X"), self._finding(rule="SAST.Y")]

        self.assertEqual(len(StaticAnalysisSuite.deduplicate(pair)), 2)

    def test_different_files_both_survive(self):
        other = Finding(
            category=FindingCategory.SECURITY,
            severity=Severity.MEDIUM,
            file_path="other.py",
            line_number=10,
            title="T",
            description="a",
            remediation="fix",
            rule_id="SAST.X",
        )

        self.assertEqual(len(StaticAnalysisSuite.deduplicate([self._finding(), other])), 2)

    def test_an_empty_input_is_handled(self):
        self.assertEqual(StaticAnalysisSuite.deduplicate([]), [])

    def test_the_suite_returns_deduplicated_findings_most_severe_first(self):
        findings = (
            StaticAnalysisSuite(ReviewPolicy()).analyze("app.py", TestRuleIdsAreNamespaced.SOURCE).findings
        )

        keys = [(f.rule_id, f.file_path, f.line_number) for f in findings]
        self.assertEqual(len(keys), len(set(keys)), "the suite returned a duplicate")
        self.assertEqual(findings, sorted(findings), "the suite stopped sorting")


class TestSuppression(unittest.TestCase):
    """What the suite was told to ignore comes back alongside what it found.

    Dropping the suppressed ones would make a silenced rule and an inert rule
    look identical from the outside, which is the state suppression exists to
    avoid creating (finding G-07).
    """

    SOURCE = textwrap.dedent(
        """
        import subprocess

        def run(name):
            # review-ignore: SAST.COMMAND_INJECTION - name comes from an enum
            subprocess.call("ls " + name, shell=True)
        """
    ).strip()

    def setUp(self):
        self.result = StaticAnalysisSuite(ReviewPolicy()).analyze("app.py", self.SOURCE)

    def test_the_suppressed_finding_is_absent_from_the_findings(self):
        rules = {finding.rule_id for finding in self.result.findings}

        self.assertNotIn("SAST.COMMAND_INJECTION", rules)

    def test_the_suppressed_finding_is_present_in_the_record(self):
        rules = {item.finding.rule_id for item in self.result.suppressed}

        self.assertIn("SAST.COMMAND_INJECTION", rules)

    def test_the_reason_travels_with_it(self):
        reasons = {item.directive.reason for item in self.result.suppressed}

        self.assertIn("name comes from an enum", reasons)

    def test_the_count_is_available(self):
        self.assertGreaterEqual(self.result.suppressed_count, 1)

    def test_a_file_without_directives_suppresses_nothing(self):
        result = StaticAnalysisSuite(ReviewPolicy()).analyze(
            "app.py", 'import subprocess\nsubprocess.call("ls", shell=True)\n'
        )

        self.assertEqual(result.suppressed, [])

    def test_suppression_happens_after_deduplication(self):
        """One directive silences one finding, not a duplicate pair.

        Suppressing first would leave the duplicate behind and make the count
        report two silences where the author wrote one.
        """
        pair = [
            TestDeduplication._finding(description="first"),
            TestDeduplication._finding(description="second"),
        ]
        deduplicated = StaticAnalysisSuite.deduplicate(pair)

        self.assertEqual(len(deduplicated), 1)

    def test_the_findings_are_still_sorted(self):
        result = StaticAnalysisSuite(ReviewPolicy()).analyze("app.py", TestRuleIdsAreNamespaced.SOURCE)

        self.assertEqual(result.findings, sorted(result.findings))

    def test_an_empty_analysis_still_returns_a_result(self):
        result = StaticAnalysisSuite(ReviewPolicy()).analyze("app.py", "")

        self.assertEqual(result.findings, [])
        self.assertEqual(result.suppressed, [])
