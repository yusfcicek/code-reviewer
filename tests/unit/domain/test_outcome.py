"""Unit tests for the merge-request-level review outcome.

The orchestrator used to track the overall verdict in a string that it compared
against ``gate_eval.result`` — a ``ReviewGateResult`` enum. The comparison was
always false, so a failing gate never escalated, the "Pipeline BLOCKED" header
was unreachable and the non-zero exit was dead code (finding F-01).

``ReviewOutcome`` replaces that string. Enums go in, an enum comes out, and
there is no representation in which the mistake can be repeated silently.
"""

import unittest

from code_reviewer.infrastructure.config.loader import ReviewPolicy
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.gate import GateEvaluation, ReviewGateResult


def _evaluation(result, blocking=(), reasons=()):
    return GateEvaluation(
        result=result,
        exit_code=1 if result is ReviewGateResult.FAIL else 0,
        reasons=list(reasons),
        scores={"quality": 80},
        blocking_issues=list(blocking),
    )


class TestReviewOutcome(unittest.TestCase):
    def test_empty_outcome_passes(self):
        outcome = ReviewOutcome()

        self.assertEqual(outcome.result, ReviewGateResult.PASS)
        self.assertFalse(outcome.is_blocking)
        self.assertEqual(outcome.blocking_issues, [])

    def test_all_passing_files_pass(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.PASS))
        outcome.record("b.py", _evaluation(ReviewGateResult.PASS))

        self.assertEqual(outcome.result, ReviewGateResult.PASS)
        self.assertFalse(outcome.is_blocking)

    def test_one_failing_file_fails_the_whole_review(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.PASS))
        outcome.record("b.py", _evaluation(ReviewGateResult.FAIL, blocking=["SAST Scan Failed"]))

        self.assertEqual(outcome.result, ReviewGateResult.FAIL)
        self.assertTrue(outcome.is_blocking)

    def test_warnings_do_not_block(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.WARN, reasons=["Breaking Changes Detected"]))

        self.assertEqual(outcome.result, ReviewGateResult.WARN)
        self.assertFalse(outcome.is_blocking)

    def test_blocking_issues_are_attributed_to_their_file(self):
        outcome = ReviewOutcome()
        outcome.record("src/db.py", _evaluation(ReviewGateResult.FAIL, blocking=["SAST Scan Failed"]))

        self.assertEqual(outcome.blocking_issues, ["src/db.py: SAST Scan Failed"])

    def test_exit_code_is_non_zero_when_policy_blocks_on_critical(self):
        policy = ReviewPolicy()
        policy.gate.fail_pipeline_on_critical = True

        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.FAIL, blocking=["SAST Scan Failed"]))

        self.assertEqual(outcome.exit_code(policy), 1)

    def test_exit_code_is_zero_when_policy_does_not_block(self):
        policy = ReviewPolicy()
        policy.gate.fail_pipeline_on_critical = False

        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.FAIL, blocking=["SAST Scan Failed"]))

        self.assertEqual(outcome.exit_code(policy), 0)

    def test_files_without_a_gate_evaluation_are_counted_but_neutral(self):
        """Auto-approved files never reach the gate; they must not skew the verdict."""
        outcome = ReviewOutcome()
        outcome.record_unevaluated("docs.py")

        self.assertEqual(outcome.result, ReviewGateResult.PASS)
        self.assertEqual(outcome.files_considered, 1)


if __name__ == "__main__":
    unittest.main()
