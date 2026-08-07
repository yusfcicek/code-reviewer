"""Unit tests for the review gate.

The gate turns a review report into a pipeline decision. Two defects are pinned
here: a report the gate marks FAIL has to be distinguishable from a passing one
by something other than a string (F-01), and a report whose quality line is
missing must not be treated as a report scoring zero (F-10).
"""

import unittest

from code_reviewer.infrastructure.config.loader import ReviewPolicy
from code_reviewer.domain.gate import ReviewGate, ReviewGateResult

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


if __name__ == "__main__":
    unittest.main()
