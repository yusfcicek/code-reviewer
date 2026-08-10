"""What a model is allowed to say about a document, and what it means.

Tier B of Level 23. The deterministic tier reports what a change *proves*; this
one reports what nobody can prove — a section of prose that describes behaviour
the change altered without naming a single symbol. That case is the common one
and the reason the level exists, and it is not decidable by a parser.

So a model is asked, and the answer is confined to three values before it
reaches anything else. Three, not two: a model that must choose between "stale"
and "current" will choose one, and the choice it makes when it does not know is
noise wearing a verdict's clothes. :attr:`DriftVerdict.UNSURE` is where that
goes, and it is also where every unparseable answer goes.

Nothing here can block. Findings from this tier carry the `DRIFT` namespace,
which Level 20's attribution table registers as an `AGENT`, and
:class:`~code_reviewer.domain.provenance.DecisionRecord` already refuses to
record a blocking verdict citing one. That is a property of the table rather
than a rule anybody has to remember.
"""

from dataclasses import dataclass
from enum import Enum


class DriftVerdict(Enum):
    """What the model said about one section, reduced to three answers."""

    #: The section describes behaviour this change altered.
    STALE = "stale"
    #: The section still describes the code.
    CURRENT = "current"
    #: The model could not tell, or said something this could not read.
    UNSURE = "unsure"

    @property
    def is_reportable(self) -> bool:
        """Only a positive answer is worth a reader's time.

        `UNSURE` is deliberately not reported. A candidate list padded with
        maybes is a list nobody finishes, and the tier's whole value is that
        the few things in it are worth opening.
        """
        return self is DriftVerdict.STALE

    @classmethod
    def parse(cls, answer: str) -> "DriftVerdict":
        """Reads a model's reply. Anything unrecognised is `UNSURE`.

        Tolerant of the shapes a model actually produces — leading whitespace,
        a trailing full stop, a capitalised word, a sentence that begins with
        the answer — and unforgiving about everything else. A reply this cannot
        read is a reply that did not answer the question.
        """
        first = answer.strip().lower().lstrip("*#_> ").split()
        if not first:
            return cls.UNSURE
        # Stripped from both ends: a model that emphasises its answer writes
        # `**stale**`, and the closing marks are as much noise as the opening
        # ones.
        word = first[0].strip("*_`.,:;!\"'")
        for verdict in cls:
            if word == verdict.value:
                return verdict
        return cls.UNSURE


@dataclass(frozen=True)
class DriftCandidate:
    """One document section a change might have made stale.

    Carries the section's text because the model has to read it. Nothing
    downstream does: the finding built from a candidate names the path, the
    line and the heading, and stops there.
    """

    #: Where the section is.
    path: str
    line: int
    #: The heading it sits under, empty for prose before the first one.
    heading: str
    #: The section itself, for the model and for nothing else.
    text: str
    #: The file whose change raised this candidate.
    source_path: str
    #: That file's diff. Carried here rather than fetched again: the service
    #: already holds it, and a second read is a second chance to disagree
    #: about what the change was.
    diff: str = ""
