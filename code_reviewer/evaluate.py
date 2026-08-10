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

from code_reviewer.application.documentation_evaluation import evaluate_documentation
from code_reviewer.application.evaluation_report import evaluation_summary, render_evaluation_report
from code_reviewer.application.evaluation_service import EvaluationService
from code_reviewer.application.narration_evaluation import NarrationEvaluator
from code_reviewer.application.narration_report import narration_summary, render_narration_report
from code_reviewer.domain.evaluation import EvaluationThreshold
from code_reviewer.errors import ConfigurationError
from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite
from code_reviewer.infrastructure.config.loader import load_policy
from code_reviewer.infrastructure.evaluation.dataset import FileSystemDataset
from code_reviewer.infrastructure.evaluation.documentation_dataset import DocumentationCorpus
from code_reviewer.infrastructure.evaluation.narration_dataset import NarrationCorpus

#: The dataset shipped with this repository.
DEFAULT_DATASET = "evaluation"

#: The floor the shipped narration corpus holds, applied to the **lower bound**
#: of a 95 % interval since Level 25 rather than to the point estimate.
#:
#: Every case still either passes every check or declares the one it is built
#: to break, so the point estimate is 1.00. Seventy-five checks over fifteen
#: cases put the lower bound at 0.95, and that is the floor: a value of 1.00
#: here would be unreachable by any finite corpus, which is a floor that can
#: only be met by nobody measuring.
DEFAULT_NARRATION_FLOOR = 0.95

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
        "--live",
        action="store_true",
        help=(
            "With --narration: grade what the configured model produces now "
            "instead of the recorded reviews. Needs an endpoint; without one "
            "the command exits 2, because a measurement that could not be "
            "taken is not a bad score."
        ),
    )
    parser.add_argument(
        "--write-baseline",
        default="",
        metavar="PATH",
        help=(
            "With --narration: store this run as a baseline, keyed by the model "
            "and prompt fingerprint that produced it."
        ),
    )
    parser.add_argument(
        "--compare-baseline",
        default="",
        metavar="PATH",
        help=(
            "With --narration: report what moved since a stored baseline, per "
            "check. Two runs over different cases are refused rather than "
            "differenced."
        ),
    )
    parser.add_argument(
        "--documentation",
        action="store_true",
        help=(
            "Grade the documentation rules instead of the analyzers: whether "
            "a change is reported against the prose that described it. The "
            "retrieved tier is not graded here and cannot be."
        ),
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
    if args.documentation:
        return _grade_documentation(args)

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
    except ConfigurationError as error:
        print(f"Narration evaluation could not run: {error}", file=sys.stderr)  # stdout: the output
        return EXIT_CANNOT_MEASURE

    if args.live:
        outcome = _live_narration(cases, args)
        if outcome is None:
            return EXIT_CANNOT_MEASURE
        report = outcome.report
        if outcome.unreachable:
            print(  # stdout: the program's output, not a diagnostic
                f"{len(outcome.unreachable)} case(s) could not be reviewed and are not in the score: "
                f"{', '.join(outcome.unreachable)}",
                file=sys.stderr,
            )
    else:
        report = NarrationEvaluator().evaluate(cases, current_fingerprint=prompt_fingerprint())

    _baselines(report, args)

    try:
        _emit(render_narration_report(report, args.min_narration), args.markdown)
        if args.json_path:
            _write(json.dumps(narration_summary(report, args.min_narration), indent=2) + "\n", args.json_path)
    except OSError as error:
        print(  # stdout: the program's output, not a diagnostic
            f"Narration evaluation ran but could not be written: {error}", file=sys.stderr
        )
        return EXIT_CANNOT_MEASURE

    # The lower bound, not the point estimate (Level 25, decision D-2). The
    # exit code and the rendered verdict were reading two different numbers,
    # which is how a report can say BELOW THE FLOOR and exit zero.
    return EXIT_OK if report.score_interval.lower >= args.min_narration else EXIT_BELOW_THRESHOLD


def _grade_documentation(args) -> int:
    """Grades Level 23's deterministic tier. Same three exit codes.

    Uses the analyzers' own thresholds and report renderer, because the numbers
    mean the same thing: a rule that fires where nothing is wrong costs
    precision here exactly as it does there. Only the corpus is different.
    """
    threshold = EvaluationThreshold(
        min_precision=args.min_precision,
        min_recall=args.min_recall,
        min_f1=args.min_f1,
    )

    try:
        report = evaluate_documentation(DocumentationCorpus(args.dataset).cases())
    except ConfigurationError as error:
        print(f"Documentation evaluation could not run: {error}", file=sys.stderr)  # stdout: the output
        return EXIT_CANNOT_MEASURE

    try:
        _emit(render_evaluation_report(report, threshold), args.markdown)
        if args.json_path:
            _write(json.dumps(evaluation_summary(report, threshold), indent=2) + "\n", args.json_path)
    except OSError as error:
        print(  # stdout: the program's output, not a diagnostic
            f"Documentation evaluation ran but could not be written: {error}", file=sys.stderr
        )
        return EXIT_CANNOT_MEASURE

    if report.has_errors:
        return EXIT_CANNOT_MEASURE
    return EXIT_OK if threshold.is_met(report) else EXIT_BELOW_THRESHOLD


def _baselines(report, args) -> None:
    """Stores this run, compares it with a stored one, or neither.

    Never changes the exit code. A delta is something to read, not a gate: what
    counts as an acceptable movement is a judgement, and encoding one here
    would be inventing a policy nobody stated.
    """
    from code_reviewer.application.baselines import (
        baseline_from,
        compare,
        read_baseline,
        render_comparison,
        write_baseline,
    )
    from code_reviewer.infrastructure.governance.identity import prompt_fingerprint

    if not (args.write_baseline or args.compare_baseline):
        return

    model = os.environ.get("VLLM_MODEL_NAME", "")
    fingerprint = prompt_fingerprint()

    if args.compare_baseline:
        stored = read_baseline(args.compare_baseline)
        if stored is None:
            print(  # stdout: the program's output, not a diagnostic
                f"Nothing to compare against at '{args.compare_baseline}'.", file=sys.stderr
            )
        else:
            print(render_comparison(compare(stored, report, model, fingerprint)))  # stdout: the output

    if args.write_baseline:
        from datetime import UTC, datetime

        write_baseline(
            args.write_baseline,
            baseline_from(report, model, fingerprint, datetime.now(UTC).isoformat()),
        )


def _live_narration(cases, args):
    """A live run, or ``None`` when there is no model to run it against.

    Imported here rather than at module scope so that the recorded path — the
    one CI takes — never so much as loads the code that can call a model.
    """
    from code_reviewer.application.live_narration import grade_live
    from code_reviewer.infrastructure.governance.identity import prompt_fingerprint

    try:
        from code_reviewer.__main__ import _build_reviewer
        from code_reviewer.cli import build_parser as review_parser

        reviewer = _build_reviewer(review_parser().parse_args([]))
    except Exception as error:  # pragma: no cover - depends on the deployment
        print(  # stdout: the program's output, not a diagnostic
            f"Live narration could not run: no reviewer could be built ({type(error).__name__}).",
            file=sys.stderr,
        )
        return None

    def _source(case):
        return (Path(args.dataset) / case.file_path).read_text(encoding="utf-8")

    return grade_live(cases, reviewer, _source, fingerprint=prompt_fingerprint())


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
