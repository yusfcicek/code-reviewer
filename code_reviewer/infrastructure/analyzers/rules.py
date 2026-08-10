"""Every rule id the analysis suite can emit.

Derived from what `suite.py` actually writes into a rule id, rather than from
the enums that look like they would be used: Level 26 built this list from
`ChangeType`, and the suite never uses `ChangeType` as a rule id at all. It
emits the literal `SEMANTIC.BREAKING_CHANGE` and one namespaced integrity issue
type. So seven rules were claimed as emittable that cannot be emitted, two that
are emitted were absent, and the coverage figure was computed over the wrong
denominator (found by Level 28, step 1 — the third time in this roadmap that
something was written against a mental model of its input).

In infrastructure because the analyzers are adapters. What to do about a rule
without a recipe is a judgement and lives in `domain/fix_recipes.py`; how many
rules there are is a fact about this deployment's analyzers and lives here.
"""

from .performance import PerformanceIssueType
from .quality import IssueCategory
from .sast import VulnerabilityType

#: The namespaces whose rule ids come from an enum the suite reads.
_FROM_ENUMS = (
    ("SAST", VulnerabilityType),
    ("QUALITY", IssueCategory),
    ("PERFORMANCE", PerformanceIssueType),
)

#: What the suite writes under `SEMANTIC`, which is not an enum.
#:
#: `BREAKING_CHANGE` is a literal in `suite.py`. `UNREFERENCED_IN_FILE` is the
#: only `IntegrityIssue.issue_type` the semantic analyzer produces today —
#: `IntegrityIssue`'s own comment names three others (`incomplete_refactor`,
#: `missing_update`, `orphaned_code`) and nothing constructs them, so listing
#: them here would claim a rule that cannot fire.
_SEMANTIC_RULES = ("SEMANTIC.BREAKING_CHANGE", "SEMANTIC.UNREFERENCED_IN_FILE")


def emittable_rules() -> tuple[str, ...]:
    """Every rule id the analysis suite can produce, in sorted order."""
    from_enums = (f"{namespace}.{member.value.upper()}" for namespace, enum in _FROM_ENUMS for member in enum)
    return tuple(sorted({*from_enums, *_SEMANTIC_RULES}))
