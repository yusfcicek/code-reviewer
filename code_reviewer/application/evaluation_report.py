"""Two renderings of one evaluation run.

Markdown for a person reading a CI log, JSON for a pipeline that wants F1 over
time. The second is what makes "continuous optimisation" mean something later:
a number in a log is an anecdote, a number in an artefact is a series.

Both are built from the same report, and the tests assert they agree — a
summary that drifts from the text beside it is worse than either alone.
"""

from typing import Any

from code_reviewer.domain.evaluation import ConfusionMatrix, EvaluationReport, EvaluationThreshold


def evaluation_summary(
    report: EvaluationReport, threshold: EvaluationThreshold | None = None
) -> dict[str, Any]:
    """The run as plain data, ready for ``json.dumps``."""
    return {
        "cases": report.case_count,
        "overall": _matrix_summary(report.overall),
        "by_rule": {rule_id: _matrix_summary(matrix) for rule_id, matrix in report.by_rule.items()},
        "ungraded": {
            "count": report.ungraded_count,
            "rule_ids": list(report.ungraded_rule_ids),
        },
        "errors": [{"name": error.name, "reason": error.reason} for error in report.errors],
        "shortfalls": threshold.shortfalls(report) if threshold else [],
    }


def render_evaluation_report(report: EvaluationReport, threshold: EvaluationThreshold | None = None) -> str:
    """The run as markdown."""
    sections = [
        "# Evaluation",
        "",
        f"{report.case_count} case(s) graded, {report.ungraded_count} ungraded finding(s).",
    ]

    if report.errors:
        # Above the scores rather than below them: a score computed over the
        # cases that did not crash is not the score of the run.
        sections += [
            "",
            "## Cases that could not be graded",
            "",
            *(f"- **{error.name}** — {error.reason}" for error in report.errors),
        ]

    sections += ["", "## Overall", "", *_matrix_table(report.overall)]

    if report.by_rule:
        sections += [
            "",
            "## By rule",
            "",
            "| rule | TP | FP | FN | precision | recall | f1 |",
            "|---|---:|---:|---:|---:|---:|---:|",
            *(
                f"| `{rule_id}` | {matrix.true_positives} | {matrix.false_positives} | "
                f"{matrix.false_negatives} | {matrix.precision:.2f} | {matrix.recall:.2f} | "
                f"{matrix.f1:.2f} |"
                for rule_id, matrix in report.by_rule.items()
            ),
        ]

    if report.results:
        sections += [
            "",
            "## By case",
            "",
            "| case | TP | FP | FN | ungraded |",
            "|---|---:|---:|---:|---:|",
            *(
                f"| {result.case.name} | {result.matrix.true_positives} | "
                f"{result.matrix.false_positives} | {result.matrix.false_negatives} | "
                f"{len(result.ungraded)} |"
                for result in report.results
            ),
        ]

    sections += ["", "## Ungraded", "", _ungraded_sentence(report)]

    shortfalls = threshold.shortfalls(report) if threshold else []
    if shortfalls:
        sections += ["", "## Below threshold", "", *(f"- {reason}" for reason in shortfalls)]

    return "\n".join(sections) + "\n"


# -- internals --------------------------------------------------------------


def _matrix_summary(matrix: ConfusionMatrix) -> dict[str, Any]:
    return {
        "true_positives": matrix.true_positives,
        "false_positives": matrix.false_positives,
        "false_negatives": matrix.false_negatives,
        "precision": round(matrix.precision, 4),
        "recall": round(matrix.recall, 4),
        "f1": round(matrix.f1, 4),
    }


def _matrix_table(matrix: ConfusionMatrix) -> list[str]:
    return [
        "| metric | value |",
        "|---|---:|",
        f"| true positives | {matrix.true_positives} |",
        f"| false positives | {matrix.false_positives} |",
        f"| false negatives | {matrix.false_negatives} |",
        f"| precision | {matrix.precision:.2f} |",
        f"| recall | {matrix.recall:.2f} |",
        f"| f1 | {matrix.f1:.2f} |",
    ]


def _ungraded_sentence(report: EvaluationReport) -> str:
    """Stated even when the count is zero.

    An absent section reads as an oversight, and the whole point of counting
    ungraded findings is that narrowing a scope should be visible.
    """
    if not report.ungraded_count:
        return "0 ungraded findings — every finding the suite produced was graded."
    rules = ", ".join(f"`{rule_id}`" for rule_id in report.ungraded_rule_ids)
    return f"{report.ungraded_count} ungraded finding(s), from: {rules}."
