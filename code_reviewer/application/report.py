"""Rendering of the merge-request comment.

Separated from orchestration so both verdict branches can be asserted without a
GitLab instance. The blocked branch was previously unreachable: the flag that
selected it was a string compared against a ``ReviewGateResult`` (finding F-01).
"""

from collections.abc import Sequence

from code_reviewer.domain.finding import Finding
from code_reviewer.domain.outcome import ReviewOutcome


def render_review_comment(
    policy_version: str,
    outcome: ReviewOutcome,
    sections: Sequence[str],
    findings: Sequence[Finding] | None = None,
) -> str:
    """Builds the markdown comment posted on the merge request."""
    parts = ["# 🤖 AI Review Report\n"]

    if outcome.is_blocking:
        parts.append("### ⛔ Pipeline BLOCKED\n")
        for issue in outcome.blocking_issues:
            parts.append(f"- 🔴 {issue}")
    else:
        parts.append("### ✅ Pipeline PASSED\n")

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
        breakdown = ", ".join(
            f"{count} {severity.value}" for severity, count in counts.items() if count
        )
        parts.append(f"\n**Static analysis**: {len(findings)} finding(s) — {breakdown}\n")

    parts.append(
        f"\n**Policy v{policy_version}** | "
        f"**Files considered**: {outcome.files_considered}\n\n---\n"
    )
    parts.extend(sections)

    return "\n".join(parts)
