"""The single severity scale used across the whole system.

Three enums used to describe this concept — one per analyzer — which made it
impossible to aggregate findings, sort them together or compare them against a
policy threshold (finding F-28).

``Severity`` is ordered, with the *most* severe comparing as the smallest, so
``sorted(findings)`` and ``min(severities)`` do the obvious thing without a key
function.
"""

from enum import Enum
from functools import total_ordering


@total_ordering
class Severity(Enum):
    """How much a finding matters, from CRITICAL down to INFO."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    def __lt__(self, other: "Severity") -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return _ORDER[self] < _ORDER[other]

    def __str__(self) -> str:
        return self.value

    @property
    def weight(self) -> int:
        """Score contribution used when reducing findings to a single number."""
        return _WEIGHT[self]

    def is_at_least(self, threshold: "Severity") -> bool:
        """True when this severity is as severe as ``threshold`` or worse."""
        return _ORDER[self] <= _ORDER[threshold]

    @classmethod
    def parse(cls, raw: str | None, default: "Severity | None" = None) -> "Severity":
        """Reads a severity from free text, falling back rather than raising.

        Severities arrive from YAML policy files and from model output, neither
        of which is guaranteed to be well formed. A bad value should degrade the
        finding, not abort the review.
        """
        fallback = default if default is not None else cls.INFO
        if not raw:
            return fallback
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return fallback


#: Ordering rank; lower is more severe.
_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

#: Score contribution per finding. Chosen so that a single CRITICAL finding
#: exhausts a 100-point budget on its own, while LOW findings accumulate.
_WEIGHT = {
    Severity.CRITICAL: 25,
    Severity.HIGH: 15,
    Severity.MEDIUM: 5,
    Severity.LOW: 2,
    Severity.INFO: 0,
}
