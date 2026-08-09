"""Whether this process can take work, and what is stopping it.

Level 18 shipped `/readyz` with `ready=lambda: (True, "ready")`, because there
was nothing yet to check. A container wired to a probe that always passes is
worse than a container with no probe at all: Kubernetes routes traffic to it
while it is unconfigured (capability C-17).

Two rules make the difference between one deploy and three.

**Every failure is reported, not the first.** A probe that names one missing
variable at a time costs a deploy per variable.

**A reason names the setting, never its value.** `/readyz` is unauthenticated,
and a probe that echoes configuration is a configuration endpoint.
"""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    """One thing that was checked, and how it went."""

    name: str
    passed: bool
    #: Why it failed. Names the setting, never its value.
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.passed and not self.reason:
            raise ValueError(f"Check '{self.name}' failed without saying why.")
        if self.passed and self.reason:
            raise ValueError(f"Check '{self.name}' passed but carries a failure reason.")

    @classmethod
    def ok(cls, name: str) -> "CheckResult":
        return cls(name=name, passed=True)

    @classmethod
    def failed(cls, name: str, reason: str) -> "CheckResult":
        return cls(name=name, passed=False, reason=reason)


@dataclass(frozen=True)
class Readiness:
    """Every check, and the one answer they add up to."""

    results: tuple[CheckResult, ...] = ()

    @property
    def is_ready(self) -> bool:
        """True when nothing failed.

        An empty `Readiness` is ready: a process with nothing to check has
        nothing wrong with it, and defaulting to "not ready" would make the
        first deployment of anything fail for no stated reason.
        """
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """Everything that failed, in check-name order.

        Ordered so two probes of one process read alike; a reason list whose
        order depends on registration is a diff nobody can compare.
        """
        return tuple(
            sorted((result for result in self.results if not result.passed), key=lambda item: item.name)
        )

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(f"{result.name}: {result.reason}" for result in self.failures)

    def summary(self) -> str:
        """One line, naming the failing checks and nothing else."""
        if self.is_ready:
            return "ready"
        return "not ready: " + "; ".join(self.reasons)


def combine(results: Iterable[CheckResult]) -> Readiness:
    return Readiness(results=tuple(results))
