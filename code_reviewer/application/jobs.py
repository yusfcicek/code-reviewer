"""Accepting a review, and remembering that it was accepted.

A review takes minutes, so the service answers with a job rather than with a
review. This module is what stands between an HTTP request and
:class:`~code_reviewer.domain.job.ReviewJob`: it enforces the queue's depth,
decides whether a request is one it has already seen, and hands the worker its
next piece of work.

The interesting part is *find-or-create*. Two requests for the same commit
arriving at once must produce one job, and "look, then insert" is exactly the
shape that produces two. The store's ``submit`` does both under one lock and
reports which happened, so the caller can answer 202 or 200 truthfully.

Job state is in memory, and a restart loses the queue. Persisting it is a
decision about operating the service — which store, whose backup, whose
migration — and making it here would be guessing (decision D-6).
"""

import threading
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime

from code_reviewer.domain.job import JobState, ReviewJob, ReviewTarget

#: How many reviews may be waiting before the service starts refusing. A queue
#: that grows without bound is a memory leak with a REST interface.
DEFAULT_QUEUE_DEPTH = 32

#: How long a finished job stays readable. Long enough for a caller to poll,
#: short enough that the process does not accumulate a day of them.
DEFAULT_RETAINED_JOBS = 200


class QueueFull(Exception):
    """The queue is at its depth and this review was not accepted."""


class JobStore(ABC):
    """Where jobs live for as long as anyone might ask about them."""

    @abstractmethod
    def submit(self, job: ReviewJob, max_queued: int) -> tuple[ReviewJob, bool]:
        """Adds ``job`` unless one with its key is already in flight.

        Returns the job that is now in flight and whether this call created
        it. Atomic: "look, then insert" is the shape that turns two
        simultaneous requests for one commit into two reviews.

        Raises:
            QueueFull: when accepting it would exceed ``max_queued``.
        """

    @abstractmethod
    def get(self, job_id: str) -> ReviewJob | None:
        """One job, or ``None``."""

    @abstractmethod
    def claim_next(self, when: datetime, trace_id: str = "") -> ReviewJob | None:
        """The oldest queued job, moved to running, or ``None`` if there is none.

        Never blocks: a worker that waits inside the store is a worker that
        cannot be told to stop.
        """

    @abstractmethod
    def update(self, job: ReviewJob) -> None:
        """Replaces a job with a later version of itself."""

    @abstractmethod
    def queued_count(self) -> int:
        """How many are waiting."""


class InMemoryJobStore(JobStore):
    """One process's jobs, behind one lock.

    Every operation is composite — find-or-create, take-the-oldest-and-move-it
    — so each is one critical section rather than a sequence a caller could be
    interrupted in the middle of.
    """

    def __init__(self, retained: int = DEFAULT_RETAINED_JOBS):
        self._lock = threading.Lock()
        self._jobs: dict[str, ReviewJob] = {}
        self._order: list[str] = []
        self._retained = retained

    def submit(self, job: ReviewJob, max_queued: int) -> tuple[ReviewJob, bool]:
        with self._lock:
            existing = self._in_flight(job.key)
            if existing is not None:
                return existing, False

            if self._queued() >= max_queued:
                raise QueueFull(f"{max_queued} review(s) are already waiting.")

            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            self._forget_old()
            return job, True

    def get(self, job_id: str) -> ReviewJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def claim_next(self, when: datetime, trace_id: str = "") -> ReviewJob | None:
        with self._lock:
            for job_id in self._order:
                job = self._jobs[job_id]
                if job.state is JobState.QUEUED:
                    running = job.started(when, trace_id=trace_id)
                    self._jobs[job_id] = running
                    return running
            return None

    def update(self, job: ReviewJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def queued_count(self) -> int:
        with self._lock:
            return self._queued()

    # -- internals ----------------------------------------------------------

    def _in_flight(self, key: str) -> ReviewJob | None:
        """A job with this key that has not finished.

        Finished ones are deliberately not matched: once a review is done, the
        same commit may legitimately be reviewed again — a retry after a
        failure, or a rerun after the policy changed.
        """
        for job_id in reversed(self._order):
            job = self._jobs[job_id]
            if job.key == key and not job.state.is_final:
                return job
        return None

    def _queued(self) -> int:
        return sum(1 for job in self._jobs.values() if job.state is JobState.QUEUED)

    def _forget_old(self) -> None:
        """Drops the oldest finished jobs past the retention bound."""
        while len(self._order) > self._retained:
            oldest = next((job_id for job_id in self._order if self._jobs[job_id].state.is_final), None)
            if oldest is None:
                # Everything retained is still in flight. Dropping one would
                # lose a review somebody is waiting for; growing is the lesser
                # evil, and the queue depth already bounds how far.
                return
            self._order.remove(oldest)
            del self._jobs[oldest]


class JobService:
    """Turns a request into a job, and a job into work.

    Args:
        store: Where jobs live.
        max_queue_depth: How many may be waiting.
        clock: Returns now, in UTC. Injected so a test is not timing-bound.
        new_id: Returns a fresh identifier.
    """

    def __init__(
        self,
        store: JobStore,
        max_queue_depth: int = DEFAULT_QUEUE_DEPTH,
        clock: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
    ):
        self._store = store
        self._max_queue_depth = max_queue_depth
        self._clock = clock or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: uuid.uuid4().hex[:12])

    @property
    def max_queue_depth(self) -> int:
        return self._max_queue_depth

    def submit(self, target: ReviewTarget, idempotency_key: str = "") -> tuple[ReviewJob, bool]:
        """Accepts a review, or returns the one already in flight for it."""
        job = ReviewJob(
            job_id=self._new_id(),
            target=target,
            submitted_at=self._clock(),
            idempotency_key=idempotency_key,
        )
        return self._store.submit(job, self._max_queue_depth)

    def get(self, job_id: str) -> ReviewJob | None:
        return self._store.get(job_id)

    def claim(self, trace_id: str = "") -> ReviewJob | None:
        """The next job to run, already moved to running."""
        return self._store.claim_next(self._clock(), trace_id=trace_id)

    def note_trace(self, job: ReviewJob, trace_id: str) -> ReviewJob:
        """Records which trace this job is running under.

        Separate from `claim` because the trace is named after the job, and
        the job's identifier only exists once it has been claimed.
        """
        traced = job.with_trace(trace_id)
        self._store.update(traced)
        return traced

    def complete(self, job: ReviewJob, verdict: str, exit_code: int) -> ReviewJob:
        finished = job.succeeded(self._clock(), verdict=verdict, exit_code=exit_code)
        self._store.update(finished)
        return finished

    def fail(self, job: ReviewJob, reason: str, exit_code: int | None = None) -> ReviewJob:
        failed = job.failed(self._clock(), reason=reason, exit_code=exit_code)
        self._store.update(failed)
        return failed

    @property
    def is_saturated(self) -> bool:
        """Whether the queue is at its depth. Read by the readiness probe."""
        return self._store.queued_count() >= self._max_queue_depth
