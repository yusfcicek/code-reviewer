"""Step 5 — the thread that turns queued jobs into reviews."""

import itertools
import time
from datetime import UTC, datetime

from code_reviewer.application.jobs import InMemoryJobStore, JobService
from code_reviewer.application.review_service import ReviewResult
from code_reviewer.domain.gate import ReviewGateResult
from code_reviewer.domain.job import JobState, ReviewTarget
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.infrastructure.http.worker import ReviewWorker
from code_reviewer.infrastructure.observability.tracer import get_tracer

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


class StubReviews:
    """Stands in for `ReviewService`, recording what it was asked."""

    def __init__(self, error=None, exit_code=0, delay=0.0):
        self.error = error
        self.exit_code = exit_code
        self.delay = delay
        self.calls: list[tuple[int, int]] = []
        self.trace_ids: list[str] = []

    def review(self, project_id, merge_request_iid, publish=True):
        self.calls.append((project_id, merge_request_iid))
        self.trace_ids.append(get_tracer().trace_id)
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error

        outcome = ReviewOutcome()
        return ReviewResult(outcome=outcome, exit_code=self.exit_code)


def _jobs() -> JobService:
    counter = itertools.count(1)
    return JobService(InMemoryJobStore(), clock=lambda: NOW, new_id=lambda: f"job-{next(counter)}")


def test_a_queued_job_is_run_and_recorded():
    jobs = _jobs()
    reviews = StubReviews()
    job, _ = jobs.submit(ReviewTarget(17, 42, "abc"))

    assert ReviewWorker(jobs, reviews).run_once()

    assert reviews.calls == [(17, 42)]
    finished = jobs.get(job.job_id)
    assert finished.state is JobState.SUCCEEDED
    assert finished.verdict == ReviewGateResult.PASS.value
    assert finished.exit_code == 0


def test_a_blocking_review_records_its_exit_code():
    jobs = _jobs()
    job, _ = jobs.submit(ReviewTarget(17, 42, "abc"))

    ReviewWorker(jobs, StubReviews(exit_code=1)).run_once()

    assert jobs.get(job.job_id).exit_code == 1


def test_nothing_queued_is_not_an_error():
    assert not ReviewWorker(_jobs(), StubReviews()).run_once()


def test_a_review_that_raises_marks_the_job_failed():
    """A worker that dies on one bad merge request takes the service down
    with it."""
    jobs = _jobs()
    job, _ = jobs.submit(ReviewTarget(17, 42, "abc"))

    assert ReviewWorker(jobs, StubReviews(error=RuntimeError("the forge refused"))).run_once()

    failed = jobs.get(job.job_id)
    assert failed.state is JobState.FAILED
    assert "RuntimeError" in failed.failure_reason
    assert "the forge refused" in failed.failure_reason


def test_the_worker_keeps_draining_after_a_failure():
    jobs = _jobs()
    first, _ = jobs.submit(ReviewTarget(1, 1, "a"))
    second, _ = jobs.submit(ReviewTarget(1, 2, "b"))
    reviews = StubReviews(error=RuntimeError("no"))
    worker = ReviewWorker(jobs, reviews)

    worker.run_once()
    worker.run_once()

    assert jobs.get(first.job_id).state is JobState.FAILED
    assert jobs.get(second.job_id).state is JobState.FAILED
    assert len(reviews.calls) == 2


# -- tracing -----------------------------------------------------------------


def test_each_job_runs_inside_its_own_trace():
    jobs = _jobs()
    jobs.submit(ReviewTarget(17, 42, "abc"))
    jobs.submit(ReviewTarget(17, 43, "def"))
    reviews = StubReviews()
    worker = ReviewWorker(jobs, reviews)

    worker.run_once()
    worker.run_once()

    assert len(set(reviews.trace_ids)) == 2
    assert all(trace_id.startswith("17-4") for trace_id in reviews.trace_ids)


def test_the_job_records_the_trace_it_ran_under():
    jobs = _jobs()
    job, _ = jobs.submit(ReviewTarget(17, 42, "abc"))

    ReviewWorker(jobs, StubReviews()).run_once()

    assert jobs.get(job.job_id).trace_id.startswith("17-42-")


def test_the_ambient_tracer_is_released_afterwards():
    """A trace belongs to one review. Leaving it set would put the next
    request's log lines inside a finished one."""
    jobs = _jobs()
    jobs.submit(ReviewTarget(17, 42, "abc"))

    ReviewWorker(jobs, StubReviews()).run_once()

    assert get_tracer().trace_id == ""


def test_the_tracer_is_released_even_when_the_review_raises():
    jobs = _jobs()
    jobs.submit(ReviewTarget(17, 42, "abc"))

    ReviewWorker(jobs, StubReviews(error=RuntimeError("no"))).run_once()

    assert get_tracer().trace_id == ""


# -- the loop ----------------------------------------------------------------


def test_the_loop_drains_the_queue_and_stops_promptly():
    jobs = _jobs()
    for index in range(3):
        jobs.submit(ReviewTarget(1, index, f"sha{index}"))
    reviews = StubReviews()
    worker = ReviewWorker(jobs, reviews, poll_seconds=0.01)

    worker.start()
    deadline = time.monotonic() + 2.0
    while len(reviews.calls) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    started = time.monotonic()
    worker.stop()

    assert len(reviews.calls) == 3
    assert time.monotonic() - started < 1.0


def test_starting_twice_runs_one_thread():
    worker = ReviewWorker(_jobs(), StubReviews(), poll_seconds=0.01)

    worker.start()
    worker.start()
    worker.stop()


def test_stopping_a_worker_that_never_started_is_safe():
    ReviewWorker(_jobs(), StubReviews()).stop()
