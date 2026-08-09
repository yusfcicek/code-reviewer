"""Step 2 — accepting a review, once."""

import itertools
import threading
from datetime import UTC, datetime

import pytest

from code_reviewer.application.jobs import InMemoryJobStore, JobService, QueueFull
from code_reviewer.domain.job import JobState, ReviewTarget

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
TARGET = ReviewTarget(project_id=17, merge_request_iid=42, head_sha="abc123")


def _service(**overrides) -> JobService:
    counter = itertools.count(1)
    defaults = {
        "store": InMemoryJobStore(),
        "clock": lambda: NOW,
        "new_id": lambda: f"job-{next(counter)}",
    }
    return JobService(**{**defaults, **overrides})


# -- accepting ---------------------------------------------------------------


def test_a_new_target_is_accepted_and_created():
    job, created = _service().submit(TARGET)

    assert created
    assert job.state is JobState.QUEUED
    assert job.target == TARGET
    assert job.submitted_at == NOW


def test_the_same_target_twice_is_one_job():
    service = _service()

    first, created_first = service.submit(TARGET)
    second, created_second = service.submit(TARGET)

    assert created_first
    assert not created_second
    assert second.job_id == first.job_id


def test_a_different_commit_is_a_different_job():
    """Two requests at different head commits are two reviews, because the
    code changed."""
    service = _service()

    first, _ = service.submit(TARGET)
    second, created = service.submit(ReviewTarget(17, 42, "def456"))

    assert created
    assert second.job_id != first.job_id


def test_an_idempotency_key_collapses_two_different_targets():
    service = _service()

    first, _ = service.submit(TARGET, idempotency_key="chosen")
    second, created = service.submit(ReviewTarget(99, 1, "zzz"), idempotency_key="chosen")

    assert not created
    assert second.job_id == first.job_id


def test_a_finished_job_does_not_block_the_same_target_again():
    """A retry after a failure, or a rerun after the policy changed."""
    service = _service()
    first, _ = service.submit(TARGET)
    running = service.claim()
    service.complete(running, verdict="pass", exit_code=0)

    second, created = service.submit(TARGET)

    assert created
    assert second.job_id != first.job_id


def test_a_running_job_does_block_the_same_target():
    service = _service()
    service.submit(TARGET)
    service.claim()

    _, created = service.submit(TARGET)

    assert not created


# -- the queue's depth -------------------------------------------------------


def test_a_full_queue_refuses():
    service = _service(max_queue_depth=2)
    service.submit(ReviewTarget(1, 1, "a"))
    service.submit(ReviewTarget(1, 2, "b"))

    with pytest.raises(QueueFull):
        service.submit(ReviewTarget(1, 3, "c"))


def test_claiming_makes_room():
    service = _service(max_queue_depth=1)
    service.submit(ReviewTarget(1, 1, "a"))
    service.claim()

    _, created = service.submit(ReviewTarget(1, 2, "b"))

    assert created


def test_saturation_is_readable():
    service = _service(max_queue_depth=1)

    assert not service.is_saturated
    service.submit(TARGET)
    assert service.is_saturated


def test_an_idempotent_request_is_accepted_even_when_the_queue_is_full():
    """It adds nothing to the queue, and refusing it would tell a caller its
    review was rejected when it is already running."""
    service = _service(max_queue_depth=1)
    first, _ = service.submit(TARGET)

    second, created = service.submit(TARGET)

    assert not created
    assert second.job_id == first.job_id


# -- claiming ----------------------------------------------------------------


def test_claiming_takes_the_oldest_and_starts_it():
    service = _service()
    first, _ = service.submit(ReviewTarget(1, 1, "a"))
    service.submit(ReviewTarget(1, 2, "b"))

    claimed = service.claim(trace_id="t-1")

    assert claimed.job_id == first.job_id
    assert claimed.state is JobState.RUNNING
    assert claimed.started_at == NOW
    assert claimed.trace_id == "t-1"


def test_claiming_with_nothing_queued_returns_nothing_rather_than_blocking():
    """A worker that waits inside the store is a worker that cannot be told
    to stop."""
    assert _service().claim() is None


def test_a_claimed_job_is_not_claimed_twice():
    service = _service()
    service.submit(TARGET)

    service.claim()

    assert service.claim() is None


# -- finishing ---------------------------------------------------------------


def test_completing_records_the_verdict_and_the_exit_code():
    service = _service()
    service.submit(TARGET)
    running = service.claim()

    finished = service.complete(running, verdict="fail", exit_code=1)

    assert service.get(finished.job_id).state is JobState.SUCCEEDED
    assert service.get(finished.job_id).verdict == "fail"
    assert service.get(finished.job_id).exit_code == 1


def test_failing_records_the_reason():
    service = _service()
    service.submit(TARGET)
    running = service.claim()

    failed = service.fail(running, reason="ForgeError: 502", exit_code=3)

    assert service.get(failed.job_id).state is JobState.FAILED
    assert "502" in service.get(failed.job_id).failure_reason


def test_an_unknown_job_is_not_found():
    assert _service().get("nope") is None


# -- retention ---------------------------------------------------------------


def test_finished_jobs_are_forgotten_past_the_retention_bound():
    service = _service(store=InMemoryJobStore(retained=3))

    for index in range(6):
        service.submit(ReviewTarget(1, index, f"sha{index}"))
        running = service.claim()
        service.complete(running, verdict="pass", exit_code=0)

    assert sum(1 for index in range(6) if service.get(f"job-{index + 1}")) <= 3


def test_a_job_still_in_flight_is_never_forgotten():
    """Dropping one would lose a review somebody is waiting for."""
    service = _service(store=InMemoryJobStore(retained=1))

    first, _ = service.submit(ReviewTarget(1, 1, "a"))
    second, _ = service.submit(ReviewTarget(1, 2, "b"))
    third, _ = service.submit(ReviewTarget(1, 3, "c"))

    assert service.get(first.job_id) is not None
    assert service.get(second.job_id) is not None
    assert service.get(third.job_id) is not None


# -- contention --------------------------------------------------------------


def test_eight_threads_submitting_one_target_produce_one_job():
    """ "Look, then insert" is exactly the shape that produces two."""
    service = _service()
    results = []
    lock = threading.Lock()

    def submit():
        job, created = service.submit(TARGET)
        with lock:
            results.append((job.job_id, created))

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({job_id for job_id, _ in results}) == 1
    assert sum(1 for _, created in results if created) == 1


def test_eight_threads_claiming_take_eight_distinct_jobs():
    service = _service()
    for index in range(8):
        service.submit(ReviewTarget(1, index, f"sha{index}"))

    claimed = []
    lock = threading.Lock()

    def claim():
        job = service.claim()
        if job is not None:
            with lock:
                claimed.append(job.job_id)

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(claimed) == 8
    assert len(set(claimed)) == 8
