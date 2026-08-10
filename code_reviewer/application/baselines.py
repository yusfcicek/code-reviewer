"""A measurement worth keeping, and a delta with a subject.

Level 25. *"Is this better than last week"* needs two things this repository did
not have: a stored measurement, and something that says **what differed between
the runs**. A delta between two numbers whose provenance nobody recorded is a
number without a subject — it says the score moved and cannot say whether the
prompt, the model, the corpus or the weather moved with it.

So a baseline carries what produced it: the model, the prompt fingerprint Level
20 already computes, the cases it covered, and every per-check rate. And a
comparison reports **per-check movement**, because "better" is not a scalar: a
prompt edit that raises one check and lowers another has not made the reviewer
better or worse, it has made a trade, and a single number hides which.

The refusal is the load-bearing part. Two runs over different case sets are not
comparable, and reporting their difference as movement would be the most
confident wrong number this repository could produce. A different *prompt*, by
contrast, is compared and labelled — that is the comparison somebody actually
wants, with the thing that changed named.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from code_reviewer.application.narration_evaluation import NarrationReport
from code_reviewer.domain.narration import CHECK_NAMES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NarrationBaseline:
    """One measurement, and everything needed to know what it was about."""

    model: str
    prompt_fingerprint: str
    #: The cases it covered, sorted. A comparison against a different set is
    #: refused, and this is what that is decided from.
    case_names: tuple[str, ...] = ()
    rates: Mapping[str, float] = field(default_factory=dict)
    score: float = 0.0
    recorded_at: str = ""


@dataclass(frozen=True)
class CheckMovement:
    """One check, before and after."""

    check: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before


@dataclass(frozen=True)
class Comparison:
    """What moved between two runs, and what differed between them."""

    rose: tuple[CheckMovement, ...] = ()
    fell: tuple[CheckMovement, ...] = ()
    unchanged: tuple[CheckMovement, ...] = ()
    #: Checks this run measured that the baseline never did. Reported as new
    #: rather than as movement: reading an absent rate as nought renders a
    #: corpus edit as the reviewer improving (self-review 25, S-03).
    unmeasured: tuple[str, ...] = ()
    #: Why the two runs were not compared. Empty when they were.
    refused: str = ""
    prompt_changed: bool = False
    model_changed: bool = False


def baseline_from(
    report: NarrationReport, model: str, prompt_fingerprint: str, recorded_at: str
) -> NarrationBaseline:
    """A baseline from a run, keyed by what produced it."""
    return NarrationBaseline(
        model=model,
        prompt_fingerprint=prompt_fingerprint,
        case_names=tuple(sorted(graded.case for graded in report.graded)),
        rates={check: report.rate_for(check) for check in CHECK_NAMES},
        score=report.score,
        recorded_at=recorded_at,
    )


def write_baseline(path: str | Path, baseline: NarrationBaseline) -> None:
    """Stores a baseline as JSON. Raises only what the filesystem raises."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "model": baseline.model,
                "prompt_fingerprint": baseline.prompt_fingerprint,
                "case_names": list(baseline.case_names),
                "rates": dict(baseline.rates),
                "score": baseline.score,
                "recorded_at": baseline.recorded_at,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def read_baseline(path: str | Path) -> NarrationBaseline | None:
    """A stored baseline, or ``None``.

    A missing or malformed baseline is *nothing to compare against*, which is an
    ordinary state — the first run of a new corpus is in it — and not an error
    worth stopping a measurement for.
    """
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        return NarrationBaseline(
            model=str(raw["model"]),
            prompt_fingerprint=str(raw["prompt_fingerprint"]),
            case_names=tuple(str(name) for name in raw.get("case_names", ())),
            rates={str(key): float(value) for key, value in (raw.get("rates") or {}).items()},
            score=float(raw.get("score", 0.0)),
            recorded_at=str(raw.get("recorded_at", "")),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.info("No baseline to compare against at %s: %s", target, type(error).__name__)
        return None


def compare(
    baseline: NarrationBaseline, report: NarrationReport, model: str, prompt_fingerprint: str
) -> Comparison:
    """What moved between a stored baseline and this run.

    Refuses two different case sets. A corpus that gained a case scores
    differently for a reason that has nothing to do with the reviewer, and
    presenting that as movement would attribute a corpus edit to a prompt edit.
    Order does not matter — a reordered corpus is the same corpus.
    """
    now = tuple(sorted(graded.case for graded in report.graded))
    if now != baseline.case_names:
        added = sorted(set(now) - set(baseline.case_names))
        removed = sorted(set(baseline.case_names) - set(now))
        return Comparison(
            refused=(
                "the two runs cover different cases, so their difference is not movement: "
                f"added {', '.join(added) or 'none'}; removed {', '.join(removed) or 'none'}"
            )
        )

    rose: list[CheckMovement] = []
    fell: list[CheckMovement] = []
    unchanged: list[CheckMovement] = []
    unmeasured: list[str] = []
    for check in CHECK_NAMES:
        if check not in baseline.rates:
            # The baseline predates this check. Reading its absence as a rate of
            # nought would render adding a check as the reviewer improving.
            unmeasured.append(check)
            continue
        movement = CheckMovement(check, baseline.rates[check], report.rate_for(check))
        if movement.delta > 1e-9:
            rose.append(movement)
        elif movement.delta < -1e-9:
            fell.append(movement)
        else:
            unchanged.append(movement)

    return Comparison(
        rose=tuple(rose),
        fell=tuple(fell),
        unchanged=tuple(unchanged),
        unmeasured=tuple(unmeasured),
        prompt_changed=prompt_fingerprint != baseline.prompt_fingerprint,
        model_changed=model != baseline.model,
    )


def render_comparison(comparison: Comparison) -> str:
    """The delta as markdown, per check and never as one number."""
    if comparison.refused:
        return f"# Comparison\n\n**Not comparable.** {comparison.refused}\n"

    lines = ["# Comparison", ""]

    changed = []
    if comparison.prompt_changed:
        changed.append("the prompt")
    if comparison.model_changed:
        changed.append("the model")
    lines.append(
        f"**{' and '.join(changed).capitalize()} changed between these runs.**"
        if changed
        else "**Same model, same prompt, same cases.**"
    )
    lines.append("")

    if comparison.unmeasured:
        lines += [
            "**"
            + ", ".join(f"`{check}`" for check in comparison.unmeasured)
            + "** did not exist when the baseline was taken, so there is no movement to "
            "report for them.",
            "",
        ]

    if not (comparison.rose or comparison.fell):
        lines += ["No check moved.", ""]
        return "\n".join(lines)

    lines += ["| check | before | after | change |", "|---|---:|---:|---:|"]
    for movement in (*comparison.fell, *comparison.rose):
        lines.append(
            f"| `{movement.check}` | {movement.before:.2f} | {movement.after:.2f} | {movement.delta:+.2f} |"
        )
    lines += [
        "",
        "Per check rather than one number: a change that raises one check and lowers "
        "another is a trade, and an average hides which way.",
        "",
    ]
    return "\n".join(lines)
