"""Steps 5 and 6 — the committee, concurrently, and provably unchanged.

Every assertion here is an *equality* against the sequential path. That is the
only honest way to claim a concurrency change did not change anything else.
"""

import threading
import time

import pytest

from code_reviewer.application.orchestration_service import ReviewOrchestrator
from code_reviewer.application.ports import (
    CodeForge,
    FileChange,
    MergeRequestRef,
    ReviewBrief,
    Specialist,
)
from code_reviewer.application.review_service import ReviewService
from code_reviewer.application.tasks import SequentialRunner
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.orchestration import AgentReport, Specialism
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import SuppressionResult
from code_reviewer.domain.trace import SpanKind
from code_reviewer.domain.triage import ReviewTriage
from code_reviewer.infrastructure.concurrency.thread_pool import ThreadPoolRunner
from code_reviewer.infrastructure.observability.tracer import SpanRecorder

PATH = "storage/repository.py"
DIFF = "\n".join(
    [
        "@@ -1,4 +1,10 @@",
        "+def find(connection, name):",
        "+    query = 'SELECT * FROM users WHERE name = ' + name",
        "+    return connection.execute(query)",
        "+    # padding",
        "+    # padding",
        "+    # padding",
    ]
)


def _finding(category=FindingCategory.SECURITY) -> Finding:
    return Finding(
        category=category,
        severity=Severity.CRITICAL,
        file_path=PATH,
        line_number=2,
        title="t",
        description="d",
        remediation="r",
        rule_id=f"{category.value.upper()}.RULE",
    )


ALL_FINDINGS = (
    _finding(FindingCategory.SECURITY),
    _finding(FindingCategory.PERFORMANCE),
    _finding(FindingCategory.DEPENDENCY),
)


class SlowSpecialist(Specialist):
    """Waits, the way a model call waits."""

    def __init__(self, delay: float = 0.05, error=None):
        self.delay = delay
        self.error = error

    def review(self, brief, assignment):
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return AgentReport(
            specialism=assignment.specialism,
            prose=f"{assignment.specialism.value}: reviewed",
            tokens_allowed=assignment.token_budget,
            tool_calls=1,
        )


def _committee(delay: float = 0.05) -> dict:
    return {specialism: SlowSpecialist(delay) for specialism in Specialism}


def _brief() -> ReviewBrief:
    return ReviewBrief(file_path=PATH, diff=DIFF, findings=ALL_FINDINGS)


# -- identical results -------------------------------------------------------


def test_the_report_is_identical_sequential_and_concurrent():
    sequential = ReviewOrchestrator(_committee(0.0), runner=SequentialRunner())
    concurrent = ReviewOrchestrator(_committee(0.0), runner=ThreadPoolRunner(max_workers=4))

    assert sequential.review_diff(_brief()) == concurrent.review_diff(_brief())


def test_the_per_agent_accounting_is_identical():
    sequential = ReviewOrchestrator(_committee(0.0), runner=SequentialRunner())
    concurrent = ReviewOrchestrator(_committee(0.0), runner=ThreadPoolRunner(max_workers=4))

    sequential.review_diff(_brief())
    concurrent.review_diff(_brief())

    assert {
        specialism: (total.runs, total.failures, total.tool_calls)
        for specialism, total in sequential.agent_totals.items()
    } == {
        specialism: (total.runs, total.failures, total.tool_calls)
        for specialism, total in concurrent.agent_totals.items()
    }


def test_the_sections_stay_in_composition_order():
    document = ReviewOrchestrator(_committee(0.0), runner=ThreadPoolRunner(max_workers=4)).review_diff(
        _brief()
    )

    assert (
        document.index("architecture:")
        < document.index("security:")
        < document.index("performance:")
        < document.index("dependency:")
    )


# -- and faster --------------------------------------------------------------


def test_the_committee_overlaps_its_waiting():
    started = time.monotonic()
    ReviewOrchestrator(_committee(0.1), runner=ThreadPoolRunner(max_workers=4)).review_diff(_brief())
    concurrent = time.monotonic() - started

    started = time.monotonic()
    ReviewOrchestrator(_committee(0.1), runner=SequentialRunner()).review_diff(_brief())
    sequential = time.monotonic() - started

    assert concurrent < sequential
    assert concurrent < 0.3, f"four 100 ms agents took {concurrent:.2f}s"


def test_only_as_many_specialists_run_at_once_as_the_pool_allows():
    peak = 0
    running = 0
    lock = threading.Lock()

    class Counting(Specialist):
        def review(self, brief, assignment):
            nonlocal peak, running
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with lock:
                running -= 1
            return AgentReport(specialism=assignment.specialism, prose="x")

    ReviewOrchestrator(
        {specialism: Counting() for specialism in Specialism},
        runner=ThreadPoolRunner(max_workers=2),
    ).review_diff(_brief())

    assert peak <= 2


# -- failure and timeout -----------------------------------------------------


def test_a_specialist_that_hangs_is_reported_and_the_others_still_appear():
    committee = _committee(0.0)
    committee[Specialism.SECURITY] = SlowSpecialist(delay=5.0)

    started = time.monotonic()
    document = ReviewOrchestrator(
        committee, runner=ThreadPoolRunner(max_workers=4), agent_timeout_s=0.15
    ).review_diff(_brief())

    assert "architecture: reviewed" in document
    assert "did not complete" in document
    assert "timed out" in document
    assert time.monotonic() - started < 1.5


def test_a_specialist_that_raises_is_reported_under_either_runner():
    for runner in (SequentialRunner(), ThreadPoolRunner(max_workers=4)):
        committee = _committee(0.0)
        committee[Specialism.SECURITY] = SlowSpecialist(error=RuntimeError("endpoint refused"))

        document = ReviewOrchestrator(committee, runner=runner).review_diff(_brief())

        assert "endpoint refused" in document
        assert "architecture: reviewed" in document


# -- tracing under concurrency -----------------------------------------------


def test_every_agent_span_attaches_to_the_file_span():
    """AC-7 through the real path: a worker's span belongs to what submitted
    it, not to another agent that happened to be open on another thread."""
    tracer = SpanRecorder()
    orchestrator = ReviewOrchestrator(_committee(0.02), tracer=tracer, runner=ThreadPoolRunner(max_workers=4))

    with tracer.span(SpanKind.FILE, PATH) as file_span:
        orchestrator.review_diff(_brief())

    trace = tracer.trace()
    agents = [span for span in trace.spans if span.kind is SpanKind.AGENT]

    assert len(agents) == 4
    assert {span.parent_id for span in agents} == {file_span}
    assert trace.anomalies == ()


# -- the whole review --------------------------------------------------------


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
    def analyze(self, file_path, content, diff=""):
        return SuppressionResult(findings=list(ALL_FINDINGS))


def _review(runner):
    orchestrator = ReviewOrchestrator(_committee(0.0), runner=runner)
    return ReviewService(
        forge=FakeForge(),
        reviewer=orchestrator,
        triage=ReviewTriage(ReviewPolicy()),
        policy=ReviewPolicy(),
        analysis=StubAnalysis(),
        clock=lambda: 0,
    ).review(1, 2, publish=False)


def test_the_verdict_is_identical_sequential_and_concurrent():
    """AC-13. The gate reads findings, and findings come from the analyzers,
    which run before any agent and remain sequential."""
    sequential = _review(SequentialRunner())
    concurrent = _review(ThreadPoolRunner(max_workers=4))

    assert sequential.exit_code == concurrent.exit_code
    assert sequential.outcome.result is concurrent.outcome.result
    assert sequential.findings == concurrent.findings
    assert sequential.comment == concurrent.comment


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_the_result_does_not_depend_on_the_pool_size(workers):
    assert _review(ThreadPoolRunner(max_workers=workers)).comment == _review(SequentialRunner()).comment
