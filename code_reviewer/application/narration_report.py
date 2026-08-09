"""The narration run, as markdown.

Separate from the grading for the reason Level 12 separated its own report from
its service: rendering is where the audience lives, and a scorer that formats
is a scorer nobody can reuse.
"""

from code_reviewer.application.narration_evaluation import NarrationReport


def render_narration_report(report: NarrationReport, floor: float) -> str:
    """One table of checks, one list of failures, one line of qualification."""
    lines = [
        "# Narration evaluation",
        "",
        f"{report.case_count} recorded review(s), {len(report.graded[0].results) if report.graded else 0} "
        "check(s) each.",
        "",
        "| check | agreement |",
        "|---|---:|",
    ]

    checks = [result.check for result in report.graded[0].results] if report.graded else []
    for check in checks:
        lines.append(f"| `{check}` | {report.rate_for(check):.2f} |")

    lines += [
        "",
        f"**Score**: {report.score:.2f} (floor {floor:.2f}) — "
        f"{'met' if report.score >= floor else 'BELOW THE FLOOR'}",
        "",
    ]

    if report.stale:
        # Stated in the report rather than folded into the score. An older
        # prompt does not make a citation less grounded; it makes the number
        # evidence about a prompt nobody is running (decision D-4).
        lines += [
            f"**{len(report.stale)} of {report.case_count} case(s) are stale** — recorded under a "
            "prompt other than the one in use, or under none at all: "
            f"{', '.join(report.stale)}.",
            "",
        ]

    if report.failures:
        lines += ["## Disagreements", ""]
        lines += [
            f"- `{failure.case}` — **{failure.check}**: {failure.detail}" for failure in report.failures
        ]
        lines.append("")
    else:
        lines += ["Every check agreed with what its case declared.", ""]

    return "\n".join(lines)
