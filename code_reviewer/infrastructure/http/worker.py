"""The thread that turns queued jobs into reviews.

One worker, one thread, one job at a time. Not a pool: a review already spends
its concurrency inside itself (Level 17), and running two whole reviews at once
would double the memory, the model spend and the number of things a failure can
be about, for a service whose queue depth is the thing that actually bounds
load.

The worker owns exactly two rules. A job that raises is *recorded* as failed
rather than lost, and the loop keeps draining — a worker that dies on one bad
merge request takes the service down with it. And it polls rather than blocking
inside the store, because a worker that waits inside a lock is a worker that
cannot be told to stop.
"""

import logging
import threading

from code_reviewer.application.jobs import JobService
from code_reviewer.application.review_service import ReviewService
from code_reviewer.infrastructure.observability.tracer import SpanRecorder, set_tracer

logger = logging.getLogger(__name__)

#: How long the loop sleeps when there is nothing to do. Short enough that a
#: submitted review starts promptly, long enough that an idle service is idle.
DEFAULT_POLL_SECONDS = 0.25


class ReviewWorker:
    """Drains the queue, one review at a time.

    Args:
        jobs: Where work is claimed and outcomes are recorded.
        reviews: What a claimed job is run through.
        poll_seconds: How long to wait when the queue is empty.
    """

    def __init__(
        self,
        jobs: JobService,
        reviews: ReviewService,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ):
        self._jobs = jobs
        self._reviews = reviews
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Runs the loop on its own thread. Idempotent."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self.run, name="review-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        """Asks the loop to finish and waits for it.

        Returns whether it actually finished. The caller needs to know which
        of "drained" and "gave up" happened: a shutdown that waits forever is
        a pod that gets SIGKILLed anyway, with the same review half-run and no
        record of it (Level 19, decision D-5).
        """
        self._stop.set()
        if self._thread is None:
            return True

        self._thread.join(timeout=timeout)
        drained = not self._thread.is_alive()
        if drained:
            self._thread = None
        return drained

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(self) -> None:
        """The loop. Runs until :meth:`stop`."""
        while not self._stop.is_set():
            if not self.run_once():
                # `Event.wait` rather than `sleep`, so a stop is acted on
                # immediately rather than after the poll interval.
                self._stop.wait(self._poll_seconds)

    # -- one job ------------------------------------------------------------

    def run_once(self) -> bool:
        """Claims and runs one job. ``False`` when there was nothing to do."""
        job = self._jobs.claim()
        if job is None:
            return False

        # Each job gets its own trace, named after what it is reviewing *and*
        # which job it is, so a log line from one review cannot be mistaken for
        # another's — including a re-review of the same merge request.
        trace_id = f"{job.target.project_id}-{job.target.merge_request_iid}-{job.job_id}"
        job = self._jobs.note_trace(job, trace_id)
        set_tracer(SpanRecorder(trace_id=trace_id))

        try:
            result = self._reviews.review(job.target.project_id, job.target.merge_request_iid, publish=True)
        except Exception as error:
            # Recorded, not lost. A worker that dies on one bad merge request
            # takes the service down with it.
            logger.exception("Review job %s failed", job.job_id)
            self._jobs.fail(job, reason=f"{type(error).__name__}: {error}")
            return True
        finally:
            set_tracer(None)

        self._jobs.complete(job, verdict=result.outcome.result.value, exit_code=result.exit_code)
        return True
