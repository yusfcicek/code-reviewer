"""Whether the prompt asks for what the checks over its output enforce.

Level 21 built five checks over the reviewer's prose. Level 25 measured them
against twenty-four recorded reviews and they score 1.00. Nobody had asked the
other half of the question, and the answer for three of the five was that the
prompt says nothing at all: `cite`, `citation`, `path:line`, `verdict`,
`approved` — none of them appear in the shipped template.

> An unbacked check grades the model on a rule it was never given. An
> ungoverned demand asks for output nobody ever looks at.

The first matters practically. When a narration score falls, the fix is assumed
to be in the prompt — and for three of these five there was nothing in the
prompt to fix.

Two texts and a substring search, which is the whole of it. Anything cleverer —
a model asked whether the prompt implies the rule, a similarity over embeddings
— would put an unmeasured judgement inside a measurement, which is the reason
Level 21 refused an LLM judge (decision D-1).

**No interval and no floor.** Every other measurement in this repository carries
a Wilson interval because it is a sample of a larger population. This one is not
a sample: it is a fact about two texts that ship together, and "three of five
checks are unbacked" is a list of three things to write rather than a rate of
0.40 (decision D-4).

What this cannot answer, and does not pretend to: whether the model *obeys* an
instruction that is present. That needs an endpoint on every iteration, and it
is named in the report rather than approximated.
"""

import re
from dataclasses import dataclass
from enum import Enum

#: An ATX heading in the prompt's output format. Bounded to three levels
#: because the fourth is where the format's repeated blocks start.
_HEADING = re.compile(r"^\s{0,3}#{1,3}\s+(?P<title>.+?)\s*#*\s*$", re.M)

#: Everything that decorates a heading without naming it: emoji, symbols, the
#: whitespace around them. A check that pinned the decoration would fail on a
#: change that means nothing — the reasoning `required_sections_are_present`
#: already carries, applied to the other side of the same comparison.
_DECORATION = re.compile(r"[^\w\s&'/-]+")

#: A bracketed placeholder, which the output format uses for the text the model
#: is to supply. Recognised before the decoration is stripped, because
#: stripping turns `[Priority] - [Title]` into a heading that looks real.
_PLACEHOLDER = re.compile(r"\[[^\]]*\]")


class Match(Enum):
    """How many of an expectation's phrases the prompt must contain."""

    #: Every phrase. For a rule with two halves — cite a location, and only a
    #: real one — where a prompt carrying one half backs half a check.
    ALL = "all"
    #: Any one. For a rule a prompt may reasonably phrase more than one way.
    ANY = "any"


@dataclass(frozen=True)
class Expectation:
    """What one check needs the prompt to say for grading against it to be fair.

    Literal phrases, deliberately. A phrase somebody can search for in the
    template is a phrase somebody can add to it, and the whole value of this
    measurement is that its failures are actionable in one edit.
    """

    check: str
    phrases: tuple[str, ...]
    match: Match = Match.ALL

    def __post_init__(self) -> None:
        if not self.phrases:
            # An expectation with no phrases is met by every prompt. That is
            # the shape of check this repository has caught itself building
            # four times, and the constructor is the cheapest place to refuse.
            raise ValueError(f"{self.check}: an expectation needs at least one phrase")

    def absent_from(self, prompt: str) -> tuple[str, ...]:
        """The phrases this prompt does not contain, in declared order.

        Empty when the expectation is met, which for :attr:`Match.ANY` means
        empty as soon as one phrase is there — the others are alternatives
        rather than omissions.
        """
        missing = tuple(phrase for phrase in self.phrases if phrase.lower() not in prompt.lower())
        if self.match is Match.ANY and len(missing) < len(self.phrases):
            return ()
        return missing

    def met_by(self, prompt: str) -> bool:
        return not self.absent_from(prompt)


@dataclass(frozen=True)
class UnbackedCheck:
    """A check the prompt never asks the model to satisfy."""

    check: str
    #: What was looked for and not found. The report prints it so the fix is a
    #: sentence somebody writes rather than a puzzle somebody solves.
    missing: tuple[str, ...]


@dataclass(frozen=True)
class AlignmentReport:
    """What the prompt and the checks say about each other."""

    #: Checks with no instruction behind them, in check order.
    unbacked: tuple[UnbackedCheck, ...] = ()
    #: Headings the prompt demands that nothing grades and nothing declines.
    ungoverned: tuple[str, ...] = ()
    #: Headings the code names — as graded or as deliberately ungraded — that
    #: the prompt does not demand. The more damaging direction, and the one
    #: Level 29 forgot to look in: a demanded heading nothing grades costs a
    #: reader nothing, while a *graded* heading nothing demands fails every
    #: case in the corpus, forever (self-review 29, S-01).
    ungrounded: tuple[str, ...] = ()
    #: Headings deliberately left ungraded, each with a reason on record.
    declined: tuple[str, ...] = ()
    #: Checks the prompt does back.
    aligned: tuple[str, ...] = ()
    #: Every heading the output format asks for.
    demanded: tuple[str, ...] = ()

    @property
    def is_aligned(self) -> bool:
        return not self.unbacked and not self.ungoverned and not self.ungrounded


def sections_demanded(prompt: str) -> tuple[str, ...]:
    """The headings a prompt's output format asks a review to contain.

    Read out of the Markdown rather than out of a list somebody keeps in step,
    because the list is what goes stale: this measurement exists because two
    headings were demanded for eight levels and never checked.

    A heading that is entirely a placeholder — `### [Priority] - [Title]` — is a
    template for a repeated block rather than a section a review must contain,
    and demanding it would demand the literal brackets.
    """
    found: list[str] = []
    for match in _HEADING.finditer(prompt):
        raw = match.group("title")
        if not _PLACEHOLDER.sub("", raw).strip(" -–—:"):
            continue
        title = _DECORATION.sub("", raw).strip()
        if not title:
            continue
        if title not in found:
            found.append(title)
    return tuple(found)


def _refuse_contradictions(checked: tuple[str, ...], declined: dict[str, str]) -> None:
    """Two ways the code can disagree with itself rather than with the prompt.

    Neither is a fact about the prompt, so neither belongs in the report: a
    decline with no reason is indistinguishable from an oversight, and a
    heading that is both graded and deliberately ungraded is one constant
    contradicting another.
    """
    for heading, reason in declined.items():
        if not reason.strip():
            raise ValueError(f"{heading}: a declined section needs a reason, not a blank")
        if heading in checked:
            raise ValueError(f"{heading} is both graded and declined; it cannot be both")


def alignment(
    prompt: str,
    expectations: tuple[Expectation, ...],
    checked: tuple[str, ...],
    declined: dict[str, str],
) -> AlignmentReport:
    """Compares a prompt against the checks that grade what it produces.

    ``checked`` is the headings something grades; ``declined`` maps a heading to
    the reason nothing does. Both are names the code carries, and a name the
    prompt does not demand is a misalignment in the direction Level 29 forgot to
    look in — reported as ``ungrounded`` rather than raised, because the
    measurement was taken and the answer is known (self-review 29, S-01, S-03).

    Two things are still refused outright, because they are contradictions
    between two constants rather than facts about the prompt: a decline with no
    reason, and a heading that is both graded and deliberately ungraded.
    """
    if not expectations:
        # A measurement over nothing reports perfect alignment. Self-review 25
        # found that in the analyzer harness and 27 found it in the retrieval
        # corpus; twice is enough to refuse it in the constructor of the third.
        raise ValueError("alignment needs at least one expectation to check")

    _refuse_contradictions(checked, declined)
    demanded = sections_demanded(prompt)
    named = sorted({*checked, *declined})
    unbacked = tuple(
        UnbackedCheck(check=expectation.check, missing=expectation.absent_from(prompt))
        for expectation in expectations
        if not expectation.met_by(prompt)
    )
    return AlignmentReport(
        unbacked=unbacked,
        ungoverned=tuple(name for name in demanded if name not in checked and name not in declined),
        ungrounded=tuple(name for name in named if name not in demanded),
        declined=tuple(name for name in demanded if name in declined),
        aligned=tuple(expectation.check for expectation in expectations if expectation.met_by(prompt)),
        demanded=demanded,
    )
