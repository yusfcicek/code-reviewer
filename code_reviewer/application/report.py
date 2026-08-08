"""Rendering of the merge-request comment.

Separated from orchestration so both verdict branches can be asserted without a
GitLab instance. The blocked branch was previously unreachable: the flag that
selected it was a string compared against a ``ReviewGateResult`` (finding F-01).
"""

import os
from collections.abc import Mapping, Sequence

from code_reviewer.domain.finding import Finding
from code_reviewer.domain.outcome import ReviewOutcome

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
) -> str:
    """Builds the markdown comment posted on the merge request.

    Args:
        policy_version: Printed in the footer, because "which policy applied"
            is the first question when a verdict surprises someone.
        outcome: The merge-request-level verdict.
        sections: One rendered block per reviewed file.
        findings: Everything the analyzers produced, for the summary line.
        max_chars: Size bound. Defaults to the environment's value.

    Returns:
        The comment body, beginning with :data:`REVIEW_COMMENT_MARKER` and
        truncated to ``max_chars`` if it would otherwise be rejected.
    """
    parts = [REVIEW_COMMENT_MARKER, "# 🤖 AI Review Report\n"]

    if outcome.is_blocking:
        parts.append("### ⛔ Pipeline BLOCKED\n")
        for issue in outcome.blocking_issues:
            parts.append(f"- 🔴 {issue}")
    else:
        parts.append("### ✅ Pipeline PASSED\n")

    if outcome.unanalysed_files:
        # Stated separately and before the model's prose, because the reader's
        # first question about a file with no findings is whether anything
        # looked at it (finding G-09).
        parts.append("\n**Not analysed** — no findings below mean *nothing was examined*\n")
        for path, reason in outcome.unanalysed_files:
            parts.append(f"- 🚫 `{path}` — static analysis could not run: {reason}")

    if outcome.failed_files:
        parts.append("\n**Not reviewed**\n")
        for path, reason in outcome.failed_files:
            parts.append(f"- ⚠️ `{path}` — {reason}")

    warnings = outcome.warnings
    if warnings:
        parts.append("\n**Warnings**\n")
        for warning in warnings:
            parts.append(f"- ⚠️ {warning}")

    if findings:
        counts = Finding.count_by_severity(findings)
        breakdown = ", ".join(f"{count} {severity.value}" for severity, count in counts.items() if count)
        parts.append(f"\n**Static analysis**: {len(findings)} finding(s) — {breakdown}\n")

    parts.append(
        f"\n**Policy v{policy_version}** | **Files considered**: {outcome.files_considered}\n\n---\n"
    )
    parts.extend(sections)

    limit = max_chars if max_chars is not None else max_comment_chars_from_env()
    return _truncate("\n".join(parts), limit)
