"""The review gate: turning a review into a pipeline decision.

Turns one file's review into a `PASS` / `WARN` / `FAIL` decision.

Evidence comes from two places and they are not equal:

- **Findings** produced by the static analyzers. Deterministic, located,
  reproducible. These decide whether the pipeline is blocked.
- **The model's prose**. It carries architectural judgement no analyzer
  produces, but it is generated text, and recovering numbers from it with
  regular expressions makes the pipeline decision depend on formatting. It
  therefore contributes warnings, not blocks, whenever findings are available
  (finding F-32, decision D-1).

Each reason states which source produced it, so a reader can tell an analyzer's
verdict from the model's opinion.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from .finding import Finding
from .policy import ReviewPolicy
from .severity import Severity


class ReviewGateResult(Enum):
    """Pipeline karar sonucu."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class GateEvaluation:
    """One file's verdict, with everything that produced it.

    A value in ``scores`` may be ``None``: when neither the findings nor the
    report yielded a number, the score is *unknown*, which is not zero
    (finding F-10).
    """

    result: ReviewGateResult
    exit_code: int
    reasons: list[str]
    scores: dict[str, int | None]
    blocking_issues: list[str]
    #: Findings that caused the block, so the report can show where they are.
    blocking_findings: list[Finding] = field(default_factory=list)


class ReviewGate:
    """
    Evaluates one file's review.

    What it looks at:
    - analyzer findings, blocking at or above the policy's severity threshold
    - the quality score, computed from findings or, failing that, parsed
    - SAST Scan Result (Pass/Fail)
    - Security Risk Level (Critical/High)
    - Breaking Changes
    """

    def __init__(self, policy: ReviewPolicy):
        self.policy = policy

    def evaluate(
        self,
        review_markdown: str,
        findings: Sequence[Finding] | None = None,
    ) -> GateEvaluation:
        """
        Evaluates one file's review.

        Args:
            review_markdown: The report the model produced.
            findings: Static analysis findings. ``None`` means no analysis ran;
                an empty list means it ran and found nothing. When analysis ran,
                the blocking decision comes from the findings and the report
                text can only warn.

        Returns:
            GateEvaluation: the verdict and its reasons.
        """
        # `None` means no analysis ran; `[]` means it ran and found nothing.
        # The difference matters: a clean analysis is evidence, and the prose
        # should not be allowed to override it.
        analysis_ran = findings is not None
        findings = list(findings) if findings else []

        reasons: list[str] = []
        blocking_issues: list[str] = []
        blocking_findings: list[Finding] = []
        scores: dict[str, int | None] = {}

        if analysis_ran:
            self._evaluate_findings(findings, reasons, blocking_issues, blocking_findings, scores)

        prose_blocks = self._evaluate_prose(
            review_markdown, reasons, blocking_issues, scores, have_findings=analysis_ran
        )

        result = ReviewGateResult.PASS
        exit_code = 0

        if blocking_issues or prose_blocks:
            result = ReviewGateResult.FAIL
            exit_code = 1
        elif reasons:
            result = ReviewGateResult.WARN
            exit_code = 0  # a warning does not break the pipeline

        return GateEvaluation(
            result=result,
            exit_code=exit_code,
            reasons=reasons,
            scores=scores,
            blocking_issues=blocking_issues,
            blocking_findings=blocking_findings,
        )

    # -- findings -----------------------------------------------------------

    @property
    def blocking_severity(self) -> Severity:
        """Severity at or above which a finding fails the pipeline."""
        return Severity.parse(self.policy.gate.blocking_severity, default=Severity.CRITICAL)

    def _evaluate_findings(self, findings, reasons, blocking_issues, blocking_findings, scores):
        """Blocks on severe findings and scores quality from what was found."""
        threshold = self.blocking_severity

        for finding in findings:
            if finding.severity.is_at_least(threshold):
                blocking_findings.append(finding)
                blocking_issues.append(
                    f"[analysis] {finding.severity.value.upper()} {finding.title} "
                    f"at {finding.location} — {finding.description}"
                )

        counts = Finding.count_by_severity(findings)
        for severity in (Severity.HIGH, Severity.MEDIUM):
            if severity.is_at_least(threshold):
                continue  # already blocking, no need to warn as well
            if counts[severity]:
                reasons.append(f"[analysis] {counts[severity]} {severity.value} finding(s) reported")

        quality_score = self.score_from_findings(findings)
        scores["quality"] = quality_score

        if quality_score < self.policy.gate.quality_score_threshold:
            message = (
                f"[analysis] Quality score {quality_score} is below the threshold "
                f"{self.policy.gate.quality_score_threshold}"
            )
            if quality_score < self.policy.gate.fail_pipeline_on_quality_below:
                blocking_issues.append(message)
            else:
                reasons.append(message)

    @staticmethod
    def score_from_findings(findings: Sequence[Finding]) -> int:
        """Reduces findings to a 0-100 score using each severity's weight.

        Computed rather than parsed: the analyzers already know what they
        found, and asking the model to restate it as a number only introduces a
        way for the number to be wrong.
        """
        penalty = sum(finding.severity.weight for finding in findings)
        return max(0, 100 - penalty)

    # -- prose --------------------------------------------------------------

    def _evaluate_prose(self, review_markdown, reasons, blocking_issues, scores, have_findings):
        """Reads the model's own verdict. Returns True if it alone should block.

        With findings available the prose can only warn: it is generated text,
        and a pipeline that fails on a phrasing change is not a pipeline anyone
        trusts. Without findings it retains its blocking power, so callers that
        have no analyzer available are no worse off than before.
        """
        prose_blocks = False

        # The prompt asks for `- **SAST Scan Result**: FAIL - <level>`; matching
        # is tolerant of the emphasis markers and brackets the template shows
        # (finding F-57).
        if re.search(r"SAST\s+Scan\s+Result\**\s*:\s*\**\s*\[?\s*FAIL", review_markdown, re.IGNORECASE):
            reasons.append("[review] SAST Scan Failed")
            if not have_findings:
                prose_blocks = True

        risk_match = re.search(r"Risk Assessment\*\*:\s*\[?(\w+)\]?", review_markdown)
        risk_level = risk_match.group(1).lower() if risk_match else "unknown"

        if risk_level == "critical" and self.policy.gate.fail_pipeline_on_critical:
            if have_findings:
                reasons.append("[review] Critical risk assessment")
            else:
                blocking_issues.append("Critical Risk Assessment")

        if not have_findings:
            # A missing score is unknown, not zero. Defaulting to 0 meant that
            # any drift in the model's formatting scored below every threshold
            # and blocked the merge request for a reason nobody could act on
            # (finding F-10).
            quality_match = re.search(r"SOLID Compliance\*\*:\s*\[?(\d+)/100\]?", review_markdown)
            quality_score = int(quality_match.group(1)) if quality_match else None
            scores["quality"] = quality_score

            if quality_score is None:
                reasons.append(
                    "Quality score not reported by the review — the report is missing a "
                    "'SOLID Compliance: n/100' line, so the quality gate was not applied"
                )
            elif quality_score < self.policy.gate.quality_score_threshold:
                message = (
                    f"Quality Score ({quality_score}) below threshold "
                    f"({self.policy.gate.quality_score_threshold})"
                )
                if self.policy.gate.fail_pipeline_on_quality_below > quality_score:
                    blocking_issues.append(message)
                else:
                    reasons.append(message)

        if "Breaking Changes**: Yes" in review_markdown:
            if self.policy.security.block_on_critical:
                reasons.append("Breaking Changes Detected")

        return prose_blocks
