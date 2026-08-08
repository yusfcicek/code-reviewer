"""Operational error categories, so the exit point can map them to codes.

At the package root rather than inside a layer: every layer raises these and
none of them owns the taxonomy. Putting it in `domain/` would make an
operational concern look like a rule of code review; putting it in
`infrastructure/` would invert the dependency rule for the application layer
that also needs it.

The point is not taxonomy for its own sake. Before Level 10 the entry point
exited `1` for a blocked gate *and* for a crash, so no pipeline could tell a
gate that did its job from an agent that fell over — and that distinction is
the precondition for ever setting `allow_failure: false` (finding G-13).
Mapping a category to an exit code needs categories; the alternative is
inspecting exception messages, which is the same mistake as recovering a
verdict from the model's prose.
"""


class ReviewError(Exception):
    """Anything that stops a review from completing correctly."""


class ConfigurationError(ReviewError):
    """The run could not start correctly.

    A missing credential, an unloadable policy, an identifier that is not
    there. Nothing was reviewed, and nothing will be until someone changes the
    configuration — so retrying is pointless and the exit code says so.
    """


class ForgeError(ReviewError):
    """The code-hosting platform could not be reached or would not answer.

    Distinct from a configuration error because it is often transient: the
    same command may well work in a minute.
    """


class ReviewAgentError(ReviewError):
    """The agent could not produce a review for a file.

    Kept separate from a quality finding on purpose. When a technical failure
    is reported through the same channel as a code-quality judgement, "the
    connection was refused" arrives in the report as an opinion about the code
    (this repository's finding F-32, and the reason for ADR 0004).
    """
