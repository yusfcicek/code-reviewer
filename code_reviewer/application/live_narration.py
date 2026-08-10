"""Grading what the configured model produces now, rather than what it produced.

Level 25. [Level 21](../../docs/roadmap/level-21/spec.md) refused to call a
model in CI, and that refusal still holds for the default run: a test suite
whose result depends on a remote service fails for reasons unrelated to the
code, and everybody learns to rerun it.

What the refusal left open is the thing the harness was built for. Level 20
records *which* prompt produced a review. Level 21 grades a review **no current
prompt produced** — a recording is a fact about the day it was captured, so a
prompt edit still ships unmeasured. Every case in the shipped corpus reports as
stale, and has since it was written.

So: the same cases, the same checks, and the reviewer that is configured right
now. Opt-in, never in the default run, and a model that fails on one case costs
that case and says so — a measurement with a hole in it must name the hole
rather than average over it.

Nothing here changes what the reviewer says. It measures.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from code_reviewer.application.narration_evaluation import NarrationEvaluator, NarrationReport
from code_reviewer.application.ports import ReviewBrief, Reviewer
from code_reviewer.domain.narration import NarrationCase

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveNarration:
    """What a live run measured, and what it could not reach."""

    report: NarrationReport | None
    #: Cases the model or the filesystem failed on, by name. Named rather than
    #: scored: "the model timed out" and "the model wrote something wrong" are
    #: different facts, and only the second is a measurement.
    unreachable: tuple[str, ...] = ()


def grade_live(
    cases: Sequence[NarrationCase],
    reviewer: Reviewer,
    source_of: Callable[[NarrationCase], str],
    fingerprint: str = "",
) -> LiveNarration:
    """Runs the reviewer over each case's inputs and grades what comes back.

    Args:
        cases: The corpus. Only the *inputs* are used — the file, its findings
            and what the case declares it should fail. The recorded review is
            not consulted, which is the whole point of the mode.
        reviewer: Whatever is configured. This is the subject of the
            measurement.
        source_of: Reads the case's fixture. Injected so this layer does not
            open files, and so a caller can confine the read the way Level 8
            confines every other one.
        fingerprint: The prompt in use, stamped onto each freshly produced case
            so the result is attributable to what made it.

    Never raises. A case the model or the filesystem could not serve is named
    in :attr:`LiveNarration.unreachable` and left out of the score.
    """
    produced: list[NarrationCase] = []
    unreachable: list[str] = []

    for case in cases:
        review = _produce(case, reviewer, source_of)
        if review is None:
            unreachable.append(case.name)
            continue
        produced.append(
            NarrationCase(
                name=case.name,
                file_path=case.file_path,
                line_count=case.line_count,
                review=review,
                findings=case.findings,
                expected_failures=case.expected_failures,
                prompt_fingerprint=fingerprint,
            )
        )

    report = NarrationEvaluator().evaluate(produced, current_fingerprint=fingerprint)
    return LiveNarration(report=report, unreachable=tuple(unreachable))


def _produce(
    case: NarrationCase, reviewer: Reviewer, source_of: Callable[[NarrationCase], str]
) -> str | None:
    """One case's fresh review, or ``None`` if it could not be produced."""
    try:
        source = source_of(case)
    except Exception as error:
        logger.warning("Could not read the fixture for case '%s': %s", case.name, error)
        return None

    brief = ReviewBrief(
        file_path=case.file_path,
        # The whole file as the diff. A case is a file and a review about it;
        # there is no merge request behind it, and inventing a hunk header
        # would be feeding the model a fact the corpus does not have.
        diff=source,
        full_content=source,
        findings=tuple(case.findings),
    )

    try:
        return reviewer.review_diff(brief)
    except Exception as error:
        logger.warning("The reviewer failed on case '%s': %s: %s", case.name, type(error).__name__, error)
        return None
