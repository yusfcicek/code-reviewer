"""The shared result type every analyzer produces.

Each analyzer used to define its own result shape — ``SecurityFinding``,
``QualityIssue``, ``PerformanceIssue`` — with different field names for the same
ideas. A report could therefore not be assembled from more than one analyzer,
and the gate had to recover numbers by parsing the model's prose instead of
reading the values the analyzers had already computed (findings F-28, F-32).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from functools import total_ordering
from types import MappingProxyType
from typing import Any

from .severity import Severity


class FindingCategory(Enum):
    """What kind of problem a finding describes."""

    SECURITY = "security"
    QUALITY = "quality"
    PERFORMANCE = "performance"
    SEMANTIC = "semantic"
    DEPENDENCY = "dependency"


class DependencyType(Enum):
    """How one piece of code depends on another."""

    DIRECT_CALL = "direct_call"
    INHERITANCE = "inheritance"
    COMPOSITION = "composition"
    IMPORT = "import"
    TYPE_USAGE = "type_usage"
    DATA_STRUCTURE = "data_structure"


#: Shared empty mapping for findings that carry no rule-specific numbers.
_NO_METRICS: Mapping[str, Any] = MappingProxyType({})


@total_ordering
@dataclass(frozen=True)
class Finding:
    """One problem, at one place, with one suggested remedy.

    A *value*: immutable, equal by content and hashable. Deduplication needs a
    key, and a key needs to hash — two detectors reporting one problem at one
    line under one rule is one problem, and collapsing them is only possible if
    findings behave like values (finding G-08).
    """

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
    #: Rule-specific numbers, e.g. loop depth or method count. Stored as an
    #: immutable mapping: a mutable field inside a value object makes it a
    #: value object in name only, and an unhashable one in practice.
    metrics: Mapping[str, Any] = field(default_factory=lambda: _NO_METRICS)

    def __post_init__(self) -> None:
        # Callers pass an ordinary dict, which is the convenient thing to
        # write. It is wrapped here rather than at every construction site.
        if not isinstance(self.metrics, MappingProxyType):
            object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    def __hash__(self) -> int:
        # `metrics` is a mapping and mappings are not hashable, so it is left
        # out of the hash. Equality still considers it — findings that differ
        # only in their metrics collide in a bucket and are told apart by
        # `__eq__`, which is exactly what a hash is allowed to do.
        return hash((self.rule_id, self.file_path, self.line_number, self.title, self.severity))

    @property
    def namespace(self) -> str:
        """The leading segment of the rule id, e.g. ``SAST``.

        Empty when the id carries no namespace. Level 11's suppression globs
        match on this, and a bare id gives them nothing to match.
        """
        return self.rule_id.split(".", 1)[0] if "." in self.rule_id else ""

    @property
    def location(self) -> str:
        """Human-readable position, as `path:line`."""
        if not self.file_path:
            return "unknown"
        if not self.line_number:
            return self.file_path
        return f"{self.file_path}:{self.line_number}"

    def _sort_key(self) -> tuple:
        return (self.severity, self.file_path, self.line_number, self.title)

    def __lt__(self, other: "Finding") -> bool:
        if not isinstance(other, Finding):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    @staticmethod
    def count_by_severity(findings: Iterable["Finding"]) -> dict[Severity, int]:
        """Counts per severity, with every level present so callers can index freely."""
        counts = dict.fromkeys(Severity, 0)
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
    reason: str = ""
    #: How the affected code depends on what changed, when it is known.
    dependency_type: DependencyType | None = None
    #: The source line where the dependency was observed.
    context: str = ""
    preview: str = ""
    line_number: int = 0

    def __post_init__(self):
        if self.preview and len(self.preview) > self.MAX_PREVIEW_CHARS:
            self.preview = self.preview[: self.MAX_PREVIEW_CHARS]

    @property
    def identity(self) -> tuple[str, str]:
        """What makes two entries the same: one symbol in one file."""
        return (self.file_path, self.symbol_name)

    @property
    def location(self) -> str:
        if self.line_number:
            return f"{self.file_path}:{self.line_number}"
        return self.file_path

    def __str__(self) -> str:
        return f"{self.location} `{self.symbol_name}` — {self.reason}"


def deduplicate(entries: Iterable[AffectedCode]) -> list[AffectedCode]:
    """Keeps the first entry per symbol, preserving discovery order."""
    seen = set()
    unique = []
    for entry in entries:
        if entry.identity in seen:
            continue
        seen.add(entry.identity)
        unique.append(entry)
    return unique
