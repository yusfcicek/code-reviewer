"""Grading what the analyzers produced against what a case says they should.

Eleven levels made this agent stricter. None of them could say whether it
reviews code *well*: coverage proves the code ran, the metrics export counts
what was produced, and the dogfooding test proves the package does not block
itself. A team deciding whether to turn the gate on asks a different question —
when it reports a vulnerability, is one there, and when it stays quiet, is the
file clean (capability C-01).

Answering that needs ground truth, and ground truth needs a rule for when a
produced finding *is* the expected one. That rule is here rather than in the
harness for the same reason `gate.py` is here: it turns findings into a
verdict, needs no filesystem and no model, and every edge case in it is
settled by arithmetic rather than by I/O.

Three properties are deliberate.

**Assignment is one-to-one.** An expectation consumes at most one finding and a
finding satisfies at most one expectation, so a rule firing twice at one line
cannot inflate recall.

**Nothing is silently dropped.** A finding the case does not grade is counted
as *ungraded* and its rule id is reported. Narrowing a case's scope therefore
trades a possible false positive for a visible admission — the same bargain
suppression makes at Level 11, made the same way.

**A miss and a misgrade are different events.** A rule that fires at the wrong
severity has fired; charging it as both a false negative and a false positive
would move two numbers for one defect (contract C-3).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .finding import Finding
from .severity import Severity

#: A scope entry meaning "grade every rule".
EVERYTHING = "*"


@dataclass(frozen=True)
class ConfusionMatrix:
    """Counts of the three ways a graded run can turn out.

    The ratios treat an empty denominator as 1.0, not as 0.0 and not as an
    error. A fixture with nothing to find on which the suite stayed quiet is
    the behaviour the dataset wants most, and scoring it zero would make
    adding such a case *lower* the run's F1.
    """

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    def __post_init__(self) -> None:
        if min(self.true_positives, self.false_positives, self.false_negatives) < 0:
            raise ValueError("a confusion matrix counts events, and there cannot be fewer than none")

    @property
    def precision(self) -> float:
        """Of what was reported, how much was real."""
        reported = self.true_positives + self.false_positives
        return self.true_positives / reported if reported else 1.0

    @property
    def recall(self) -> float:
        """Of what was there, how much was reported."""
        present = self.true_positives + self.false_negatives
        return self.true_positives / present if present else 1.0

    @property
    def f1(self) -> float:
        """Harmonic mean of the two, and therefore always between them."""
        precision, recall = self.precision, self.recall
        total = precision + recall
        return 2 * precision * recall / total if total else 0.0

    def __add__(self, other: "ConfusionMatrix") -> "ConfusionMatrix":
        if not isinstance(other, ConfusionMatrix):
            return NotImplemented
        return ConfusionMatrix(
            true_positives=self.true_positives + other.true_positives,
            false_positives=self.false_positives + other.false_positives,
            false_negatives=self.false_negatives + other.false_negatives,
        )

    @staticmethod
    def total(matrices: Iterable["ConfusionMatrix"]) -> "ConfusionMatrix":
        """Component-wise sum, starting from the empty matrix."""
        result = ConfusionMatrix()
        for matrix in matrices:
            result = result + matrix
        return result


@dataclass(frozen=True)
class ExpectedFinding:
    """One finding a case says the suite should produce.

    ``severity`` is optional. Stating it turns the expectation into a claim
    about the grade as well as the location, which is what pins a rule that
    might otherwise be quietly downgraded.
    """

    rule_id: str
    line_number: int
    severity: Severity | None = None


@dataclass(frozen=True)
class ForbiddenFinding:
    """One finding a case says the suite must *not* produce.

    Where a fixed false positive is pinned so it cannot return. ``line_number``
    of zero means "anywhere in the fixture".
    """

    rule_id: str
    line_number: int = 0

    def covers(self, finding: Finding) -> bool:
        if finding.rule_id != self.rule_id:
            return False
        return self.line_number == 0 or finding.line_number == self.line_number


@dataclass(frozen=True)
class EvaluationCase:
    """One annotated fixture: what should be found on it, and what must not."""

    name: str
    file_path: str
    expected: tuple[ExpectedFinding, ...] = ()
    forbidden: tuple[ForbiddenFinding, ...] = ()
    #: Rule-id globs this case takes responsibility for. The default grades
    #: everything, because the permissive default is the strict direction: an
    #: author must actively narrow it, and the narrowing is then visible as an
    #: ungraded count (decision D-3).
    scope: tuple[str, ...] = (EVERYTHING,)
    #: How far from the stated line a finding may be and still be the same
    #: finding. Zero unless a case says otherwise.
    line_tolerance: int = 0

    def grades(self, rule_id: str) -> bool:
        """Whether this case takes responsibility for ``rule_id``.

        A rule the case writes an expectation for is graded whatever the
        scope says. A case that expects a rule and excludes it is
        contradicting itself, and honouring the expectation is the reading
        that cannot hide a defect.
        """
        if any(expectation.rule_id == rule_id for expectation in self.expected):
            return True
        return any(_selects(selector, rule_id) for selector in self.scope)


@dataclass(frozen=True)
class SeverityMismatch:
    """A rule that fired where it should have, at the wrong grade."""

    expected: ExpectedFinding
    found: Finding


@dataclass(frozen=True)
class CaseResult:
    """What grading one case produced."""

    case: EvaluationCase
    matched: tuple[tuple[ExpectedFinding, Finding], ...] = ()
    missed: tuple[ExpectedFinding, ...] = ()
    mismatched: tuple[SeverityMismatch, ...] = ()
    spurious: tuple[Finding, ...] = ()
    forbidden_seen: tuple[Finding, ...] = ()
    ungraded: tuple[Finding, ...] = ()

    @property
    def matrix(self) -> ConfusionMatrix:
        return ConfusionMatrix(
            true_positives=len(self.matched),
            # A forbidden finding is a false positive by construction: the
            # case states it is not there.
            false_positives=len(self.spurious) + len(self.forbidden_seen),
            false_negatives=len(self.missed) + len(self.mismatched),
        )

    @property
    def ungraded_rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted({finding.rule_id for finding in self.ungraded}))


@dataclass(frozen=True)
class CaseError:
    """A case that could not be graded at all.

    Distinct from a case that scored badly, and it must stay distinct: "the
    analyzer crashed" and "the analyzer found nothing" are different facts,
    and only one of them is a measurement (contract C-9).
    """

    name: str
    reason: str


@dataclass(frozen=True)
class EvaluationReport:
    """Every case's result, and the numbers derived from them."""

    results: tuple[CaseResult, ...] = ()
    errors: tuple[CaseError, ...] = ()

    @property
    def case_count(self) -> int:
        return len(self.results)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def overall(self) -> ConfusionMatrix:
        return ConfusionMatrix.total(result.matrix for result in self.results)

    @property
    def by_rule(self) -> dict[str, ConfusionMatrix]:
        """One matrix per rule id, keyed in sorted order.

        An overall F1 of 0.9 hiding a single rule at 0.2 is the failure mode a
        single number has. These sum back to :attr:`overall`, which is checked
        as a property rather than asserted here.
        """
        buckets: dict[str, ConfusionMatrix] = {}

        def add(rule_id: str, matrix: ConfusionMatrix) -> None:
            buckets[rule_id] = buckets.get(rule_id, ConfusionMatrix()) + matrix

        for result in self.results:
            for expectation, _ in result.matched:
                add(expectation.rule_id, ConfusionMatrix(true_positives=1))
            for expectation in result.missed:
                add(expectation.rule_id, ConfusionMatrix(false_negatives=1))
            for mismatch in result.mismatched:
                add(mismatch.expected.rule_id, ConfusionMatrix(false_negatives=1))
            for finding in (*result.spurious, *result.forbidden_seen):
                add(finding.rule_id, ConfusionMatrix(false_positives=1))

        return {rule_id: buckets[rule_id] for rule_id in sorted(buckets)}

    @property
    def ungraded_count(self) -> int:
        return sum(len(result.ungraded) for result in self.results)

    @property
    def ungraded_rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted({rule_id for result in self.results for rule_id in result.ungraded_rule_ids}))


@dataclass(frozen=True)
class EvaluationThreshold:
    """The floors a run must clear, and what it means to fail one."""

    min_precision: float = 0.0
    min_recall: float = 0.0
    min_f1: float = 0.0

    def shortfalls(self, report: EvaluationReport) -> list[str]:
        """Every reason this report is not acceptable, in reading order."""
        reasons = [f"case '{error.name}' could not be graded — {error.reason}" for error in report.errors]

        if not report.results:
            # Every ratio is 1.0 over an empty run, which is arithmetic rather
            # than evidence.
            reasons.append("no cases were graded, so the scores mean nothing")
            return reasons

        matrix = report.overall
        for name, value, floor in (
            ("precision", matrix.precision, self.min_precision),
            ("recall", matrix.recall, self.min_recall),
            ("f1", matrix.f1, self.min_f1),
        ):
            # A hair of tolerance, so a floor of 0.9 is not breached by a
            # value that is 0.9 in every way except its last binary digit.
            if value < floor - 1e-9:
                reasons.append(f"{name} {value:.2f} is below the floor of {floor:.2f}")

        return reasons

    def is_met(self, report: EvaluationReport) -> bool:
        return not self.shortfalls(report)


def grade(case: EvaluationCase, findings: Sequence[Finding]) -> CaseResult:
    """Judges what the suite produced on one fixture against what was asked for.

    Expectations are satisfied in the order written, each claiming its best
    remaining candidate. "Best" prefers a finding whose severity matches over
    a nearer one that does not: severity is part of what is being matched, so
    claiming a misgraded finding while a correctly graded one is available
    would report a false negative on a suite that behaved correctly.
    """
    remaining = list(findings)
    matched: list[tuple[ExpectedFinding, Finding]] = []
    missed: list[ExpectedFinding] = []
    mismatched: list[SeverityMismatch] = []

    for expectation in case.expected:
        candidate = _claim(expectation, remaining, case.line_tolerance)
        if candidate is None:
            missed.append(expectation)
            continue

        remaining.remove(candidate)
        if expectation.severity is None or candidate.severity is expectation.severity:
            matched.append((expectation, candidate))
        else:
            mismatched.append(SeverityMismatch(expected=expectation, found=candidate))

    spurious: list[Finding] = []
    forbidden_seen: list[Finding] = []
    ungraded: list[Finding] = []

    for finding in remaining:
        if any(rule.covers(finding) for rule in case.forbidden):
            forbidden_seen.append(finding)
        elif case.grades(finding.rule_id):
            spurious.append(finding)
        else:
            ungraded.append(finding)

    return CaseResult(
        case=case,
        matched=tuple(matched),
        missed=tuple(missed),
        mismatched=tuple(mismatched),
        spurious=tuple(spurious),
        forbidden_seen=tuple(forbidden_seen),
        ungraded=tuple(ungraded),
    )


# -- internals --------------------------------------------------------------


def _claim(expectation: ExpectedFinding, remaining: Sequence[Finding], tolerance: int) -> Finding | None:
    """The finding this expectation takes, or ``None`` if nothing is eligible."""
    candidates = [
        finding
        for finding in remaining
        if finding.rule_id == expectation.rule_id
        and abs(finding.line_number - expectation.line_number) <= tolerance
    ]
    if not candidates:
        return None

    def rank(finding: Finding) -> tuple[int, int, int]:
        graded_right = expectation.severity is None or finding.severity is expectation.severity
        # Ties resolve to the lower line number, so the result does not depend
        # on the order the analyzers happened to run in.
        distance = abs(finding.line_number - expectation.line_number)
        return (0 if graded_right else 1, distance, finding.line_number)

    return min(candidates, key=rank)


def _selects(selector: str, rule_id: str) -> bool:
    """Whether a scope entry covers ``rule_id``.

    The glob vocabulary is the one `suppression.py` already uses — an exact id
    or a `NAMESPACE.*` — with the difference that a bare `*` is accepted here.
    There it would silence everything; here it grades everything, and the
    permissive reading is the strict one.
    """
    if selector == EVERYTHING:
        return True
    if selector.endswith(".*"):
        return rule_id.startswith(f"{selector[:-1]}")
    return selector == rule_id
