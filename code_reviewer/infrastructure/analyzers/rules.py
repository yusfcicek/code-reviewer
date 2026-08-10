"""Every rule id the analysis suite can emit.

Derived from the same enums `suite._rule_id` turns into rule ids, rather than
listed: a hand-written list is a list that drifts from the analyzers, and the
whole point of the coverage figure is that nobody has to count by hand.

In infrastructure because the analyzers are adapters. What to do about a rule
without a recipe is a judgement and lives in `domain/fix_recipes.py`; how many
rules there are is a fact about this deployment's analyzers and lives here.
"""

from .performance import PerformanceIssueType
from .quality import IssueCategory
from .sast import VulnerabilityType
from .semantic import ChangeType

#: The namespace each analyzer's rule enum is qualified with, matching what
#: `suite._rule_id` does.
_NAMESPACES = (
    ("SAST", VulnerabilityType),
    ("QUALITY", IssueCategory),
    ("PERFORMANCE", PerformanceIssueType),
    ("SEMANTIC", ChangeType),
)


def emittable_rules() -> tuple[str, ...]:
    """Every rule id the analysis suite can produce, in sorted order."""
    return tuple(
        sorted(f"{namespace}.{member.value.upper()}" for namespace, enum in _NAMESPACES for member in enum)
    )
