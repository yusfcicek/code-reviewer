"""A bounded pool of threads, for work that is almost entirely waiting.

Four specialists reviewing one file make four to forty network round trips,
and the process is blocked for all of them. Threads release the interpreter
lock across a socket read, so the waiting overlaps; a process pool would add
pickling to a problem that does not have one, and `asyncio` would turn every
port in this repository async in order to await two libraries that are
synchronous anyway (decision D-1).

The honest part of this module is the timeout. Python cannot kill a thread. A
task past its deadline is **abandoned**, not cancelled: the runner stops
waiting, reports the timeout, and refuses to reuse the pool, because the hung
worker is still in it holding whatever it was holding. Calling that
"cancelled" would be a lie that costs somebody an afternoon (decision D-3).
"""

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor

from code_reviewer.application.tasks import TaskOutcome, TaskRunner

logger = logging.getLogger(__name__)

#: How long one task may take before it is abandoned. Generous: an agent with
#: a large budget makes several model calls, and a timeout that fires on a
#: healthy run is a timeout that gets raised until it never fires.
DEFAULT_TASK_TIMEOUT_SECONDS = 180.0

#: Threads in one pool. Four is the committee's size; more would only queue.
DEFAULT_MAX_WORKERS = 4


class ThreadPoolRunner(TaskRunner):
    """Runs tasks on a bounded pool, in submission order out.

    Args:
        max_workers: How many tasks may be in flight at once.
        default_timeout_s: Applied when a caller does not name one.
    """

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        default_timeout_s: float | None = DEFAULT_TASK_TIMEOUT_SECONDS,
    ):
        if max_workers < 1:
            raise ValueError("A pool needs at least one worker.")
        self.max_workers = max_workers
        self.default_timeout_s = default_timeout_s
        self._pool: ThreadPoolExecutor | None = None
        self._tainted = False

    @property
    def is_tainted(self) -> bool:
        """Whether a task was abandoned in this pool and it must be replaced."""
        return self._tainted

    def run_all[T](
        self, tasks: Sequence[Callable[[], T]], timeout_s: float | None = None
    ) -> list[TaskOutcome[T]]:
        if not tasks:
            return []

        deadline_s = self.default_timeout_s if timeout_s is None else timeout_s
        pool = self._acquire_pool()
        started = time.monotonic()

        # Submitted in order; collected in order. The futures list *is* the
        # plan, which is what keeps the result independent of who finished
        # first (contract C-2).
        futures: list[Future] = [pool.submit(task) for task in tasks]
        deadline = None if deadline_s is None else started + deadline_s

        return [self._collect(future, deadline, deadline_s, started) for future in futures]

    # -- internals ----------------------------------------------------------

    def _acquire_pool(self) -> ThreadPoolExecutor:
        """The pool, replacing it if a task was abandoned in the last one."""
        if self._pool is None or self._tainted:
            if self._tainted:
                logger.warning(
                    "Replacing the worker pool: a task was abandoned and its thread cannot be reclaimed"
                )
                # Not waited on: waiting is exactly what the timeout said not
                # to do, and the thread is left to finish or not on its own.
                self._pool.shutdown(wait=False) if self._pool else None
            self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="review")
            self._tainted = False
        return self._pool

    def _collect[T](
        self, future: Future, deadline: float | None, deadline_s: float | None, started: float
    ) -> TaskOutcome[T]:
        """One task's outcome, waiting no longer than the group's deadline.

        The remaining time is computed against a deadline shared by the whole
        group rather than restarting per task, so ten hung tasks cost one
        timeout rather than ten.
        """
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())

        try:
            result = future.result(timeout=remaining)
        except TimeoutError:
            self._tainted = True
            logger.warning("A task was abandoned after %.0fs", deadline_s or 0)
            return TaskOutcome.timeout(deadline_s or 0.0, _elapsed_ms(started))
        except Exception as error:
            return TaskOutcome.failed(f"{type(error).__name__}: {error}", _elapsed_ms(started))

        return TaskOutcome.ok(result, _elapsed_ms(started))

    def shutdown(self) -> None:
        """Releases the pool. Safe to call more than once."""
        if self._pool is not None:
            self._pool.shutdown(wait=not self._tainted)
            self._pool = None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
