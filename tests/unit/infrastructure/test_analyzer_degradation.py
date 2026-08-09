"""R-02 — an analyzer that crashes may not be a silent pass.

The suite catches each analyzer's exception and contributes nothing for it,
which is deliberate: a file that does not parse is a reason to say less rather
than to abort the review. What was missing is that it said *nothing at all* —
no log, no line in the comment, no field in the record. A security analyzer
that crashed on every file produced a clean report.
"""

import unittest
from unittest.mock import patch

from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite

SOURCE = "def handler(request):\n    return request\n"


class TestADegradedAnalyzerIsNamed(unittest.TestCase):
    def _result_with_broken(self, attribute: str):
        suite = StaticAnalysisSuite()
        broken = getattr(suite, attribute)
        with patch.object(broken, "analyze" if attribute != "_semantic" else "analyze_diff") as call:
            call.side_effect = RuntimeError("the analyzer exploded")
            return suite.analyze("src/app.py", SOURCE, diff="+ a line\n")

    def test_each_analyzer_reports_its_own_failure(self):
        for attribute, name in (
            ("_sast", "SASTAnalyzer"),
            ("_quality", "QualityAnalyzer"),
            ("_performance", "PerformanceAnalyzer"),
            ("_semantic", "SemanticChangeAnalyzer"),
        ):
            with self.subTest(analyzer=name):
                result = self._result_with_broken(attribute)

                self.assertEqual([item.analyzer for item in result.degraded], [name])
                self.assertIn("RuntimeError", result.degraded[0].reason)

    def test_a_healthy_run_reports_no_degradation(self):
        result = StaticAnalysisSuite().analyze("src/app.py", SOURCE, diff="+ a line\n")

        self.assertEqual(result.degraded, [])

    def test_the_failure_is_logged(self):
        with self.assertLogs("code_reviewer.infrastructure.analyzers.suite", level="WARNING") as logged:
            self._result_with_broken("_sast")

        # The name is a structured field rather than prose in the message,
        # because that is how the JSON format an aggregator reads carries it.
        self.assertEqual(logged.records[0].fields["analyzer"], "SASTAnalyzer")
        self.assertEqual(logged.records[0].fields["path"], "src/app.py")

    def test_the_other_analyzers_still_run(self):
        """Saying less, not aborting: the point of catching it at all."""
        result = self._result_with_broken("_sast")

        self.assertEqual(len(result.degraded), 1)

    def test_the_reason_names_the_exception_type(self):
        """'It failed' is not something anybody can act on."""
        result = self._result_with_broken("_quality")

        self.assertIn("the analyzer exploded", result.degraded[0].reason)


class TestItReachesTheReader(unittest.TestCase):
    """A field on a result object nobody renders is not an improvement."""

    def _review(self, degraded):
        from unittest.mock import MagicMock

        from code_reviewer.application.governance import DecisionRecorder
        from code_reviewer.application.ports import FileChange
        from code_reviewer.application.review_service import ReviewService
        from code_reviewer.domain.policy import ReviewPolicy
        from code_reviewer.domain.provenance import RunIdentity
        from code_reviewer.domain.suppression import DegradedAnalyzer, SuppressionResult
        from code_reviewer.domain.triage import ReviewTriage
        from tests.unit.application.test_review_service import (
            CLEAN_REVIEW,
            FakeForge,
            ScriptedReviewer,
            _significant_diff,
        )

        class BrokenAnalysis:
            def analyze(self, file_path, content, diff=""):
                return SuppressionResult(
                    degraded=[DegradedAnalyzer(analyzer=name, reason=reason) for name, reason in degraded]
                )

        forge = FakeForge([FileChange("src/app.py", _significant_diff())])
        policy = ReviewPolicy()
        sink = MagicMock()
        service = ReviewService(
            forge=forge,
            reviewer=ScriptedReviewer(CLEAN_REVIEW),
            triage=ReviewTriage(policy),
            policy=policy,
            analysis=BrokenAnalysis(),
            recorder=DecisionRecorder(sink, RunIdentity(package_version="2.14.0", policy_version="1.0")),
        )
        result = service.review(1, 2)
        return result, forge, sink

    def test_the_comment_names_the_analyzer_that_did_not_run(self):
        _, forge, _ = self._review([("SASTAnalyzer", "SyntaxError: invalid syntax")])

        self.assertIn("SASTAnalyzer", forge.published[0])
        self.assertIn("src/app.py", forge.published[0])

    def test_the_record_carries_it(self):
        """An auditor reading "no findings" deserves to know one analyzer was
        not among the things that found nothing."""
        _, _, sink = self._review([("QualityAnalyzer", "RecursionError: too deep")])

        written = sink.write.call_args[0][0]
        self.assertTrue(any("QualityAnalyzer" in warning for warning in written.warnings))

    def test_the_verdict_is_unchanged(self):
        """Deliberate: the common cause is a file that does not parse, and a
        half-finished branch is a reason to say less rather than to block. The
        knowledge that it happened is what was missing, not a block."""
        result, _, _ = self._review([("SASTAnalyzer", "SyntaxError: invalid syntax")])

        self.assertEqual(result.exit_code, 0)

    def test_a_healthy_review_says_nothing_about_analyzers(self):
        _, forge, _ = self._review([])

        self.assertNotIn("could not run", forge.published[0])
