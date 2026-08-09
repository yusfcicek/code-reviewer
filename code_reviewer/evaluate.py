"""``ai-code-review-eval`` — grade the analyzers against an annotated dataset.

A second console entry point rather than a subcommand of ``ai-code-review``.
That command is invoked by pipelines with a fixed argument list, and converting
its parser to subcommands would break every one of them for no gain
(decision D-5).

Three exit codes, and the split is the one Level 10 introduced:

* ``0`` — every floor was cleared.
* ``1`` — the thing measured is not good enough.
* ``2`` — the measurement could not be taken: an unreadable dataset, a fixture
  that is not there, an analyzer that raised.

Conflating the last two is what makes a gate unusable, because a pipeline
cannot tell a bad score from a broken harness and has to treat both as advice.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from code_reviewer.application.evaluation_report import evaluation_summary, render_evaluation_report
from code_reviewer.application.evaluation_service import EvaluationService
from code_reviewer.application.narration_evaluation import NarrationEvaluator
from code_reviewer.application.narration_report import narration_summary, render_narration_report
from code_reviewer.domain.evaluation import EvaluationThreshold
from code_reviewer.errors import ConfigurationError
from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite
from code_reviewer.infrastructure.config.loader import load_policy
from code_reviewer.infrastructure.evaluation.dataset import FileSystemDataset
from code_reviewer.infrastructure.evaluation.narration_dataset import NarrationCorpus

#: The dataset shipped with this repository.
DEFAULT_DATASET = "evaluation"

#: The floor the shipped narration corpus holds. Every case either passes every
#: check or declares the one it is built to break, so the measured value is
#: 1.00 and the floor is the measurement rather than a hope (Level 21).
DEFAULT_NARRATION_FLOOR = 1.0

EXIT_OK = 0
EXIT_BELOW_THRESHOLD = 1
EXIT_CANNOT_MEASURE = 2


def _env(name: str, fallback: str) -> str:
    value = os.getenv(name)
    return value if value else fallback


def _floor(raw: str) -> float:
    """A threshold, rejected at parse time if it is not a proportion."""
    try:
        value = float(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"'{raw}' is not a number") from error
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError(f"'{raw}' is not between 0 and 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-code-review-eval",
        description="Score the analysis suite against an annotated dataset",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=_env("EVALUATION_DATASET", DEFAULT_DATASET),
        help=f"Directory holding cases/ and their fixtures (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--policy",
        type=str,
        default=None,
        help=(
            "Policy YAML to grade under. Omitted by default: a baseline graded "
            "against whichever policy file happens to be present is not a baseline."
        ),
    )
    for metric in ("precision", "recall", "f1"):
        parser.add_argument(
            f"--min-{metric}",
            type=_floor,
            default=_floor(_env(f"EVALUATION_MIN_{metric.upper()}", "0.0")),
            help=f"Minimum acceptable {metric}. Below it, the command exits 1.",
        )
    parser.add_argument(
        "--narration",
        action="store_true",
        help=(
            "Grade the recorded reviews instead of the analyzers: whether the "
            "prose is consistent with the facts it was written about."
        ),
    )
    parser.add_argument(
        "--min-narration",
        type=_floor,
        default=_floor(_env("EVALUATION_MIN_NARRATION", str(DEFAULT_NARRATION_FLOOR))),
        help="Minimum acceptable narration score. Below it, the command exits 1.",
    )
    parser.add_argument(
        "--markdown",
        type=str,
        default="-",
        help="Where to write the report; '-' means stdout (the default)",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=str,
        default=_env("EVALUATION_JSON_PATH", ""),
        help="Where to write the machine-readable summary. Omitted, none is written.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    if args.narration:
        return _grade_narration(args)

    threshold = EvaluationThreshold(
        min_precision=args.min_precision,
        min_recall=args.min_recall,
        min_f1=args.min_f1,
    )

    try:
        policy = load_policy(args.policy) if args.policy else None
        dataset = FileSystemDataset(args.dataset)
        report = EvaluationService(StaticAnalysisSuite(policy)).evaluate(dataset)
    except ConfigurationError as error:
        print(f"Evaluation could not run: {error}", file=sys.stderr)  # stdout: the program's output
        return EXIT_CANNOT_MEASURE

    try:
        _emit(render_evaluation_report(report, threshold), args.markdown)
        if args.json_path:
            _write(json.dumps(evaluation_summary(report, threshold), indent=2) + "\n", args.json_path)
    except OSError as error:
        print(f"Evaluation ran but could not be written: {error}", file=sys.stderr)  # stdout: same
        return EXIT_CANNOT_MEASURE

    # A case that could not be graded is not a low score; the numbers were
    # never taken for it.
    if report.has_errors:
        return EXIT_CANNOT_MEASURE
    return EXIT_OK if threshold.is_met(report) else EXIT_BELOW_THRESHOLD


def _grade_narration(args) -> int:
    """Grades the recorded reviews. Same three exit codes, same meanings.

    The prompt fingerprint is read from the running package so the report can
    say which cases were recorded under some other prompt — a floor held
    entirely by recordings nobody can attribute is a floor holding nothing
    (Level 21, decision D-4).
    """
    from code_reviewer.infrastructure.governance.identity import prompt_fingerprint

    try:
        cases = NarrationCorpus(args.dataset).cases()
        report = NarrationEvaluator().evaluate(cases, current_fingerprint=prompt_fingerprint())
    except ConfigurationError as error:
        print(f"Narration evaluation could not run: {error}", file=sys.stderr)  # stdout: the output
        return EXIT_CANNOT_MEASURE

    try:
        _emit(render_narration_report(report, args.min_narration), args.markdown)
        if args.json_path:
            _write(json.dumps(narration_summary(report, args.min_narration), indent=2) + "\n", args.json_path)
    except OSError as error:
        print(  # stdout: the program's output, not a diagnostic
            f"Narration evaluation ran but could not be written: {error}", file=sys.stderr
        )
        return EXIT_CANNOT_MEASURE

    return EXIT_OK if report.score >= args.min_narration else EXIT_BELOW_THRESHOLD


def _emit(text: str, destination: str) -> None:
    if destination == "-":
        print(text, end="")  # stdout: the report is the program's output, not a diagnostic
        return
    _write(text, destination)


def _write(text: str, destination: str) -> None:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - exercised through the entry point
    raise SystemExit(main())
