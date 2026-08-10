"""The narration run, as markdown.

Separate from the grading for the reason Level 12 separated its own report from
its service: rendering is where the audience lives, and a scorer that formats
is a scorer nobody can reuse.
"""

from code_reviewer.application.narration_evaluation import MINIMUM_DEMONSTRATIONS, NarrationReport


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

    interval = report.score_interval
    lines += [
        "",
        f"**Score**: {report.score:.2f} per check; {interval} per case "
        f"(floor {floor:.2f} on the lower bound) — "
        f"{'met' if interval.lower >= floor else 'BELOW THE FLOOR'}",
        "",
        f"_{interval.method}, {interval.confidence:.0%}, over **cases** — a case counts once "
        "however many checks it has, because checks within one review are not independent. "
        "The point estimate alone would say the same thing about a corpus a hundred times "
        "this size._",
        "",
    ]

    lines += _coverage_lines(report)

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


def _coverage_lines(report: NarrationReport) -> list[str]:
    """How many cases exercise each check, in each direction.

    The aggregate cannot say this: five checks averaged move by a fifth when
    one of them breaks completely. And the direction nobody counts is the one
    that matters — every check in this repository's corpus was *passed* by
    thirteen or fourteen cases and *demonstrated firing* by one, which is how
    a check catching three phrasings of eight survived the corpus built to
    demonstrate it (self-review 21–22, S-01).
    """
    coverage = report.coverage
    if not coverage:
        return []

    lines = [
        "## Coverage",
        "",
        "How many cases exercise each check, in each direction. A check is only "
        "as pinned as the number of cases that demonstrate it *firing*.",
        "",
        "| check | cases passing it | cases demonstrating it fires |",
        "|---|---:|---:|",
    ]
    for entry in coverage:
        mark = " ⚠️" if entry.is_uncovered or entry.is_thin else ""
        lines.append(f"| `{entry.check}` | {entry.passing} | {entry.firing}{mark} |")

    thin = [entry for entry in coverage if entry.is_thin or entry.is_uncovered]
    lines.append("")
    if thin:
        lines += [
            f"**{len(thin)} check(s) below {MINIMUM_DEMONSTRATIONS} demonstration(s)** — named rather "
            "than averaged away, because one example pins one author's idea of a check:",
            "",
        ]
        lines += [
            f"- `{entry.check}` — {entry.firing} demonstrating it fires, {entry.passing} passing it"
            for entry in thin
        ]
        lines.append("")

    return lines


def narration_summary(report: NarrationReport, floor: float) -> dict:
    """The narration run as plain data, for a pipeline rather than a person.

    The same shape of artefact the analyzer harness writes: what was measured,
    against what floor, and everything that qualifies the number. `--json` was
    accepted on this path and silently ignored until the self-review found it
    (S-05).
    """
    checks = [result.check for result in report.graded[0].results] if report.graded else []
    return {
        "cases": report.case_count,
        "checks": {check: report.rate_for(check) for check in checks},
        "score": report.score,
        "floor": floor,
        "met": report.score >= floor,
        # Named rather than counted: "eleven are stale" does not say which to
        # re-record.
        "stale": list(report.stale),
        "failures": [
            {"case": failure.case, "check": failure.check, "detail": failure.detail}
            for failure in report.failures
        ],
    }
