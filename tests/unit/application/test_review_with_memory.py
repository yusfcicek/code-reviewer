"""Step 6 — memory in the workflow, and the verdict that does not move."""

import unittest
from datetime import date, timedelta

from code_reviewer.application.ports import CodeForge, FileChange, MemoryStore, MergeRequestRef, Reviewer
from code_reviewer.application.project_memory import ProjectMemory
from code_reviewer.application.review_service import ReviewService
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.recollection import Recollection, RecollectionKind
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import SuppressedFinding, SuppressionDirective, SuppressionResult
from code_reviewer.domain.triage import ReviewTriage

TODAY = date(2026, 8, 9)
PATH = "storage/repository.py"
DIFF = "\n".join(
    [
        "@@ -1,4 +1,10 @@",
        "+def find(connection, name):",
        "+    query = 'SELECT * FROM users WHERE name = ' + name",
        "+    return connection.execute(query)",
        "+    # padding to make this a substantial change",
        "+    # padding",
        "+    # padding",
    ]
)


def _finding(rule_id="SAST.SQL_INJECTION", severity=Severity.CRITICAL) -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path=PATH,
        line_number=2,
        title="SQL Injection",
        description="Concatenated query",
        remediation="Parameterise it",
        rule_id=rule_id,
    )


def _recollection(**overrides) -> Recollection:
    defaults = {
        "kind": RecollectionKind.FINDING,
        "file_path": PATH,
        "rule_id": "SAST.SQL_INJECTION",
        "severity": Severity.CRITICAL,
        "first_seen": TODAY - timedelta(days=45),
        "last_seen": TODAY - timedelta(days=5),
        "occurrences": 7,
    }
    return Recollection(**{**defaults, **overrides})


class RecordingReviewer(Reviewer):
    def __init__(self):
        self.recollections_seen: list | None = None

    def review_diff(
        self,
        filename,
        diff_content,
        full_file_content=None,
        other_files=None,
        related=None,
        recollections=None,
    ):
        self.recollections_seen = recollections
        return "## Review\nA concatenated query."


class FakeForge(CodeForge):
    def __init__(self):
        self.published: list[str] = []

    def fetch_merge_request(self, project_id, merge_request_iid):
        return MergeRequestRef(project_id=str(project_id), merge_request_id=str(merge_request_iid))

    def fetch_changes(self, reference):
        return [FileChange(PATH, DIFF)]

    def fetch_file(self, reference, path):
        return "def find(connection, name):\n    return 1\n"

    def publish_comment(self, reference, body):
        self.published.append(body)


class StubAnalysis:
    def __init__(self, findings=(), suppressed=()):
        self._findings = list(findings)
        self._suppressed = list(suppressed)

    def analyze(self, file_path, content, diff=""):
        return SuppressionResult(findings=list(self._findings), suppressed=list(self._suppressed))


class StubStore(MemoryStore):
    def __init__(self, stored=(), load_error=None, save_error=None):
        self.stored = list(stored)
        self.load_error = load_error
        self.save_error = save_error
        self.saved: list | None = None

    def load(self):
        if self.load_error is not None:
            raise self.load_error
        return list(self.stored)

    def save(self, recollections):
        if self.save_error is not None:
            raise self.save_error
        self.saved = list(recollections)


def _service(reviewer, analysis, memory=None, forge=None) -> ReviewService:
    return ReviewService(
        forge=forge or FakeForge(),
        reviewer=reviewer,
        triage=ReviewTriage(ReviewPolicy()),
        policy=ReviewPolicy(),
        analysis=analysis,
        memory=memory,
        clock=lambda: 0,
    )


def _memory(store) -> ProjectMemory:
    return ProjectMemory(store, clock=lambda: TODAY)


class TestRecallReachesTheReviewer(unittest.TestCase):
    def test_what_was_remembered_is_passed_to_the_reviewer(self):
        reviewer = RecordingReviewer()
        service = _service(reviewer, StubAnalysis([_finding()]), _memory(StubStore([_recollection()])))

        service.review(1, 2, publish=False)

        self.assertEqual([item.rule_id for item in reviewer.recollections_seen], ["SAST.SQL_INJECTION"])

    def test_without_memory_the_reviewer_is_given_nothing(self):
        reviewer = RecordingReviewer()

        _service(reviewer, StubAnalysis([_finding()])).review(1, 2, publish=False)

        self.assertEqual(reviewer.recollections_seen, [])


class TestWhatIsRemembered(unittest.TestCase):
    def test_the_run_is_persisted(self):
        store = StubStore()

        _service(RecordingReviewer(), StubAnalysis([_finding()]), _memory(store)).review(1, 2, publish=False)

        self.assertIsNotNone(store.saved)
        self.assertEqual([item.rule_id for item in store.saved], ["SAST.SQL_INJECTION"])

    def test_a_repeat_increments_rather_than_appending(self):
        store = StubStore([_recollection()])

        _service(RecordingReviewer(), StubAnalysis([_finding()]), _memory(store)).review(1, 2, publish=False)

        self.assertEqual(len(store.saved), 1)
        self.assertEqual(store.saved[0].occurrences, 8)

    def test_suppressions_are_remembered_with_their_reason(self):
        directive = SuppressionDirective(rule_id="SAST.WEAK_CRYPTO", reason="cache key", line=4)
        analysis = StubAnalysis(
            findings=[_finding()],
            suppressed=[SuppressedFinding(finding=_finding("SAST.WEAK_CRYPTO"), directive=directive)],
        )
        store = StubStore()

        _service(RecordingReviewer(), analysis, _memory(store)).review(1, 2, publish=False)

        suppression = next(item for item in store.saved if item.kind is RecollectionKind.SUPPRESSION)
        self.assertEqual(suppression.rule_id, "SAST.WEAK_CRYPTO")
        self.assertEqual(suppression.reason, "cache key")


class TestTheReport(unittest.TestCase):
    def test_a_recurring_finding_is_marked_with_its_count(self):
        forge = FakeForge()
        _service(
            RecordingReviewer(), StubAnalysis([_finding()]), _memory(StubStore([_recollection()])), forge
        ).review(1, 2)

        body = forge.published[0]
        self.assertIn("seen in this project before", body)
        self.assertIn("7 time(s) before", body)

    def test_a_first_time_finding_is_not_marked(self):
        forge = FakeForge()
        _service(RecordingReviewer(), StubAnalysis([_finding()]), _memory(StubStore()), forge).review(1, 2)

        self.assertNotIn("seen in this project before", forge.published[0])

    def test_without_memory_the_report_says_nothing_about_recurrence(self):
        forge = FakeForge()
        _service(RecordingReviewer(), StubAnalysis([_finding()]), None, forge).review(1, 2)

        self.assertNotIn("seen in this project before", forge.published[0])


class TestMemoryNeverDecides(unittest.TestCase):
    """AC-11, and the reason this level has a central test at all.

    Memory is the first feature here that could plausibly make the agent less
    trustworthy — by making it forgiving. The same review is run twice, once
    with a long history of exactly this finding and once with none, and every
    part of the decision has to be identical.
    """

    def _run(self, memory):
        return _service(RecordingReviewer(), StubAnalysis([_finding()]), memory).review(1, 2, publish=False)

    def test_the_verdict_is_identical_with_and_without_a_history(self):
        without = self._run(None)
        with_history = self._run(_memory(StubStore([_recollection(occurrences=99)])))

        self.assertIs(with_history.outcome.result, without.outcome.result)
        self.assertEqual(with_history.exit_code, without.exit_code)

    def test_the_findings_are_identical_with_and_without_a_history(self):
        without = self._run(None)
        with_history = self._run(_memory(StubStore([_recollection(occurrences=99)])))

        self.assertEqual(with_history.findings, without.findings)

    def test_a_long_history_does_not_soften_a_severity(self):
        result = self._run(_memory(StubStore([_recollection(occurrences=99)])))

        self.assertEqual([finding.severity for finding in result.findings], [Severity.CRITICAL])


class TestMemoryNeverBlocks(unittest.TestCase):
    def test_a_store_that_cannot_be_read_costs_the_review_nothing(self):
        result = _service(
            RecordingReviewer(), StubAnalysis([_finding()]), _memory(StubStore(load_error=OSError("gone")))
        ).review(1, 2, publish=False)

        self.assertEqual(result.exit_code, 1)  # the CRITICAL finding, not the store
        self.assertFalse(result.outcome.failed_files)

    def test_a_store_that_cannot_be_written_costs_the_review_nothing(self):
        result = _service(
            RecordingReviewer(),
            StubAnalysis([_finding()]),
            _memory(StubStore(save_error=OSError("read-only"))),
        ).review(1, 2, publish=False)

        self.assertFalse(result.outcome.failed_files)
        self.assertFalse(result.outcome.unanalysed_files)


if __name__ == "__main__":
    unittest.main()
