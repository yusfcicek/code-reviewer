"""Running a group of independent pieces of work, and what comes back.

The port the committee submits its specialists through, plus the sequential
runner that is the default. Both live here for the reason `NullTracer` lives
beside `Tracer`: a default that does nothing interesting belongs with the
interface it satisfies, not in an adapter package.

Two properties matter more than speed.

**Order is by plan, not by completion.** Outcomes come back in the order the
tasks were given, whatever order they finished in. That is what lets a report
composed from concurrent work be byte-identical to one composed from sequential
work — and Level 15's fixed composition order is what makes it cheap.

**A task's failure is its own.** An exception inside a task is captured into
that task's outcome. It does not escape `run_all`, and it does not stop the
others: a committee where one agent's timeout costs the other three is a
committee that is worse than one agent.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class TaskOutcome[T]:
    """What one task produced, or why it produced nothing."""

    succeeded: bool
    result: T | None = None
    error_type: str = ""
    timed_out: bool = False
    duration_ms: int = 0

    @property
    def value(self) -> T:
        """The result, or an error.

        Refused rather than returning ``None`` when the task failed: ``None``
        is a value a task may legitimately return, and a reader who cannot
        tell the two apart will eventually write the bug that says they are
        the same.
        """
        if not self.succeeded:
            raise ValueError(f"This task did not produce a value: {self.error_type or 'timed out'}.")
        return cast(T, self.result)

    @classmethod
    def ok(cls, result: T, duration_ms: int = 0) -> "TaskOutcome[T]":
        return cls(succeeded=True, result=result, duration_ms=duration_ms)

    @classmethod
    def failed(cls, error_type: str, duration_ms: int = 0) -> "TaskOutcome[T]":
        return cls(succeeded=False, error_type=error_type, duration_ms=duration_ms)

    @classmethod
    def timeout(cls, seconds: float, duration_ms: int = 0) -> "TaskOutcome[T]":
        return cls(
            succeeded=False,
            error_type=f"timed out after {seconds:g}s",
            timed_out=True,
            duration_ms=duration_ms,
        )


class TaskRunner(ABC):
    """Runs a group of callables and returns one outcome each, in order."""

    @abstractmethod
    def run_all[T](
        self, tasks: Sequence[Callable[[], T]], timeout_s: float | None = None
    ) -> list[TaskOutcome[T]]:
        """Runs every task. Never raises for a task's failure.

        ``timeout_s`` bounds one task. A runner that cannot interrupt a task
        says so in its own documentation rather than pretending to honour it.
        """


class SequentialRunner(TaskRunner):
    """One after another, on this thread. The default, and the old behaviour.

    It cannot honour a timeout. Interrupting a running callable requires
    somewhere else to run, and a runner that quietly ignored the argument
    would be worse than one that says this out loud: a task that hangs here
    hangs the review, exactly as it did before this level existed. Use
    `ThreadPoolRunner` where that matters.
    """

    def run_all[T](
        self, tasks: Sequence[Callable[[], T]], timeout_s: float | None = None
    ) -> list[TaskOutcome[T]]:
        outcomes: list[TaskOutcome[T]] = []
        for task in tasks:
            try:
                outcomes.append(TaskOutcome.ok(task()))
            except Exception as error:
                outcomes.append(TaskOutcome.failed(f"{type(error).__name__}: {error}"))
        return outcomes
