"""Unit tests for the SAST analyzer.

Two defects are pinned here: a deserialisation rule whose negative lookahead
could not exclude anything, so safe calls were reported alongside unsafe ones
(F-06), and report ordering that sorted severities alphabetically, putting
`info` and `low` ahead of `medium` (F-07).
"""

import unittest

from code_reviewer.infrastructure.analyzers.sast import (
    SASTAnalyzer,
    Severity,
    VulnerabilityType,
    run_sast_scan,
)


def _types(report):
    return {finding.vulnerability_type for finding in report.findings}


class TestDeserialisationRules(unittest.TestCase):
    def setUp(self):
        self.analyzer = SASTAnalyzer()

    def test_unsafe_yaml_load_is_reported(self):
        report = self.analyzer.analyze("data = yaml.load(handle)\n", "config.py")

        self.assertIn(VulnerabilityType.INSECURE_DESERIALIZATION, _types(report))

    def test_safe_load_is_not_reported(self):
        """Regression for F-06."""
        report = self.analyzer.analyze("data = yaml.safe_load(handle)\n", "config.py")

        self.assertNotIn(VulnerabilityType.INSECURE_DESERIALIZATION, _types(report))

    def test_explicit_safe_loader_is_not_reported(self):
        """Regression for F-06."""
        report = self.analyzer.analyze(
            "data = yaml.load(handle, Loader=yaml.SafeLoader)\n", "config.py"
        )

        self.assertNotIn(VulnerabilityType.INSECURE_DESERIALIZATION, _types(report))

    def test_pickle_loads_is_reported(self):
        report = self.analyzer.analyze("obj = pickle.loads(blob)\n", "cache.py")

        self.assertIn(VulnerabilityType.INSECURE_DESERIALIZATION, _types(report))


class TestInjectionRules(unittest.TestCase):
    def setUp(self):
        self.analyzer = SASTAnalyzer()

    def test_eval_is_critical(self):
        report = self.analyzer.analyze("result = eval(user_input)\n", "app.py")

        findings = [f for f in report.findings if f.vulnerability_type is VulnerabilityType.COMMAND_INJECTION]
        self.assertTrue(findings)
        self.assertEqual(findings[0].severity, Severity.CRITICAL)
        self.assertEqual(findings[0].cwe_id, "CWE-95")

    def test_string_concatenated_sql_is_reported(self):
        report = self.analyzer.analyze(
            'cursor.execute("SELECT * FROM t WHERE id=" + user_id)\n', "db.py"
        )

        self.assertIn(VulnerabilityType.SQL_INJECTION, _types(report))

    def test_shell_true_is_reported(self):
        report = self.analyzer.analyze("subprocess.run(cmd, shell=True)\n", "run.py")

        self.assertIn(VulnerabilityType.COMMAND_INJECTION, _types(report))

    def test_comments_are_not_scanned(self):
        report = self.analyzer.analyze("# result = eval(user_input)\n", "app.py")

        self.assertEqual(report.findings, [])


class TestSecretRules(unittest.TestCase):
    def test_hardcoded_password_is_reported_with_its_line(self):
        report = SASTAnalyzer().analyze('\n\npassword = "hunter22"\n', "settings.py")

        findings = [f for f in report.findings if f.vulnerability_type is VulnerabilityType.HARDCODED_SECRET]
        self.assertTrue(findings)
        self.assertEqual(findings[0].line_number, 3)

    def test_private_key_block_is_critical(self):
        report = SASTAnalyzer().analyze("KEY = '-----BEGIN RSA PRIVATE KEY-----'\n", "keys.py")

        severities = {f.severity for f in report.findings}
        self.assertIn(Severity.CRITICAL, severities)


class TestRiskScore(unittest.TestCase):
    def setUp(self):
        self.analyzer = SASTAnalyzer()

    def test_clean_file_is_safe(self):
        score = self.analyzer.calculate_risk_score([])

        self.assertEqual(score.risk_level, "safe")
        self.assertEqual(score.total_score, 0)

    def test_any_critical_finding_makes_the_file_critical(self):
        report = self.analyzer.analyze("eval(x)\n", "app.py")

        self.assertEqual(report.risk_score.risk_level, "critical")

    def test_score_is_capped_at_one_hundred(self):
        content = "\n".join("eval(x)" for _ in range(20))
        report = self.analyzer.analyze(content, "app.py")

        self.assertLessEqual(report.risk_score.total_score, 100)


class TestSeverityOrdering(unittest.TestCase):
    def test_severities_have_an_explicit_rank(self):
        self.assertLess(Severity.CRITICAL.rank, Severity.HIGH.rank)
        self.assertLess(Severity.HIGH.rank, Severity.MEDIUM.rank)
        self.assertLess(Severity.MEDIUM.rank, Severity.LOW.rank)
        self.assertLess(Severity.LOW.rank, Severity.INFO.rank)

    def test_report_lists_critical_findings_before_low_ones(self):
        """Regression for F-07.

        Sorting on `severity.value` is alphabetical: critical < high < info <
        low < medium. The truncation to 15 findings then dropped severe items
        in favour of trivial ones.
        """
        content = "url = 'http://example.com'\nresult = eval(payload)\n"

        rendered = run_sast_scan(content, "app.py")

        # The summary lists vulnerability types as an unordered set; only the
        # detailed section is ordered by severity.
        details = rendered.split("### Security Findings:")[1]
        self.assertLess(details.index("command_injection"), details.index("insecure_http"))


class TestLanguageSelection(unittest.TestCase):
    def test_cpp_rules_apply_to_cpp_files(self):
        report = SASTAnalyzer().analyze("char buf[8]; gets(buf);\n", "main.cpp")

        self.assertTrue(report.findings)
        self.assertIn(Severity.CRITICAL, {f.severity for f in report.findings})

    def test_python_rules_do_not_apply_to_cpp_files(self):
        report = SASTAnalyzer().analyze("data = yaml.load(handle)\n", "main.cpp")

        self.assertNotIn(VulnerabilityType.INSECURE_DESERIALIZATION, _types(report))


if __name__ == "__main__":
    unittest.main()
