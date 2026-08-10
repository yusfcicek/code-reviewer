"""How much a score actually knows.

Level 25. This repository has quoted `1.00 over fifteen cases` since Level 21 —
in the README, the CHANGELOG and every level report — and printed it exactly the
way it would print `1.00 over fifteen hundred`. Both are true. They are not the
same claim: fifteen successes out of fifteen is consistent with a real pass rate
of eighty per cent.

**Wilson, and why.** The obvious interval — the normal approximation — gives
`[1.00, 1.00]` at fifteen of fifteen. It divides by an estimated variance that
is zero when nothing failed, so it answers "how uncertain are you" with "not at
all" precisely where the honest answer is "we barely looked". Wilson inverts the
test instead of approximating the estimate, which is why it behaves at the
boundary and why every clinical and polling convention reaches for it there.

The number is small, the derivation is a hundred years old, and the reason it is
in the domain rather than borrowed from a library is that a dependency for
fifteen lines of arithmetic is a dependency to keep current for the life of the
project.

Nothing here decides anything. It changes what a report *says* about a score,
and — through :class:`~code_reviewer.domain.evaluation.EvaluationThreshold` —
what a floor is applied to.
"""

import math
from dataclasses import dataclass

#: z for a two-sided 95 % interval. Hard-coded rather than parameterised: one
#: confidence level, named in the output, is a number a reader can hold. Two
#: would mean every quoted figure needed a qualifier nobody would carry.
_Z = 1.959963984540054

#: What the intervals here claim.
CONFIDENCE = 0.95


@dataclass(frozen=True)
class Interval:
    """A rate, and the rates still consistent with what was seen.

    Carries the sample size because the interval without it is unreadable —
    `[0.78, 1.00]` says nothing about whether writing ten more cases would help,
    and `[0.78, 1.00] over 15` says exactly that.
    """

    point: float
    lower: float
    upper: float
    total: int
    confidence: float = CONFIDENCE
    #: Which convention produced these bounds. Printed, so nobody has to guess
    #: which one a number they are about to quote came from.
    method: str = "Wilson score interval"

    def __str__(self) -> str:
        return f"{self.point:.2f} [{self.lower:.2f}, {self.upper:.2f}] over {self.total}"


def wilson(successes: int, total: int, z: float = _Z) -> Interval:
    """The Wilson score interval for ``successes`` out of ``total``.

    An empty sample is ``[0, 1]``: nothing was observed, so every rate remains
    consistent with it. That is a real answer rather than a division by zero,
    and it is what a freshly created corpus should report.
    """
    if successes < 0 or total < 0:
        raise ValueError("A count cannot be negative.")
    if successes > total:
        raise ValueError(f"{successes} successes out of {total} is not a proportion.")

    if total == 0:
        return Interval(point=0.0, lower=0.0, upper=1.0, total=0)

    observed = successes / total
    denominator = 1 + z**2 / total
    centre = (observed + z**2 / (2 * total)) / denominator
    spread = z * math.sqrt(observed * (1 - observed) / total + z**2 / (4 * total**2)) / denominator

    return Interval(
        point=observed,
        # Clamped: the arithmetic can leave the unit interval by a rounding
        # error at extreme counts, and a bound of -0.0000001 in a report is a
        # question nobody should have to ask.
        lower=max(0.0, centre - spread),
        upper=min(1.0, centre + spread),
        total=total,
    )


def rate_interval(rate: float, total: int) -> Interval:
    """The interval for a rate already computed as a proportion.

    A convenience for callers holding a share rather than a count — the
    narration score is one — and it rounds to the nearest whole success because
    a proportion over ``total`` items came from whole items.
    """
    return wilson(round(rate * total), total)


def harmonic(first: float, second: float) -> float:
    """The harmonic mean, which is nought when either input is."""
    if first <= 0 or second <= 0:
        return 0.0
    return 2 * first * second / (first + second)


def f1_interval(precision: Interval, recall: Interval) -> Interval:
    """A bound for F1, derived rather than sampled.

    Self-review 25, S-02. F1 is a harmonic mean, not a proportion, so there is
    no sample of successes to put a Wilson interval around. The first version
    of this level manufactured one — ``wilson(round(f1 * total), total)`` — and
    printed it in the same column as precision and recall, where its bounds
    belonged to 0.83 and the number beside them read 0.80.

    F1 is monotone increasing in both of its inputs, so the harmonic mean of
    the two lower bounds **is** a lower bound for F1, and likewise above. That
    is conservative — it is not the shortest interval available — and it is a
    statement that can be defended, which the previous one was not.

    ``total`` is the smaller of the two samples: a measurement is only as
    strong as its weaker half, and reporting the larger would be the same kind
    of flattery in a different field.
    """
    return Interval(
        point=harmonic(precision.point, recall.point),
        lower=harmonic(precision.lower, recall.lower),
        upper=harmonic(precision.upper, recall.upper),
        total=min(precision.total, recall.total),
        confidence=precision.confidence,
        method="derived from the precision and recall bounds",
    )
