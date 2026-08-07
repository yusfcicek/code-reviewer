"""Rendering of the merge-request comment.

Separated from orchestration so both verdict branches can be asserted without a
GitLab instance. The blocked branch was previously unreachable: the flag that
selected it was a string compared against a ``ReviewGateResult`` (finding F-01).
"""

from typing import Sequence

from .gate.outcome import ReviewOutcome


def render_review_comment(
    policy_version: str,
    outcome: ReviewOutcome,
    sections: Sequence[str],
) -> str:
    """Builds the markdown comment posted on the merge request."""
    parts = ["# 🤖 AI Review Report\n"]

    if outcome.is_blocking:
        parts.append("### ⛔ Pipeline BLOCKED\n")
        for issue in outcome.blocking_issues:
            parts.append(f"- 🔴 {issue}")
    else:
        parts.append("### ✅ Pipeline PASSED\n")

    warnings = outcome.warnings
    if warnings:
        parts.append("\n**Warnings**\n")
        for warning in warnings:
            parts.append(f"- ⚠️ {warning}")

    parts.append(
        f"\n**Policy v{policy_version}** | "
        f"**Files considered**: {outcome.files_considered}\n\n---\n"
    )
    parts.extend(sections)

    return "\n".join(parts)
