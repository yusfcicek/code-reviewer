"""Step 6 — the workflow writes a record of what it decided.

The record is written from what the review already produced. No second pass, no
re-analysis, no extra model call: anything it cannot get from the outcome, the
findings and the identity is a thing this level does not claim (decision D-6).
"""

import json
import unittest

from code_reviewer.application.governance import AuditSink, DecisionRecorder
from code_reviewer.application.ports import FileChange
from code_reviewer.application.review_service import ReviewService
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.provenance import RunIdentity
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.triage import ReviewTriage

from .test_review_service import (
    CLEAN_REVIEW,
    FakeForge,
    RecordingAnalysis,
    ScriptedReviewer,
    _significant_diff,
)

IDENTITY = RunIdentity(
    package_version="2.14.0",
    policy_version="1.0",
    model="qwen3-8b",
    prompt_fingerprint="b6b17025f0c5",
)


def _finding(severity=Severity.CRITICAL, rule_id="SAST.COMMAND_INJECTION") -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path="src/app.py",
        line_number=4,
        title="Command Injection",
        description="eval() executes arbitrary code",
        remediation="Use ast.literal_eval()",
        rule_id=rule_id,
        cwe_id="CWE-95",
    )


class CollectingSink(AuditSink):
    def __init__(self):
        self.written = []

    def write(self, record):
        self.written.append(record)


class BrokenSink(AuditSink):
    def write(self, record):
        raise OSError("read-only file system")


def _service(forge, recorder, policy=None, findings=()):
    policy = policy or ReviewPolicy()
    return ReviewService(
        forge=forge,
        reviewer=ScriptedReviewer(CLEAN_REVIEW),
        triage=ReviewTriage(policy),
        policy=policy,
        analysis=RecordingAnalysis(list(findings)),
        recorder=recorder,
    )


def _forge():
    return FakeForge([FileChange("src/app.py", _significant_diff())])


class TestTheRecordIsWritten(unittest.TestCase):
    def test_a_blocking_review_writes_a_record_naming_the_analyzer(self):
        sink = CollectingSink()

        _service(_forge(), DecisionRecorder(sink, IDENTITY), findings=[_finding()]).review(1, 2)

        record = sink.written[0]
        self.assertEqual(record.verdict, "fail")
        self.assertEqual(record.deciders, ("analyzer:SASTAnalyzer@2.14.0",))

    def test_a_passing_review_writes_one_too(self):
        """A record only written when something blocked would make "no record"
        ambiguous between "it passed" and "nobody ran it"."""
        sink = CollectingSink()

        _service(_forge(), DecisionRecorder(sink, IDENTITY)).review(1, 2)

        self.assertEqual(len(sink.written), 1)
        self.assertEqual(sink.written[0].verdict, "pass")

    def test_the_record_carries_the_merge_request_it_was_about(self):
        sink = CollectingSink()

        _service(_forge(), DecisionRecorder(sink, IDENTITY)).review(7, 42)

        self.assertEqual(sink.written[0].project, "7")
        self.assertEqual(sink.written[0].merge_request, "42")

    def test_the_exit_code_in_the_record_is_the_one_the_run_returns(self):
        sink = CollectingSink()
        finding = _finding(Severity.CRITICAL)

        result = _service(_forge(), DecisionRecorder(sink, IDENTITY), findings=[finding]).review(1, 2)

        self.assertEqual(sink.written[0].exit_code, result.exit_code)

    def test_a_review_with_no_changes_records_nothing(self):
        """Nothing was decided, so there is nothing to be accountable for."""
        sink = CollectingSink()

        _service(FakeForge([]), DecisionRecorder(sink, IDENTITY)).review(1, 2)

        self.assertEqual(sink.written, [])


class TestTheCommentSaysTheSameThing(unittest.TestCase):
    def test_the_comment_carries_the_identity(self):
        forge = _forge()

        _service(forge, DecisionRecorder(CollectingSink(), IDENTITY)).review(1, 2)

        self.assertIn("b6b17025f0c5", forge.published[0])
        self.assertIn("qwen3-8b", forge.published[0])

    def test_the_comment_names_what_decided(self):
        forge = _forge()

        _service(forge, DecisionRecorder(CollectingSink(), IDENTITY), findings=[_finding()]).review(1, 2)

        self.assertIn("analyzer:SASTAnalyzer@2.14.0", forge.published[0])

    def test_without_a_recorder_the_comment_is_what_it_was_before(self):
        forge = _forge()

        _service(forge, None).review(1, 2)

        self.assertNotIn("Accountability", forge.published[0])


class TestRecordingNeverCostsTheReview(unittest.TestCase):
    def test_a_sink_that_cannot_write_does_not_change_the_verdict(self):
        """Fifth level with the same rule: observability may not fail the
        review it observes."""
        forge = _forge()

        result = _service(forge, DecisionRecorder(BrokenSink(), IDENTITY), findings=[_finding()]).review(1, 2)

        self.assertEqual(result.exit_code, 1)
        self.assertTrue(forge.published)


class TestAnUnattributableFindingCannotBlockSilently(unittest.TestCase):
    def test_a_blocking_finding_with_no_rule_id_is_recorded_as_incomplete(self):
        """Fail-closed. A claim nobody can attribute is an opinion, and a
        record saying so is more honest than one asserting an analyzer decided.
        The verdict itself is untouched: the record follows the review, never
        the other way round."""
        sink = CollectingSink()

        result = _service(_forge(), DecisionRecorder(sink, IDENTITY), findings=[_finding(rule_id="")]).review(
            1, 2
        )

        self.assertEqual(result.exit_code, 1)
        self.assertFalse(sink.written[0].completed)
        self.assertIn("may not rest on a model's opinion", sink.written[0].failure_reason)


class TestWhatTheReviewCost(unittest.TestCase):
    """Contract C-7 — cost recorded alongside the decision it paid for.

    The metrics file is overwritten by the next review; the record is not.
    """

    class _CountingReviewer(ScriptedReviewer):
        def __init__(self):
            super().__init__(CLEAN_REVIEW)
            from code_reviewer.application.orchestration_service import AgentTotals
            from code_reviewer.domain.orchestration import Specialism

            self.agent_totals = {
                Specialism.SECURITY: AgentTotals(
                    runs=2, failures=1, tool_calls=5, tokens_allowed=4000, duration_ms=120
                )
            }

    def _service_with(self, forge, recorder):
        policy = ReviewPolicy()
        return ReviewService(
            forge=forge,
            reviewer=self._CountingReviewer(),
            triage=ReviewTriage(policy),
            policy=policy,
            analysis=RecordingAnalysis([]),
            recorder=recorder,
        )

    def test_each_specialists_totals_reach_the_record(self):
        sink = CollectingSink()

        self._service_with(_forge(), DecisionRecorder(sink, IDENTITY)).review(1, 2)

        cost = sink.written[0].agent_costs
        self.assertEqual([item.agent for item in cost], ["security"])
        self.assertEqual(cost[0].tool_calls, 5)
        self.assertEqual(cost[0].failures, 1)
        self.assertEqual(cost[0].tokens_allowed, 4000)

    def test_a_reviewer_that_counts_nothing_records_no_cost(self):
        """One agent, or none: an empty tuple is a fact, not a gap."""
        sink = CollectingSink()

        _service(_forge(), DecisionRecorder(sink, IDENTITY)).review(1, 2)

        self.assertEqual(sink.written[0].agent_costs, ())


class TestWhatWasSuggested(unittest.TestCase):
    """Contract C-8 — a suggestion offered is part of what was decided.

    Identifiers only: rule, location, recipe. Never the replacement text —
    it is derived from the file under review, and five levels have kept that
    out of the artefacts.
    """

    SOURCE = "import hashlib\n\n\ndef digest(value):\n    return hashlib.md5(value).hexdigest()\n"

    def _review(self):
        from code_reviewer.application.ports import FileChange as Change

        forge = FakeForge([Change("src/hashing.py", _significant_diff())], {"src/hashing.py": self.SOURCE})
        sink = CollectingSink()
        policy = ReviewPolicy()
        finding = Finding(
            category=FindingCategory.SECURITY,
            severity=Severity.MEDIUM,
            file_path="src/hashing.py",
            line_number=5,
            title="Weak Crypto",
            description="MD5 is broken",
            remediation="Use SHA-256",
            rule_id="SAST.WEAK_CRYPTO",
        )
        ReviewService(
            forge=forge,
            reviewer=ScriptedReviewer(CLEAN_REVIEW),
            triage=ReviewTriage(policy),
            policy=policy,
            analysis=RecordingAnalysis([finding]),
            recorder=DecisionRecorder(sink, IDENTITY),
        ).review(1, 2)
        return sink.written[0]

    def test_the_record_names_the_rule_the_location_and_the_recipe(self):
        record = self._review()

        assert len(record.suggestions) == 1
        self.assertEqual(record.suggestions[0].rule_id, "SAST.WEAK_CRYPTO")
        self.assertEqual(record.suggestions[0].location, "src/hashing.py:5")
        self.assertEqual(record.suggestions[0].recipe, "md5-to-sha256")

    def test_the_replacement_text_is_not_in_the_record(self):
        from code_reviewer.infrastructure.governance.json_sink import to_json

        written = json.dumps(to_json(self._review()), sort_keys=True)

        self.assertNotIn("sha256(value)", written)
