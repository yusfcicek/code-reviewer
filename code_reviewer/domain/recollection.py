"""What one repository's reviews have learned about it.

`SmartMemoryStrategy` carries findings from one file to the next inside a single
run, and then the process exits. The agent that reviewed this repository
yesterday and the one reviewing it today share nothing at all, so a rule that
has fired on the same line eleven times looks new every time — and "this file
has a hardcoded secret" and "this file has had a hardcoded secret reported on
it eleven times and nobody has acted on it" are different review comments
(capability C-08).

The rules for turning sightings into a memory are here, beside `gate.py` and
`evaluation.py`, for the reason all three are: they need no filesystem, and
every edge case in them is arithmetic over a handful of values.

Three properties are deliberate.

**Repeats consolidate.** A recollection is identified by what kind it is, which
file it concerns and which rule produced it — not by line and not by severity.
A refactor that shifts a function down two lines must not reset every count in
the file. Memory that grows linearly with the number of reviews is a log.

**Memory forgets.** Salience decays with a half-life, and below a floor a fact
is dropped. A memory with no forgetting is a file that grows until somebody
deletes it, and what they delete is the whole history rather than the stale
part of it.

**Memory informs; it never decides.** Nothing here produces a severity, a
verdict or an exit code. The tempting feature — downgrading a finding the team
has ignored eleven times — is a tool learning to stop complaining, and the
honest reading of eleven ignored reports is that either the rule is wrong or
the debt is real. Both are decisions for a person (decision D-4).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import Enum

from .severity import Severity

#: Days after which a sighting counts for half as much. A month: long enough
#: that last sprint's findings still weigh on this one, short enough that a
#: rule fixed in the spring stops competing by the summer.
HALF_LIFE_DAYS = 30.0

#: Below this, a recollection is forgotten. Roughly: one INFO sighting, three
#: half-lives ago.
DEFAULT_SALIENCE_FLOOR = 0.15

#: How much a severity is worth to *attention*, which is not what
#: `Severity.weight` measures. That one is a quality-score budget in which INFO
#: deliberately contributes nothing — correct there, and here it would mean
#: every INFO recollection scored zero and was forgotten immediately.
_ATTENTION = {
    Severity.CRITICAL: 5.0,
    Severity.HIGH: 4.0,
    Severity.MEDIUM: 3.0,
    Severity.LOW: 2.0,
    Severity.INFO: 1.0,
}


class RecollectionKind(Enum):
    """What kind of thing is being remembered."""

    #: A rule fired here. "This keeps happening."
    FINDING = "finding"
    #: A `review-ignore` directive silenced a rule here. "Somebody decided."
    SUPPRESSION = "suppression"


@dataclass(frozen=True)
class Recollection:
    """One fact this project's reviews have accumulated.

    Deliberately made of identifiers and counts. No evidence line, no diff
    excerpt, no model prose: a diff is written by whoever opened the merge
    request, so a memory file that accumulates it is a stored injection with a
    long half-life — and a diff may contain a secret, so it would also be a
    credential store nobody declared (decision D-3).
    """

    kind: RecollectionKind
    file_path: str
    rule_id: str
    first_seen: date
    last_seen: date
    severity: Severity = Severity.INFO
    occurrences: int = 1
    #: A suppression's written reason, when it had one. The only free text
    #: stored, and it is written by the repository's own maintainers in a
    #: source comment rather than by the change under review.
    reason: str = ""

    def __post_init__(self) -> None:
        if self.occurrences < 1:
            raise ValueError("A recollection is something that happened at least once.")
        if self.last_seen < self.first_seen:
            raise ValueError(f"'{self.rule_id}' in {self.file_path} was last seen before it was first seen.")

    @property
    def identity(self) -> tuple[RecollectionKind, str, str]:
        """What makes two sightings the same fact.

        Line number is out because a refactor moves lines, and severity is out
        because the same rule reported at a different grade is the same rule
        having an opinion.
        """
        return (self.kind, self.file_path, self.rule_id)

    @property
    def directory(self) -> str:
        """The directory this fact is about, or the empty string at the root."""
        return self.file_path.rsplit("/", 1)[0] if "/" in self.file_path else ""

    def age_in_days(self, today: date) -> float:
        """Days since this was last seen, floored at zero.

        Floored because clocks are wrong sometimes — a machine an hour ahead
        writes a `last_seen` in the future, and a negative age would make that
        entry outrank everything else forever.
        """
        return max(0.0, float((today - self.last_seen).days))

    def merge(self, other: "Recollection") -> "Recollection":
        """One fact from two sightings of it."""
        if self.identity != other.identity:
            raise ValueError(f"{self.identity} and {other.identity} are not the same fact.")

        return replace(
            self,
            occurrences=self.occurrences + other.occurrences,
            first_seen=min(self.first_seen, other.first_seen),
            last_seen=max(self.last_seen, other.last_seen),
            # `Severity` orders most-severe-smallest, so `min` is "the worst
            # it has ever been" — which is what a reader needs to know.
            severity=min(self.severity, other.severity),
            reason=_current_reason(self, other),
        )


def salience(recollection: Recollection, today: date) -> float:
    """How much this deserves the next reviewer's attention.

    Occurrences, weighted by severity, halved for every
    :data:`HALF_LIFE_DAYS` since it was last seen. Exponential rather than
    linear decay so that nothing reaches zero at an arbitrary point: the floor
    is what forgets, not the arithmetic (decision D-5).
    """
    decay = 0.5 ** (recollection.age_in_days(today) / HALF_LIFE_DAYS)
    return recollection.occurrences * _ATTENTION[recollection.severity] * decay


def forget(
    recollections: Iterable[Recollection], today: date, floor: float = DEFAULT_SALIENCE_FLOOR
) -> list[Recollection]:
    """Drops everything below the floor, keeping the rest in its original order."""
    return [item for item in recollections if salience(item, today) >= floor]


def retain(recollections: Sequence[Recollection], today: date, limit: int) -> list[Recollection]:
    """The most salient ``limit`` recollections, most salient first.

    Ties resolve by identity so that two runs over the same memory produce the
    same file — a store whose order depends on dictionary iteration produces a
    diff on every commit and teaches everyone to ignore it.
    """
    if limit <= 0:
        return []
    ordered = sorted(recollections, key=lambda item: (-salience(item, today), _identity_key(item)))
    return ordered[:limit]


def consolidate(existing: Iterable[Recollection], observed: Iterable[Recollection]) -> list[Recollection]:
    """Folds new sightings into what is already known.

    Order is preserved for what was already there, with anything genuinely new
    appended — so the file reads as a history rather than being reshuffled on
    every run.
    """
    merged: dict[tuple[RecollectionKind, str, str], Recollection] = {}
    order: list[tuple[RecollectionKind, str, str]] = []

    for item in (*existing, *observed):
        key = item.identity
        if key in merged:
            merged[key] = merged[key].merge(item)
        else:
            merged[key] = item
            order.append(key)

    return [merged[key] for key in order]


def recall_for(
    file_path: str, recollections: Sequence[Recollection], today: date, limit: int = 8
) -> list[Recollection]:
    """What is worth telling a reviewer about ``file_path``.

    This file's own history first, then its directory's, each ranked by
    salience. Scoped rather than whole: injecting an entire memory into every
    prompt is how a context window gets spent on the wrong part of the
    repository (contract C-4).
    """
    if limit <= 0 or not file_path:
        return []

    directory = file_path.rsplit("/", 1)[0] if "/" in file_path else ""

    own = [item for item in recollections if item.file_path == file_path]
    # The root is not a bucket everything falls into: a file at the top level
    # has no directory to generalise from, and treating "" as one would recall
    # the entire repository for it.
    neighbours = (
        [item for item in recollections if item.file_path != file_path and item.directory == directory]
        if directory
        else []
    )

    selected = retain(own, today, limit)
    remaining = limit - len(selected)
    if remaining > 0:
        selected.extend(retain(neighbours, today, remaining))
    return selected


# -- internals --------------------------------------------------------------


def _current_reason(first: Recollection, second: Recollection) -> str:
    """The most recent reason anybody wrote, ignoring blanks.

    A suppression's comment can be rewritten, and the current text is the one
    somebody would read in the file. A newer sighting with no reason at all
    does not erase an older explanation — that would punish a directive whose
    reason moved to the line above it.
    """
    written = [item for item in (first, second) if item.reason]
    if not written:
        return ""
    return max(written, key=lambda item: item.last_seen).reason


def _identity_key(recollection: Recollection) -> tuple[str, str, str]:
    return (recollection.kind.value, recollection.file_path, recollection.rule_id)
