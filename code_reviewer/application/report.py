"""Rendering of the merge-request comment.

Separated from orchestration so both verdict branches can be asserted without a
GitLab instance. The blocked branch was previously unreachable: the flag that
selected it was a string compared against a ``ReviewGateResult`` (finding F-01).
"""

import os
from collections.abc import Mapping, Sequence

from code_reviewer.domain.finding import Finding
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.recollection import Recollection

#: Identifies this agent's comment so the next run edits it rather than adding
#: a second one (finding G-12).
#:
#: It lives in the body, not in stored state. A note id kept in a file, a label
#: or a pipeline variable can drift out of sync with the thread it describes;
#: the body is the one thing guaranteed to travel with the comment. An HTML
#: comment is invisible in the rendered view, and it names the tool so two
#: agents posting to one merge request do not collide (decision D-1).
REVIEW_COMMENT_MARKER = "<!-- code-reviewer:ai-review-report -->"

#: GitLab rejects a note body over 1 000 000 characters. The default leaves
#: room for the truncation notice.
DEFAULT_MAX_COMMENT_CHARS = 900_000


def max_comment_chars_from_env(environment: Mapping[str, str] | None = None) -> int:
    """Reads the comment size bound, falling back on anything unusable.

    Falling back rather than raising: a review that has already been paid for
    should not be lost to a typo in an environment variable, and the fallback
    is the documented default rather than "no limit".
    """
    raw = (environment if environment is not None else os.environ).get("REVIEW_MAX_COMMENT_CHARS", "").strip()
    if not raw:
        return DEFAULT_MAX_COMMENT_CHARS

    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_COMMENT_CHARS

    return value if value > 0 else DEFAULT_MAX_COMMENT_CHARS


def _truncate(body: str, max_chars: int) -> str:
    """Cuts an oversized body, keeping the head.

    The verdict, the blocking reasons and the severity counts are at the top;
    the per-file prose is at the bottom. Dropping the tail loses detail.
    Dropping the head would lose the decision — and a report that opens
    mid-sentence about the fourth file is worse than no report, because it
    looks complete (decision D-2).

    The notice is appended *after* the cut, so the output always ends in prose
    rather than half a markdown table.
    """
    if len(body) <= max_chars:
        return body

    notice_template = (
        "\n\n---\n\n_Report truncated to fit the comment size limit: "
        "{dropped:,} characters omitted. The verdict and the blocking reasons "
        "above are complete; the per-file detail below them is not._"
    )
    # Two passes: the notice's own length depends on the number it prints, and
    # that number depends on where the cut lands. One re-measure is enough,
    # because the digit count is stable across a change of this size.
    reserve = len(notice_template.format(dropped=len(body)))
    cutoff = max(0, max_chars - reserve)
    dropped = len(body) - cutoff

    return body[:cutoff] + notice_template.format(dropped=dropped)


def render_review_comment(
    policy_version: str,
    outcome: ReviewOutcome,
    sections: Sequence[str],
    findings: Sequence[Finding] | None = None,
    max_chars: int | None = None,
    recurring: Mapping[tuple[str, str], Recollection] | None = None,
    trace_id: str = "",
) -> str:
    """Builds the markdown comment posted on the merge request.

    Args:
        policy_version: Printed in the footer, because "which policy applied"
            is the first question when a verdict surprises someone.
        outcome: The merge-request-level verdict.
        sections: One rendered block per reviewed file.
        findings: Everything the analyzers produced, for the summary line.
        max_chars: Size bound. Defaults to the environment's value.
        recurring: What the project already remembered about a finding's rule
            and file, keyed by ``(file_path, rule_id)``. Purely informational:
            the verdict above it is computed without it (Level 14, D-4).
        trace_id: Names the run in the log and in the trace artefact. The tree
            itself is not here: it is only complete after the comment has been
            rendered, and a reader who wants it wants the artefact anyway
            (Level 16).

    Returns:
        The comment body, beginning with :data:`REVIEW_COMMENT_MARKER` and
        truncated to ``max_chars`` if it would otherwise be rejected.
    """
    parts = [
        REVIEW_COMMENT_MARKER,
        "# 🤖 AI Review Report\n",
        *_verdict_lines(outcome),
        *_unanalysed_lines(outcome),
        *_unreviewed_lines(outcome),
        *_warning_lines(outcome),
        *_suppression_lines(outcome),
        *_summary_lines(findings or ()),
        *_recurrence_lines(findings or (), recurring or {}),
        f"\n**Policy v{policy_version}** | **Files considered**: {outcome.files_considered}"
        + (f" | **Trace**: `{trace_id}`" if trace_id else "")
        + "\n\n---\n",
        *sections,
    ]

    limit = max_chars if max_chars is not None else max_comment_chars_from_env()
    return _truncate("\n".join(parts), limit)


# -- sections ---------------------------------------------------------------
#
# One builder per block. They were inline until the agent reported this
# renderer at cyclomatic complexity 17 against its own source, which was fair:
# a report is a sequence of independent blocks, and reading it as one branchy
# function was harder than reading seven small ones.


def _verdict_lines(outcome: ReviewOutcome) -> list[str]:
    if not outcome.is_blocking:
        return ["### ✅ Pipeline PASSED\n"]
    return ["### ⛔ Pipeline BLOCKED\n", *(f"- 🔴 {issue}" for issue in outcome.blocking_issues)]


def _unanalysed_lines(outcome: ReviewOutcome) -> list[str]:
    """Stated separately, and before the model's prose.

    The reader's first question about a file with no findings is whether
    anything looked at it (finding G-09).
    """
    if not outcome.unanalysed_files:
        return []
    return [
        "\n**Not analysed** — no findings below mean *nothing was examined*\n",
        *(
            f"- 🚫 `{path}` — static analysis could not run: {reason}"
            for path, reason in outcome.unanalysed_files
        ),
    ]


def _unreviewed_lines(outcome: ReviewOutcome) -> list[str]:
    if not outcome.failed_files:
        return []
    return [
        "\n**Not reviewed**\n",
        *(f"- ⚠️ `{path}` — {reason}" for path, reason in outcome.failed_files),
    ]


def _warning_lines(outcome: ReviewOutcome) -> list[str]:
    warnings = outcome.warnings
    if not warnings:
        return []
    return ["\n**Warnings**\n", *(f"- ⚠️ {warning}" for warning in warnings)]


def _suppression_lines(outcome: ReviewOutcome) -> list[str]:
    """Stated in the report, not only in the source.

    Noticing a silence should not require already suspecting one (G-07).
    """
    if not outcome.suppressions:
        return []
    return [
        f"\n**{outcome.suppressed_count} finding(s) suppressed** by `review-ignore`\n",
        *(
            f"- 🔇 `{path}` line {item.directive.line}: `{item.directive.rule_id}` — "
            f"{item.directive.reason or '_no reason given_'}"
            for path, item in outcome.suppressions
        ),
    ]


def _summary_lines(findings: Sequence[Finding]) -> list[str]:
    if not findings:
        return []
    counts = Finding.count_by_severity(findings)
    breakdown = ", ".join(f"{count} {severity.value}" for severity, count in counts.items() if count)
    return [f"\n**Static analysis**: {len(findings)} finding(s) — {breakdown}\n"]


def _recurrence_lines(
    findings: Sequence[Finding], recurring: Mapping[tuple[str, str], Recollection]
) -> list[str]:
    """The findings this project has seen before, with how often and since when.

    A different sentence from "this file has a hardcoded secret": a rule that
    has fired here eleven times is either a rule that is wrong or a debt nobody
    has paid, and both are worth a reader's attention. Neither is worth a
    change of severity — the verdict above is computed from the findings alone,
    exactly as it was before this block existed (Level 14, decision D-4).
    """
    if not recurring:
        return []

    seen = [
        f"- 🔁 `{finding.location}`: `{finding.rule_id}` — reported "
        f"{remembered.occurrences} time(s) before, first on {remembered.first_seen.isoformat()}"
        for finding in findings
        if (remembered := recurring.get((finding.file_path, finding.rule_id))) is not None
    ]
    if not seen:
        return []
    return [f"\n**{len(seen)} finding(s) seen in this project before**\n", *seen]
