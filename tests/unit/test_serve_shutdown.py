"""Step 4 — what a SIGTERM does.

Kubernetes sends one and waits thirty seconds. A process that ignores both
loses a review on every rollout.
"""

import signal
import threading
import time
import unittest
from unittest.mock import MagicMock

from code_reviewer.application.jobs import InMemoryJobStore, JobService
from code_reviewer.domain.job import ReviewTarget
from code_reviewer.infrastructure.http.worker import ReviewWorker
from code_reviewer.serve import EXIT_OK, drain, install_signal_handlers


class SlowReviews:
    """A review that takes longer than the caller wants to wait."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.started = threading.Event()

    def review(self, project_id, merge_request_iid, publish=True):
        self.started.set()
        time.sleep(self.seconds)
        raise RuntimeError("never finishes in time")


class TestDraining(unittest.TestCase):
    def test_an_idle_worker_drains_immediately(self):
        worker = ReviewWorker(JobService(InMemoryJobStore()), MagicMock(), poll_seconds=0.01)
        worker.start()

        started = time.monotonic()
        code = drain(worker, seconds=5.0)

        self.assertEqual(code, EXIT_OK)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(worker.is_running)

    def test_a_worker_that_was_never_started_drains(self):
        worker = ReviewWorker(JobService(InMemoryJobStore()), MagicMock())

        self.assertEqual(drain(worker, seconds=0.1), EXIT_OK)

    def test_a_review_that_outlasts_the_bound_is_logged_and_the_process_still_exits(self):
        """A shutdown that waits forever is a pod that gets SIGKILLed anyway,
        with the same review half-run and nothing in the log about it."""
        jobs = JobService(InMemoryJobStore())
        jobs.submit(ReviewTarget(1, 1, "a"))
        reviews = SlowReviews(seconds=3.0)
        worker = ReviewWorker(jobs, reviews, poll_seconds=0.01)
        worker.start()
        self.assertTrue(reviews.started.wait(timeout=2.0))

        with self.assertLogs("code_reviewer.serve", level="WARNING") as captured:
            started = time.monotonic()
            code = drain(worker, seconds=0.2)
            elapsed = time.monotonic() - started

        self.assertEqual(code, EXIT_OK)
        self.assertLess(elapsed, 2.0, "the drain waited past its bound")
        self.assertTrue(any("did not finish" in line for line in captured.output))

    def test_a_clean_drain_says_so(self):
        worker = ReviewWorker(JobService(InMemoryJobStore()), MagicMock(), poll_seconds=0.01)
        worker.start()

        with self.assertLogs("code_reviewer.serve", level="INFO") as captured:
            drain(worker, seconds=2.0)

        self.assertTrue(any("Drained cleanly" in line for line in captured.output))

    def test_draining_twice_is_safe(self):
        worker = ReviewWorker(JobService(InMemoryJobStore()), MagicMock(), poll_seconds=0.01)
        worker.start()

        drain(worker, seconds=2.0)

        self.assertEqual(drain(worker, seconds=2.0), EXIT_OK)


class TestSignalHandlers(unittest.TestCase):
    def setUp(self):
        self.original = {received: signal.getsignal(received) for received in (signal.SIGTERM, signal.SIGINT)}
        self.addCleanup(self._restore)

    def _restore(self):
        for received, handler in self.original.items():
            signal.signal(received, handler)

    def test_both_signals_are_handled(self):
        """SIGTERM is what an orchestrator sends; SIGINT is what a person
        sends. Both mean the same thing here."""
        server = MagicMock()

        install_signal_handlers(server)

        for received in (signal.SIGTERM, signal.SIGINT):
            self.assertNotIn(signal.getsignal(received), (signal.SIG_DFL, signal.SIG_IGN))

    def test_the_handler_asks_the_server_to_stop_from_another_thread(self):
        """`serve_forever` blocks the main thread and `shutdown` waits for that
        loop to notice, so asking from the handler itself would deadlock."""
        server = MagicMock()
        asked = threading.Event()
        server.shutdown.side_effect = lambda: asked.set()

        install_signal_handlers(server)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        self.assertTrue(asked.wait(timeout=2.0))
        self.assertNotEqual(server.shutdown.call_args, None, "the server was never asked to stop")

    def test_a_second_signal_does_not_break_anything(self):
        server = MagicMock()
        install_signal_handlers(server)
        handler = signal.getsignal(signal.SIGTERM)

        handler(signal.SIGTERM, None)
        handler(signal.SIGTERM, None)

        time.sleep(0.05)
        self.assertGreaterEqual(server.shutdown.call_count, 1)


if __name__ == "__main__":
    unittest.main()
