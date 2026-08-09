"""Running the checks a readiness probe is made of.

The probe's whole job is to be more reliable than the thing it reports on, so
it is written defensively in the two places that matter: a check that raises
fails *itself* rather than the probe, and a check that returns something other
than a :class:`CheckResult` is a failed check rather than a corrupt aggregate.

A readiness endpoint that returns 500 because a check had a bug is a readiness
endpoint that takes the deployment down for a reason unrelated to readiness.
"""

import logging
from collections.abc import Callable

from code_reviewer.domain.health import CheckResult, Readiness

logger = logging.getLogger(__name__)

#: What a check is: a name, and a callable that answers about it.
Check = Callable[[], CheckResult]


class ReadinessProbe:
    """Named checks, run on demand.

    Registration order is preserved in the results; the *reasons* are sorted
    by name in the domain, so what a reader sees is stable while what a
    maintainer registered stays readable.
    """

    def __init__(self, checks: dict[str, Check] | None = None):
        self._checks: dict[str, Check] = dict(checks or {})

    def register(self, name: str, check: Check) -> "ReadinessProbe":
        """Adds a check. Returns self, so a builder reads as one expression."""
        self._checks[name] = check
        return self

    @property
    def check_names(self) -> tuple[str, ...]:
        return tuple(self._checks)

    def run(self) -> Readiness:
        """Every check, each isolated from the others."""
        return Readiness(results=tuple(self._run_one(name, check) for name, check in self._checks.items()))

    def as_probe(self) -> Callable[[], tuple[bool, str]]:
        """The `(ready, reason)` pair `ReviewApi` asks for."""

        def probe() -> tuple[bool, str]:
            readiness = self.run()
            return readiness.is_ready, readiness.summary()

        return probe

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _run_one(name: str, check: Check) -> CheckResult:
        try:
            result = check()
        except Exception as error:
            logger.warning("Readiness check %s raised: %s", name, error)
            return CheckResult.failed(name, f"the check raised {type(error).__name__}")

        if not isinstance(result, CheckResult):
            # A check that returns the wrong shape is a bug in the check, and
            # reporting it as one beats letting it through as "ready".
            return CheckResult.failed(name, "the check did not return a result")
        return result
