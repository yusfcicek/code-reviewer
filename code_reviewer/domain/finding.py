"""The shared result type every analyzer produces.

Each analyzer used to define its own result shape — ``SecurityFinding``,
``QualityIssue``, ``PerformanceIssue`` — with different field names for the same
ideas. A report could therefore not be assembled from more than one analyzer,
and the gate had to recover numbers by parsing the model's prose instead of
reading the values the analyzers had already computed (findings F-28, F-32).
"""

from dataclasses import dataclass, field
from enum import Enum
from functools import total_ordering
from typing import Dict, Iterable, List, Tuple

from .severity import Severity


class FindingCategory(Enum):
    """What kind of problem a finding describes."""

    SECURITY = "security"
    QUALITY = "quality"
    PERFORMANCE = "performance"
    SEMANTIC = "semantic"
    DEPENDENCY = "dependency"


@total_ordering
@dataclass
class Finding:
    """One problem, at one place, with one suggested remedy."""

    category: FindingCategory
    severity: Severity
    file_path: str
    line_number: int
    title: str
    description: str
    remediation: str

    #: Identifier of the rule that produced this finding, when it has one.
    rule_id: str = ""
    #: Common Weakness Enumeration reference, for security findings.
    cwe_id: str = ""
    #: OWASP Top 10 category, for security findings.
    owasp_category: str = ""
    #: The source line that triggered the rule, trimmed for display.
    evidence: str = ""
    #: Rule-specific numbers, e.g. loop depth or method count.
    metrics: Dict = field(default_factory=dict)

    @property
    def location(self) -> str:
        """Human-readable position, as `path:line`."""
        if not self.file_path:
            return "unknown"
        if not self.line_number:
            return self.file_path
        return f"{self.file_path}:{self.line_number}"

    def _sort_key(self) -> Tuple:
        return (self.severity, self.file_path, self.line_number, self.title)

    def __lt__(self, other: "Finding") -> bool:
        if not isinstance(other, Finding):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    @staticmethod
    def count_by_severity(findings: Iterable["Finding"]) -> Dict[Severity, int]:
        """Counts per severity, with every level present so callers can index freely."""
        counts = {severity: 0 for severity in Severity}
        for finding in findings:
            counts[finding.severity] += 1
        return counts

    @staticmethod
    def worst_severity(findings: Iterable["Finding"]) -> Severity:
        """Most severe level present, or INFO when there is nothing to report."""
        severities = [finding.severity for finding in findings]
        return min(severities) if severities else Severity.INFO


@dataclass
class AffectedCode:
    """Code a change reaches without appearing in its diff.

    The same idea was modelled twice — ``dependency_tracker.AffectedCode`` and
    ``memory.strategies.AffectedCodeEntry`` — with different field names, so the
    tracker's output could not be handed to the memory strategy directly
    (finding F-29).
    """

    #: Previews are inlined into the prompt, so they are bounded.
    MAX_PREVIEW_CHARS = 200

    file_path: str
    symbol_name: str
    reason: str
    preview: str = ""
    line_number: int = 0

    def __post_init__(self):
        if self.preview and len(self.preview) > self.MAX_PREVIEW_CHARS:
            self.preview = self.preview[: self.MAX_PREVIEW_CHARS]

    @property
    def identity(self) -> Tuple[str, str]:
        """What makes two entries the same: one symbol in one file."""
        return (self.file_path, self.symbol_name)

    @property
    def location(self) -> str:
        if self.line_number:
            return f"{self.file_path}:{self.line_number}"
        return self.file_path

    def __str__(self) -> str:
        return f"{self.location} `{self.symbol_name}` — {self.reason}"


def deduplicate(entries: Iterable[AffectedCode]) -> List[AffectedCode]:
    """Keeps the first entry per symbol, preserving discovery order."""
    seen = set()
    unique = []
    for entry in entries:
        if entry.identity in seen:
            continue
        seen.add(entry.identity)
        unique.append(entry)
    return unique
