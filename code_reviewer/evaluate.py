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

#: The floor the shipped analyzer corpus holds, on the **lower bound** of a
#: 95 % interval (Level 25, decision D-2) rather than on the ratio.
#:
#: 0.80 since Level 28, which is the first time a floor here has gone up by
#: somebody writing cases rather than by somebody choosing a number: twenty
#: graded findings, all correct, support 0.84.
#:
#: This is now the *only* copy. The floors used to live in the test modules
#: while the workflow passed its own numbers on the command line, so when Level
#: 25 changed what a floor means the workflow went on asking for 0.95 against a
#: bound of 0.84 and CI failed for four levels while four reports said it
#: passed (self-review 28, S-01). `tests/unit/test_ci_gates.py` now reads the
#: workflow and pins it here.
DEFAULT_ANALYZER_FLOOR = 0.80

#: The floor the shipped documentation corpus holds, on the same lower bound.
#:
#: 0.80 since Level 28: eighteen graded findings supported 0.82, and the case
#: self-review 28 added for the method-name collision makes it nineteen at
#: 0.83. A
#: blocking gate would want the 0.95 the analyzers are held to, which needs
#: seventy-three — so `DOCS` still warns and does not block.
#:
#: A separate constant from the analyzers' even though the two agree today,
#: because they are two corpora and a shared number is how one of them quietly
#: inherits the other's evidence.
DEFAULT_DOCUMENTATION_FLOOR = 0.80

#: The floor the shipped narration corpus holds, applied to the **lower bound**
#: of a 95 % interval over **cases**.
#:
#: 0.85 rather than 0.95, and the correction is a finding rather than a
#: relaxation. The first version counted checks — twenty-four cases times five —
#: as a hundred and twenty independent trials, which narrowed the interval from
#: [0.86, 1.00] to [0.97, 1.00], and the floor was then chosen from the narrow
#: number. Checks inside one review are not independent: a review with no
#: sections fails two checks for one reason (self-review 25, S-01).
#:
#: Every case still either passes every check or declares the one it is built
#: to break, so the point estimate is 1.00 and twenty-four cases support 0.86.
DEFAULT_NARRATION_FLOOR = 0.85

#: The floor the shipped retrieval corpus holds, on the lower bound.
#:
#: The history is worth keeping because two of the three moves were findings
#: rather than choices. 0.55 came from a corpus in which every case carried
#: three sections and the measurement asked for three, so recall was 1.00 by
#: construction — a measurement that could not fail (self-review 27, S-01).
#: With a haystack it became 0.35 over five cases. Level 28 grew the corpus to
#: sixteen and moved the test module's copy to 0.40 while leaving this one, the
#: number the shipped gate actually uses, at 0.35 (self-review 28, S-03).
#:
#: 0.50 today: sixteen cases, twelve found, 0.75 [0.51, 0.90].
DEFAULT_RETRIEVAL_FLOOR = 0.50

#: How often the related section must come back *first*. The figure a retriever
#: can actually fail, so it is floored rather than only printed (S-03) — and
#: floored on the interval's **lower bound**, like every other floor here since
#: Level 25 (self-review 28, S-05). Ten of sixteen cases is a share of 0.62 and
#: a bound of 0.39; the floor takes 0.35 of it.
DEFAULT_FIRST_PLACE_FLOOR = 0.35

#: How deep the measurement looks — the drift tier's own per-file limit.
#: Measuring at a depth the tier never uses measures something else.
DEFAULT_RETRIEVAL_LIMIT = 3

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
            # `None`, resolved after parsing: the floor depends on which
            # corpus is being graded and that is not known until the mode flags
            # are read. It used to default to 0.0, which made `--documentation`
            # with no flags a command that could not fail (self-review 28).
            # Not a string default — argparse would run `type` over it.
            default=None,
            help=(
                f"Minimum acceptable {metric}, on the interval's lower bound. "
                "Below it, the command exits 1. Defaults to the floor the "
                "graded corpus holds."
            ),
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
        "--retrieval",
        action="store_true",
        help=(
            "Grade the drift tier's retrieval: whether the document section a "
            "reader says relates to a change comes back, and at what rank. "
            "Deterministic — it measures what reached the model, never whether "
            "the model was right."
        ),
    )
    parser.add_argument(
        "--min-retrieval",
        type=_floor,
        default=_floor(_env("EVALUATION_MIN_RETRIEVAL", str(DEFAULT_RETRIEVAL_FLOOR))),
        help="Minimum acceptable recall, on the interval's lower bound.",
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
        "--alignment",
        action="store_true",
        help=(
            "Grade the prompt against the checks over its output instead of "
            "grading either: whether every narration check has an instruction "
            "behind it, and whether every heading the output format demands is "
            "graded by something. Two texts, no model."
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


def _resolve_metric_floors(args) -> None:
    """Fills in the floor for whichever corpus is about to be graded.

    An explicit flag wins, then the environment, then the corpus's own floor.
    The last step is the one that matters: a run with no arguments grades
    against what the corpus holds rather than against nothing.
    """
    corpus = DEFAULT_DOCUMENTATION_FLOOR if args.documentation else DEFAULT_ANALYZER_FLOOR
    for metric in ("precision", "recall", "f1"):
        if getattr(args, f"min_{metric}") is not None:
            continue
        given = _env(f"EVALUATION_MIN_{metric.upper()}", "")
        setattr(args, f"min_{metric}", _floor(given) if given else corpus)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    _resolve_metric_floors(args)
    if args.narration:
        return _grade_narration(args)
    if args.documentation:
        return _grade_documentation(args)
    if args.retrieval:
        return _grade_retrieval(args)
    if args.alignment:
        return _grade_alignment(args)

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
        if outcome.measured_nothing:
            print(  # stdout: the program's output, not a diagnostic
                f"Nothing could be measured: {len(outcome.unreachable)} case(s) unreachable.",
                file=sys.stderr,
            )
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


def _grade_retrieval(args) -> int:
    """Grades the drift tier's retrieval. Same three exit codes.

    The corpus carries its own documents, so each case builds its own index —
    which is also what makes the cases independent, and therefore what makes
    the interval over cases honest.
    """
    from code_reviewer.application.retrieval_recall import measure_recall, render_recall_report
    from code_reviewer.application.retrieval_service import HybridRetriever
    from code_reviewer.infrastructure.evaluation.retrieval_dataset import RetrievalCorpus
    from code_reviewer.infrastructure.retrieval.chunking import chunk_markdown
    from code_reviewer.infrastructure.retrieval.embedding import HashingEmbedding
    from code_reviewer.infrastructure.retrieval.lexical import BM25Index
    from code_reviewer.infrastructure.retrieval.vector_index import InMemoryVectorIndex

    def build(documents):
        retriever = HybridRetriever(
            embedding=HashingEmbedding(), lexical=BM25Index(), vectors=InMemoryVectorIndex()
        )
        retriever.index([chunk for path, text in documents for chunk in chunk_markdown(path, text)])
        return retriever

    try:
        cases = RetrievalCorpus(args.dataset).cases()
    except ConfigurationError as error:
        print(f"Retrieval evaluation could not run: {error}", file=sys.stderr)  # stdout: the output
        return EXIT_CANNOT_MEASURE

    report = measure_recall(cases, build, limit=DEFAULT_RETRIEVAL_LIMIT)

    try:
        _emit(render_recall_report(report, args.min_retrieval, DEFAULT_FIRST_PLACE_FLOOR), args.markdown)
    except OSError as error:
        print(  # stdout: the program's output, not a diagnostic
            f"Retrieval evaluation ran but could not be written: {error}", file=sys.stderr
        )
        return EXIT_CANNOT_MEASURE

    if report.errors or not report.results:
        return EXIT_CANNOT_MEASURE
    if report.first_rank_interval.lower < DEFAULT_FIRST_PLACE_FLOOR:
        return EXIT_BELOW_THRESHOLD
    return EXIT_OK if report.interval.lower >= args.min_retrieval else EXIT_BELOW_THRESHOLD


def _grade_alignment(args) -> int:
    """Compares the shipped prompt against the checks over its output.

    Same three exit codes, and the middle one means something slightly
    different: not "the score is too low" but "a check grades a rule the prompt
    never states, or a heading it demands is graded by nothing". Both are
    defects with an exact answer, so there is no floor to pass (Level 29,
    contract C-5).

    The prompt is read through the same accessor `prompt_fingerprint` uses, so
    the text measured is the text that runs.
    """
    from code_reviewer.application.alignment_report import render_alignment_report
    from code_reviewer.domain.alignment import alignment
    from code_reviewer.domain.narration import EXPECTATIONS, REQUIRED_SECTIONS, UNCHECKED_SECTIONS

    try:
        from code_reviewer.infrastructure.llm.review_agent import ReviewAgent

        prompt = ReviewAgent.SYSTEM_TEMPLATE
    except Exception as error:  # pragma: no cover - an unimportable agent is a broken install
        print(f"Alignment could not run: {error}", file=sys.stderr)  # stdout: the program's output
        return EXIT_CANNOT_MEASURE

    try:
        report = alignment(
            prompt,
            EXPECTATIONS,
            checked=tuple(REQUIRED_SECTIONS),
            declined=dict(UNCHECKED_SECTIONS),
        )
    except ValueError as error:
        # A declined heading with no reason, or one the prompt stopped
        # demanding. The measurement could not be taken rather than failed.
        print(f"Alignment could not run: {error}", file=sys.stderr)  # stdout: the program's output
        return EXIT_CANNOT_MEASURE

    try:
        _emit(render_alignment_report(report), args.markdown)
    except OSError as error:
        print(f"Could not write the report: {error}", file=sys.stderr)  # stdout: the program's output
        return EXIT_CANNOT_MEASURE

    return EXIT_OK if report.is_aligned else EXIT_BELOW_THRESHOLD


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
