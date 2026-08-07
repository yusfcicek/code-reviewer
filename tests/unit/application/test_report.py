"""Unit tests for the merge-request comment renderer.

The "Pipeline BLOCKED" header was unreachable, because the flag that selected it
was a string compared against an enum (finding F-01). Rendering is separated
from orchestration here so that both branches can be asserted directly.
"""

import unittest

from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.gate import GateEvaluation, ReviewGateResult
from code_reviewer.application.report import render_review_comment


def _evaluation(result, blocking=(), reasons=()):
    return GateEvaluation(
        result=result,
        exit_code=1 if result is ReviewGateResult.FAIL else 0,
        reasons=list(reasons),
        scores={"quality": 80},
        blocking_issues=list(blocking),
    )


class TestRenderReviewComment(unittest.TestCase):
    def test_passing_review_announces_a_pass(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.PASS))

        comment = render_review_comment("1.0", outcome, ["## Review for `a.py`\nfine"])

        self.assertIn("Pipeline PASSED", comment)
        self.assertNotIn("Pipeline BLOCKED", comment)

    def test_blocking_review_announces_the_block_and_lists_the_issues(self):
        outcome = ReviewOutcome()
        outcome.record("src/db.py", _evaluation(ReviewGateResult.FAIL, blocking=["SAST Scan Failed"]))

        comment = render_review_comment("1.0", outcome, ["## Review for `src/db.py`\nbad"])

        self.assertIn("Pipeline BLOCKED", comment)
        self.assertIn("src/db.py: SAST Scan Failed", comment)

    def test_warnings_are_surfaced_without_claiming_a_block(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.WARN, reasons=["Breaking Changes Detected"]))

        comment = render_review_comment("1.0", outcome, ["## Review for `a.py`\nhmm"])

        self.assertIn("Breaking Changes Detected", comment)
        self.assertNotIn("Pipeline BLOCKED", comment)

    def test_policy_version_and_file_count_are_reported(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.PASS))
        outcome.record_unevaluated("docs.md")

        comment = render_review_comment("2.3", outcome, ["## Review for `a.py`\nfine"])

        self.assertIn("Policy v2.3", comment)
        self.assertIn("2", comment)  # files considered

    def test_sections_are_included_verbatim(self):
        outcome = ReviewOutcome()

        comment = render_review_comment("1.0", outcome, ["SECTION-ONE", "SECTION-TWO"])

        self.assertIn("SECTION-ONE", comment)
        self.assertIn("SECTION-TWO", comment)


if __name__ == "__main__":
    unittest.main()
