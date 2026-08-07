"""Unit tests for the review gate.

The gate turns a review report into a pipeline decision. Two defects are pinned
here: a report the gate marks FAIL has to be distinguishable from a passing one
by something other than a string (F-01), and a report whose quality line is
missing must not be treated as a report scoring zero (F-10).
"""

import unittest

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.gate import ReviewGate, ReviewGateResult
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.severity import Severity

PASSING_REPORT = """
# 🏛️ Architectural Review Summary
## 🔒 Security Analysis
- **SAST Scan Result**: PASS - Low
## 🔗 Impact Analysis
- **Risk Assessment**: Low - nothing structural changed
## 📊 Code Quality
- **SOLID Compliance**: 88/100
"""

SAST_FAILING_REPORT = """
## 🔒 Security Analysis
- **SAST Scan Result**: FAIL - Critical
## 🔗 Impact Analysis
- **Risk Assessment**: Critical - hardcoded credentials added
## 📊 Code Quality
- **SOLID Compliance**: 90/100
"""

REPORT_WITHOUT_QUALITY_LINE = """
# 🏛️ Architectural Review Summary
The change looks reasonable. I did not compute a numeric quality score.
- **Risk Assessment**: Low - cosmetic only
"""


class TestReviewGate(unittest.TestCase):
    def setUp(self):
        self.gate = ReviewGate(ReviewPolicy())

    def test_clean_report_passes(self):
        evaluation = self.gate.evaluate(PASSING_REPORT)

        self.assertEqual(evaluation.result, ReviewGateResult.PASS)
        self.assertEqual(evaluation.exit_code, 0)
        self.assertEqual(evaluation.blocking_issues, [])

    def test_failed_sast_scan_fails_the_gate(self):
        evaluation = self.gate.evaluate(SAST_FAILING_REPORT)

        self.assertEqual(evaluation.result, ReviewGateResult.FAIL)
        self.assertEqual(evaluation.exit_code, 1)
        self.assertTrue(evaluation.blocking_issues)

    def test_sast_failure_is_recognised_in_the_format_the_agent_emits(self):
        """Regression for F-57.

        The prompt asks for `- **SAST Scan Result**: FAIL - Critical`, but the
        gate looked for the literal `SAST Scan Result: FAIL` without the
        emphasis markers, so a failed scan was never noticed. It only appeared
        to work because failing reports also carry a critical risk assessment.
        """
        report = """
## 🔒 Security Analysis
- **SAST Scan Result**: FAIL - Critical
## 🔗 Impact Analysis
- **Risk Assessment**: Low - see above
## 📊 Code Quality
- **SOLID Compliance**: 95/100
"""

        evaluation = self.gate.evaluate(report)

        self.assertEqual(evaluation.result, ReviewGateResult.FAIL)
        self.assertTrue(any("SAST Scan Failed" in reason for reason in evaluation.reasons))

    def test_sast_pass_is_not_read_as_a_failure(self):
        evaluation = self.gate.evaluate(PASSING_REPORT)

        self.assertFalse(any("SAST Scan Failed" in reason for reason in evaluation.reasons))

    def test_result_is_an_enum_not_a_string(self):
        """Regression for F-01.

        The orchestrator compared this value against the string "fail". The
        comparison was always false, so the blocking path was unreachable.
        """
        evaluation = self.gate.evaluate(SAST_FAILING_REPORT)

        self.assertIsInstance(evaluation.result, ReviewGateResult)
        self.assertNotEqual(evaluation.result, "fail")

    def test_low_quality_score_blocks(self):
        report = PASSING_REPORT.replace("88/100", "20/100")

        evaluation = self.gate.evaluate(report)

        self.assertEqual(evaluation.result, ReviewGateResult.FAIL)
        self.assertTrue(any("Quality Score" in issue for issue in evaluation.blocking_issues))

    def test_quality_score_between_thresholds_warns_without_blocking(self):
        # Default policy: threshold 60, hard-fail below 50.
        report = PASSING_REPORT.replace("88/100", "55/100")

        evaluation = self.gate.evaluate(report)

        self.assertEqual(evaluation.result, ReviewGateResult.WARN)
        self.assertEqual(evaluation.exit_code, 0)
        self.assertEqual(evaluation.blocking_issues, [])

    def test_missing_quality_line_is_unknown_not_zero(self):
        """Regression for F-10.

        A report without a "SOLID Compliance: n/100" line used to score 0,
        which is below every threshold, so any drift in the model's report
        formatting silently blocked the merge request.
        """
        evaluation = self.gate.evaluate(REPORT_WITHOUT_QUALITY_LINE)

        self.assertIsNone(evaluation.scores["quality"])
        self.assertEqual(evaluation.blocking_issues, [])
        self.assertNotEqual(evaluation.result, ReviewGateResult.FAIL)

    def test_missing_quality_line_is_reported_as_a_warning(self):
        evaluation = self.gate.evaluate(REPORT_WITHOUT_QUALITY_LINE)

        self.assertEqual(evaluation.result, ReviewGateResult.WARN)
        self.assertTrue(any("not reported" in reason.lower() for reason in evaluation.reasons))

    def test_critical_risk_blocks_when_policy_says_so(self):
        report = PASSING_REPORT.replace(
            "- **Risk Assessment**: Low - nothing structural changed",
            "- **Risk Assessment**: Critical - unsafe deserialisation introduced",
        )

        evaluation = self.gate.evaluate(report)

        self.assertEqual(evaluation.result, ReviewGateResult.FAIL)
        self.assertIn("Critical Risk Assessment", evaluation.blocking_issues)

    def test_breaking_changes_are_reported_without_blocking(self):
        report = PASSING_REPORT + "\n- **Breaking Changes**: Yes - removed public method\n"

        evaluation = self.gate.evaluate(report)

        self.assertEqual(evaluation.result, ReviewGateResult.WARN)
        self.assertIn("Breaking Changes Detected", evaluation.reasons)


class TestFindingsDriveTheDecision(unittest.TestCase):
    """Regression for F-32.

    The gate recovered a quality score and a risk level by running regular
    expressions over the model's prose, even though the analyzers had already
    computed both. The pipeline decision therefore rested on the model's
    formatting — F-57 was one instance of that fragility.
    """

    def setUp(self):
        self.gate = ReviewGate(ReviewPolicy())

    def _finding(self, severity, title="Command Injection", line=7):
        return Finding(
            category=FindingCategory.SECURITY,
            severity=severity,
            file_path="src/app.py",
            line_number=line,
            title=title,
            description="eval() executes arbitrary code",
            remediation="Use ast.literal_eval() for data parsing",
            cwe_id="CWE-95",
        )

    def test_a_critical_finding_blocks_however_clean_the_prose(self):
        evaluation = self.gate.evaluate(PASSING_REPORT, [self._finding(Severity.CRITICAL)])

        self.assertEqual(evaluation.result, ReviewGateResult.FAIL)
        self.assertTrue(evaluation.blocking_issues)

    def test_the_blocking_issue_names_the_location(self):
        evaluation = self.gate.evaluate(PASSING_REPORT, [self._finding(Severity.CRITICAL)])

        self.assertIn("src/app.py:7", evaluation.blocking_issues[0])

    def test_the_blocking_finding_is_returned_for_the_report(self):
        finding = self._finding(Severity.CRITICAL)

        evaluation = self.gate.evaluate(PASSING_REPORT, [finding])

        self.assertEqual(evaluation.blocking_findings, [finding])

    def test_unparseable_prose_with_clean_findings_passes(self):
        evaluation = self.gate.evaluate("The change looks fine to me.", [])

        self.assertEqual(evaluation.result, ReviewGateResult.PASS)

    def test_a_high_finding_warns_under_the_default_threshold(self):
        evaluation = self.gate.evaluate(PASSING_REPORT, [self._finding(Severity.HIGH)])

        self.assertEqual(evaluation.result, ReviewGateResult.WARN)
        self.assertEqual(evaluation.blocking_issues, [])

    def test_the_blocking_threshold_is_policy_driven(self):
        policy = ReviewPolicy()
        policy.gate.blocking_severity = "high"
        gate = ReviewGate(policy)

        evaluation = gate.evaluate(PASSING_REPORT, [self._finding(Severity.HIGH)])

        self.assertEqual(evaluation.result, ReviewGateResult.FAIL)

    def test_the_quality_score_is_computed_from_findings(self):
        evaluation = self.gate.evaluate(PASSING_REPORT, [self._finding(Severity.MEDIUM)])

        # One MEDIUM finding costs its weight, not the 88 the prose claims.
        self.assertEqual(evaluation.scores["quality"], 100 - Severity.MEDIUM.weight)

    def test_a_clean_analysis_scores_full_marks(self):
        evaluation = self.gate.evaluate("prose the parser cannot read", [])

        self.assertEqual(evaluation.scores["quality"], 100)

    def test_no_analysis_leaves_the_score_unknown(self):
        """`None` means the analysis did not run; `[]` means it ran and was
        clean. Only the first leaves the score unknown."""
        evaluation = self.gate.evaluate("prose the parser cannot read")

        self.assertIsNone(evaluation.scores["quality"])

    def test_enough_findings_drive_the_score_below_the_threshold(self):
        findings = [self._finding(Severity.MEDIUM, line=i) for i in range(12)]

        evaluation = self.gate.evaluate(PASSING_REPORT, findings)

        self.assertEqual(evaluation.result, ReviewGateResult.FAIL)

    def test_reasons_say_which_source_produced_them(self):
        evaluation = self.gate.evaluate(SAST_FAILING_REPORT, [self._finding(Severity.MEDIUM)])

        self.assertTrue(any(reason.startswith("[analysis]") for reason in evaluation.reasons))
        self.assertTrue(any(reason.startswith("[review]") for reason in evaluation.reasons))

    def test_prose_alone_cannot_block_when_findings_are_available(self):
        """A model that phrases its report alarmingly does not fail a build on
        its own; an analyzer finding does."""
        evaluation = self.gate.evaluate(SAST_FAILING_REPORT, [self._finding(Severity.LOW)])

        self.assertEqual(evaluation.result, ReviewGateResult.WARN)


class TestScoreFromFindings(unittest.TestCase):
    def test_no_findings_scores_one_hundred(self):
        self.assertEqual(ReviewGate.score_from_findings([]), 100)

    def test_the_score_never_goes_negative(self):
        findings = [
            Finding(
                category=FindingCategory.SECURITY,
                severity=Severity.CRITICAL,
                file_path="a.py",
                line_number=i,
                title="t",
                description="d",
                remediation="r",
            )
            for i in range(20)
        ]

        self.assertEqual(ReviewGate.score_from_findings(findings), 0)


if __name__ == "__main__":
    unittest.main()
