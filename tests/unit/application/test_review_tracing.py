"""Step 6 — the review path, traced."""

import unittest

from code_reviewer.application.orchestration_service import ReviewOrchestrator
from code_reviewer.application.ports import (
    CodeForge,
    CodeRetriever,
    FileChange,
    MemoryStore,
    MergeRequestRef,
    Reviewer,
    Specialist,
)
from code_reviewer.application.project_memory import ProjectMemory
from code_reviewer.application.review_service import ReviewService
from code_reviewer.application.tracing import NullTracer
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.orchestration import AgentReport
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.retrieval import CodeChunk
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import SuppressionResult
from code_reviewer.domain.trace import SpanKind, SpanStatus
from code_reviewer.domain.triage import ReviewTriage
from code_reviewer.infrastructure.observability.tracer import SpanRecorder

PATH = "storage/repository.py"
SECRET_IN_THE_DIFF = "AKIAIOSFODNN7EXAMPLE"
DIFF = "\n".join(
    [
        "@@ -1,4 +1,10 @@",
        f"+TOKEN = '{SECRET_IN_THE_DIFF}'",
        "+def find(connection, name):",
        "+    query = 'SELECT * FROM users WHERE name = ' + name",
        "+    return connection.execute(query)",
        "+    # padding",
        "+    # padding",
    ]
)
CONTENT = f"TOKEN = '{SECRET_IN_THE_DIFF}'\ndef find(connection, name):\n    return 1\n"


def _finding() -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.CRITICAL,
        file_path=PATH,
        line_number=2,
        title="SQL Injection",
        description=f"A query built from {SECRET_IN_THE_DIFF}",
        remediation="Parameterise it",
        rule_id="SAST.SQL_INJECTION",
        evidence=f"TOKEN = '{SECRET_IN_THE_DIFF}'",
    )


class FakeForge(CodeForge):
    def fetch_merge_request(self, project_id, merge_request_iid):
        return MergeRequestRef(project_id=str(project_id), merge_request_id=str(merge_request_iid))

    def fetch_changes(self, reference):
        return [FileChange(PATH, DIFF)]

    def fetch_file(self, reference, path):
        return CONTENT

    def publish_comment(self, reference, body):
        pass


class StubAnalysis:
    def analyze(self, file_path, content, diff=""):
        return SuppressionResult(findings=[_finding()])


class StubRetriever(CodeRetriever):
    def related(self, query, limit=5, exclude_path=""):
        return [CodeChunk(path="a.py", start_line=1, end_line=2, text="def verify(): ...", name="verify")]


class StubStore(MemoryStore):
    def load(self):
        return []

    def save(self, recollections):
        pass


class ScriptedSpecialist(Specialist):
    def __init__(self, error=None):
        self.error = error

    def review(self, brief, assignment):
        if self.error is not None:
            raise self.error
        return AgentReport(
            specialism=assignment.specialism,
            prose=f"{assignment.specialism.value}: fine",
            tokens_allowed=assignment.token_budget,
            tool_calls=2,
        )


class PlainReviewer(Reviewer):
    def review_diff(self, brief):
        return "## Review\nfine"


def _service(reviewer, tracer, **overrides) -> ReviewService:
    return ReviewService(
        forge=FakeForge(),
        reviewer=reviewer,
        triage=ReviewTriage(ReviewPolicy()),
        policy=ReviewPolicy(),
        analysis=StubAnalysis(),
        retriever=StubRetriever(),
        memory=ProjectMemory(StubStore()),
        tracer=tracer,
        clock=lambda: 0,
        **overrides,
    )


class TestTheReviewPathIsTraced(unittest.TestCase):
    def setUp(self):
        self.tracer = SpanRecorder(trace_id="run-1")
        specialists = {
            specialism: ScriptedSpecialist()
            for specialism in __import__(
                "code_reviewer.domain.orchestration", fromlist=["Specialism"]
            ).Specialism
        }
        self.orchestrator = ReviewOrchestrator(specialists, tracer=self.tracer)
        _service(self.orchestrator, self.tracer).review(1, 2, publish=False)
        self.trace = self.tracer.trace()

    def _kinds(self):
        return {span.kind for span in self.trace.spans}

    def test_the_run_the_file_and_the_work_beneath_it_are_all_spans(self):
        self.assertLessEqual(
            {
                SpanKind.REVIEW,
                SpanKind.FILE,
                SpanKind.ANALYSIS,
                SpanKind.RETRIEVAL,
                SpanKind.MEMORY,
                SpanKind.AGENT,
            },
            self._kinds(),
        )

    def test_the_tree_is_rooted_at_the_review(self):
        root = self.trace.tree()

        self.assertIsNotNone(root)
        self.assertIs(root.span.kind, SpanKind.REVIEW)
        self.assertEqual(self.trace.anomalies, ())

    def test_the_file_span_is_beneath_the_review_and_the_work_beneath_the_file(self):
        by_id = {span.span_id: span for span in self.trace.spans}
        file_span = next(span for span in self.trace.spans if span.kind is SpanKind.FILE)
        agent_span = next(span for span in self.trace.spans if span.kind is SpanKind.AGENT)

        self.assertIs(by_id[file_span.parent_id].kind, SpanKind.REVIEW)
        self.assertEqual(agent_span.parent_id, file_span.span_id)

    def test_an_agent_span_carries_its_specialism_and_its_budget(self):
        agents = [span for span in self.trace.spans if span.kind is SpanKind.AGENT]

        self.assertIn("security", {span.name for span in agents})
        self.assertTrue(all(span.attributes["budget"] > 0 for span in agents))
        self.assertTrue(all(span.attributes["tool_calls"] == 2 for span in agents))

    def test_the_retrieval_span_records_how_much_it_found(self):
        retrieval = next(span for span in self.trace.spans if span.kind is SpanKind.RETRIEVAL)

        self.assertEqual(retrieval.attributes["chunks"], 1)


class TestNothingUnderReviewReachesTheTrace(unittest.TestCase):
    """AC-14, enforced rather than advised.

    A trace is written to an artefact anyone with pipeline access can read,
    and this diff contains a credential-shaped string in three places: the
    diff itself, the file content, and the finding's evidence.
    """

    def test_no_attribute_anywhere_carries_the_content_under_review(self):
        tracer = SpanRecorder(trace_id="run-1")
        _service(PlainReviewer(), tracer).review(1, 2, publish=False)

        values = [str(value) for span in tracer.trace().spans for value in span.attributes.values()]
        names = [span.name for span in tracer.trace().spans]

        for text in values + names:
            self.assertNotIn(SECRET_IN_THE_DIFF, text)
            self.assertNotIn("SELECT * FROM", text)


class TestFailureIsVisible(unittest.TestCase):
    def test_a_failing_specialist_leaves_a_failed_span(self):
        from code_reviewer.domain.orchestration import Specialism

        tracer = SpanRecorder(trace_id="run-1")
        orchestrator = ReviewOrchestrator(
            {
                Specialism.ARCHITECTURE: ScriptedSpecialist(),
                Specialism.SECURITY: ScriptedSpecialist(error=TimeoutError("gone")),
            },
            tracer=tracer,
        )

        _service(orchestrator, tracer).review(1, 2, publish=False)

        failed = [span for span in tracer.trace().spans if span.status is SpanStatus.ERROR]
        self.assertEqual([span.name for span in failed], ["security"])
        self.assertEqual(failed[0].error_type, "TimeoutError")


class TestTracingIsOptional(unittest.TestCase):
    def test_a_null_tracer_produces_the_same_decision(self):
        """The report gains one footer field naming the run. Nothing else
        about the review may differ, because tracing observes."""
        traced = _service(PlainReviewer(), SpanRecorder(trace_id="run-1")).review(1, 2, publish=False)
        untraced = _service(PlainReviewer(), NullTracer()).review(1, 2, publish=False)

        self.assertEqual(traced.exit_code, untraced.exit_code)
        self.assertEqual(traced.findings, untraced.findings)
        self.assertIs(traced.outcome.result, untraced.outcome.result)
        self.assertEqual(
            traced.comment.replace(" | **Trace**: `run-1`", ""),
            untraced.comment,
        )

    def test_a_service_built_without_a_tracer_records_nothing(self):
        service = ReviewService(
            forge=FakeForge(),
            reviewer=PlainReviewer(),
            triage=ReviewTriage(ReviewPolicy()),
            policy=ReviewPolicy(),
            analysis=StubAnalysis(),
            clock=lambda: 0,
        )

        result = service.review(1, 2, publish=False)

        self.assertTrue(result.comment)


if __name__ == "__main__":
    unittest.main()
