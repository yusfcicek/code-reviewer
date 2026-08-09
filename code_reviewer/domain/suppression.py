"""Silencing a finding, narrowly and with a reason.

Every static analyzer produces false positives; one that does not is not
looking hard enough. Without a way to suppress, a team facing a single
misfiring rule has two options — turn the rule off in the policy, or stop the
gate from blocking — and both end the tool's usefulness. Suppression exists so
that the narrow answer is available to someone who would otherwise reach for a
wide one (finding G-07).

Which means its whole design is about *not* becoming that wide answer:

- **One line, or one file.** No ranges, no severity thresholds, no path globs
  in policy. The cost of a suppression stays proportional to what it silences.
- **A named rule.** `SAST.SQL_INJECTION`, or the namespace `SAST.*`. A bare
  `*` is rejected: suppressing everything is the second off-switch arriving
  through a different door.
- **A written reason**, captured and reported.
- **A count.** Suppressed findings are returned alongside kept ones, because a
  suppression nobody can see is indistinguishable from a rule that never
  fired.

This lives in the domain, next to `triage.py`, for the same reason that does:
the comment syntax is not incidental to the rule, it *is* the rule's interface,
and deciding whether a directive covers a finding needs no filesystem and no
model.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from code_reviewer.domain.finding import Finding

#: ``# review-ignore: RULE[, RULE...][ - reason]``, or the ``-file`` variant.
#:
#: The rule list accepts identifier characters, dots and a trailing ``.*``. It
#: deliberately cannot match a lone ``*``: the leading character class requires
#: a letter or an underscore.
_DIRECTIVE = re.compile(
    r"(?:#|//)\s*review-ignore(?P<file>-file)?\s*:\s*"
    r"(?P<rules>[A-Za-z_][A-Za-z0-9_.*]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_.*]*)*)"
    r"(?:\s*[-—:]\s*(?P<reason>.*))?$",
    re.IGNORECASE,
)

#: Line number standing for "every line in this file".
FILE_SCOPE = -1


@dataclass(frozen=True)
class SuppressionDirective:
    """One instruction to ignore one rule, somewhere."""

    rule_id: str
    """The rule named, or a namespace glob such as ``SAST.*``."""

    reason: str = ""

    line: int = 0
    """Where the directive was written. The report points here, so a reader
    can find the sentence explaining the silence rather than the code it
    excused."""

    target_line: int = 0
    """Which line it covers. Equal to :attr:`line` for a trailing comment, one
    greater for a standalone one, and ignored entirely when ``file_level``."""

    file_level: bool = False

    @property
    def is_explained(self) -> bool:
        """Whether a reason was given.

        A directive without one still suppresses — refusing would turn a typo
        into a blocking finding at the exact moment someone is trying to
        unblock themselves — but the absence is reported, and the dogfooding
        test refuses to accept any (decision D-3).
        """
        return bool(self.reason)

    def covers(self, finding: Finding) -> bool:
        """Whether this directive names ``finding``'s rule."""
        if self.rule_id.endswith(".*"):
            return finding.namespace == self.rule_id[:-2]
        return finding.rule_id == self.rule_id


@dataclass(frozen=True)
class SuppressedFinding:
    """A finding and the directive that silenced it."""

    finding: Finding
    directive: SuppressionDirective


@dataclass(frozen=True)
class DegradedAnalyzer:
    """An analyzer that could not run, and why.

    Zero findings from an analyzer that crashed is not the same fact as zero
    findings from one that ran, and only one of them is evidence (ADR 0011).
    """

    analyzer: str
    reason: str


@dataclass(frozen=True)
class SuppressionResult:
    """What survived, what did not, and what never ran."""

    findings: list[Finding] = field(default_factory=list)
    suppressed: list[SuppressedFinding] = field(default_factory=list)
    #: Analyzers that raised. Empty on a healthy run; never a reason to fail
    #: the analysis of the file, always a reason to say so.
    degraded: list[DegradedAnalyzer] = field(default_factory=list)

    @property
    def suppressed_count(self) -> int:
        return len(self.suppressed)

    @property
    def unexplained(self) -> list[SuppressedFinding]:
        """Suppressions with no reason written. Worth surfacing in review."""
        return [item for item in self.suppressed if not item.directive.is_explained]


def parse_directives(source: str) -> list[SuppressionDirective]:
    """Every suppression directive in ``source``, in the order written."""
    if not source:
        return []

    directives: list[SuppressionDirective] = []
    for index, line in enumerate(source.split("\n"), start=1):
        directives.extend(_parse_line(line, index))
    return directives


def apply_suppressions(findings: Sequence[Finding], source: str) -> SuppressionResult:
    """Splits ``findings`` into those that stand and those that were silenced.

    Both halves are returned. Dropping the suppressed ones would make a
    silenced rule and an inert rule look identical from the outside, which is
    the state this mechanism exists to avoid creating.
    """
    directives = parse_directives(source)
    if not directives:
        return SuppressionResult(findings=list(findings))

    by_line: dict[int, list[SuppressionDirective]] = {}
    for parsed in directives:
        key = FILE_SCOPE if parsed.file_level else parsed.target_line
        by_line.setdefault(key, []).append(parsed)

    kept: list[Finding] = []
    suppressed: list[SuppressedFinding] = []

    for finding in findings:
        applicable = [*by_line.get(FILE_SCOPE, ()), *by_line.get(finding.line_number, ())]
        directive: SuppressionDirective | None = next((d for d in applicable if d.covers(finding)), None)

        if directive is None:
            kept.append(finding)
        else:
            suppressed.append(SuppressedFinding(finding=finding, directive=directive))

    return SuppressionResult(findings=kept, suppressed=suppressed)


# -- internals --------------------------------------------------------------


def _parse_line(line: str, number: int) -> list[SuppressionDirective]:
    """Directives written on one source line."""
    match = _DIRECTIVE.search(line)
    if match is None:
        return []

    reason = (match.group("reason") or "").strip()
    file_level = bool(match.group("file"))
    stripped = line.strip()
    # A comment on its own line documents what comes *next*; one trailing a
    # statement documents that statement.
    standalone = stripped.startswith("#") or stripped.startswith("//")

    rules = [rule.strip() for rule in match.group("rules").split(",") if rule.strip()]

    return [
        SuppressionDirective(
            rule_id=rule,
            reason=reason,
            line=number,
            target_line=number + 1 if standalone and not file_level else number,
            file_level=file_level,
        )
        for rule in rules
        if rule != "*"
    ]
