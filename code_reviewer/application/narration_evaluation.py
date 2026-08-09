"""Running every check over every recorded review, and reporting what held.

The second harness. Level 12's grades what the analyzers *found*; this grades
what the model *said* about it. They are deliberately separate objects rather
than two columns of one report: the first is a confusion matrix over findings,
the second is a pass rate over checks, and forcing one shape onto both would
make each read the other's empty fields (decision D-5).

Nothing here calls a model. The corpus holds recorded output, so a change in the
score is a change in the checks or in what somebody recorded — which is what
makes a *regression* detectable rather than a variance measurement wearing its
clothes (decision D-2).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from code_reviewer.domain.narration import CHECKS, CheckResult, NarrationCase


@dataclass(frozen=True)
class GradedNarration:
    """One recorded review, and how it did against every check.

    What is scored is **agreement with the expectation**, not the raw pass. A
    case that declares a defect and exhibits it is the harness working; the
    same case coming out clean means the check stopped working, or somebody
    fixed the review and did not say so.
    """

    case: str
    results: tuple[CheckResult, ...]
    expected_failures: tuple[str, ...] = ()

    def agrees(self, result: CheckResult) -> bool:
        return result.passed is (result.check not in self.expected_failures)

    @property
    def passed(self) -> bool:
        return all(self.agrees(result) for result in self.results)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """Checks whose outcome disagreed with what the case declared."""
        return tuple(
            result if not result.passed else _unmet_expectation(result)
            for result in self.results
            if not self.agrees(result)
        )


@dataclass(frozen=True)
class NarrationFailure:
    """One check, on one case, and why it failed.

    Flattened out of the graded cases because this is what a reader acts on:
    the report's job is to name the review, the check and the substring, in one
    line each.
    """

    case: str
    check: str
    detail: str


@dataclass(frozen=True)
class NarrationReport:
    """What a corpus scored, and everything that qualifies the number."""

    graded: tuple[GradedNarration, ...] = ()
    #: Cases recorded under a prompt other than the one in use. Reported rather
    #: than folded into the score: an older prompt does not make a citation
    #: less grounded, but a floor held entirely by old recordings is a floor
    #: holding nothing (decision D-4).
    stale: tuple[str, ...] = ()

    @property
    def case_count(self) -> int:
        return len(self.graded)

    @property
    def check_count(self) -> int:
        return sum(len(graded.results) for graded in self.graded)

    @property
    def score(self) -> float:
        """The share of checks that passed, across the whole corpus.

        Per check rather than per case: a review with one flaw is not as wrong
        as a review with five, and a per-case score cannot say so.

        An empty corpus scores ``0.0`` rather than ``1.0``. Nothing passing
        everything is precisely the failure a floor exists to catch, and
        Level 12's "an empty denominator is 1.0" rule does not transfer —
        there, an empty case was a fixture the analyzers correctly stayed quiet
        about; here, an empty corpus is a harness with nothing in it.
        """
        if not self.check_count:
            return 0.0
        agreed = sum(1 for graded in self.graded for result in graded.results if graded.agrees(result))
        return agreed / self.check_count

    @property
    def failures(self) -> tuple[NarrationFailure, ...]:
        return tuple(
            NarrationFailure(case=graded.case, check=result.check, detail=result.detail)
            for graded in self.graded
            for result in graded.failures
        )

    def rate_for(self, check: str) -> float:
        """The share of cases that passed one named check.

        The number that answers "what did this prompt change break", which is
        the question the whole level exists for.
        """
        pairs = [
            (graded, result) for graded in self.graded for result in graded.results if result.check == check
        ]
        if not pairs:
            return 0.0
        return sum(1 for graded, result in pairs if graded.agrees(result)) / len(pairs)


class NarrationEvaluator:
    """Grades recorded reviews against the checks.

    Deliberately not injected with the checks: they are the level's subject
    matter, and a configurable set would let a caller raise a score by grading
    less — the same trade Level 12 refused when it made an ungraded finding a
    counted, named event rather than a silent one.
    """

    def evaluate(self, cases: Sequence[NarrationCase], current_fingerprint: str = "") -> NarrationReport:
        """Every check over every case, in the order both were given."""
        graded = tuple(
            GradedNarration(
                case=case.name,
                results=tuple(check(case) for check in CHECKS),
                expected_failures=case.expected_failures,
            )
            for case in cases
        )
        stale = tuple(
            case.name
            for case in cases
            if current_fingerprint and case.prompt_fingerprint != current_fingerprint
        )
        return NarrationReport(graded=graded, stale=stale)


def _unmet_expectation(result: CheckResult) -> CheckResult:
    """A check that passed where the case said it would not.

    Reported as a failure of the *corpus* rather than of the review: either the
    check stopped working or somebody fixed the recording without amending what
    it claims to demonstrate, and both need a person.
    """
    return CheckResult(
        check=result.check,
        passed=False,
        detail="passed, and this case was expected to fail it — the check or the case has drifted",
    )
