"""Merge-request-level aggregation of per-file gate evaluations.

The orchestrator used to keep the overall verdict in a plain string and compare
it against ``GateEvaluation.result``, which is a ``ReviewGateResult``. Since the
enum does not subclass ``str``, the comparison never matched: the pipeline could
not be blocked, however severe the findings (finding F-01).

This aggregate removes the representation that allowed the mistake. Gate
evaluations go in, an enum verdict comes out, and the exit code is derived from
policy rather than from an ad-hoc flag.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .policy import ReviewPolicy
from .gate import GateEvaluation, ReviewGateResult

#: Ordered from most to least permissive; the aggregate verdict is the worst.
_SEVERITY_ORDER = {
    ReviewGateResult.PASS: 0,
    ReviewGateResult.WARN: 1,
    ReviewGateResult.FAIL: 2,
}


@dataclass
class ReviewOutcome:
    """The verdict for a whole merge request.

    Files that never reach the gate — skipped or auto-approved — are recorded
    with :meth:`record_unevaluated` so that reporting can state how many files
    were considered without those files influencing the verdict.
    """

    evaluations: List[Tuple[str, GateEvaluation]] = field(default_factory=list)
    unevaluated_files: List[str] = field(default_factory=list)
    #: Files the reviewer could not process, with the reason. "The reviewer
    #: crashed here" is not evidence that the file is fine (finding F-58).
    failed_files: List[Tuple[str, str]] = field(default_factory=list)

    def record(self, file_path: str, evaluation: GateEvaluation) -> None:
        self.evaluations.append((file_path, evaluation))

    def record_unevaluated(self, file_path: str) -> None:
        self.unevaluated_files.append(file_path)

    def record_failure(self, file_path: str, reason: str) -> None:
        """Records that a file could not be reviewed at all."""
        self.failed_files.append((file_path, reason))

    @property
    def result(self) -> ReviewGateResult:
        """The worst verdict across all evaluated files.

        A file that could not be reviewed is at least a warning: the review
        has less evidence than it appears to.
        """
        verdicts = [evaluation.result for _, evaluation in self.evaluations]
        if self.failed_files:
            verdicts.append(ReviewGateResult.WARN)
        if not verdicts:
            return ReviewGateResult.PASS
        return max(verdicts, key=lambda result: _SEVERITY_ORDER[result])

    @property
    def has_failures(self) -> bool:
        return bool(self.failed_files)

    @property
    def is_blocking(self) -> bool:
        return self.result is ReviewGateResult.FAIL

    @property
    def blocking_issues(self) -> List[str]:
        """Blocking issues, each attributed to the file that raised it."""
        return [
            f"{file_path}: {issue}"
            for file_path, evaluation in self.evaluations
            for issue in evaluation.blocking_issues
        ]

    @property
    def warnings(self) -> List[str]:
        gate_warnings = [
            f"{file_path}: {reason}"
            for file_path, evaluation in self.evaluations
            for reason in evaluation.reasons
        ]
        failures = [
            f"{file_path}: could not be reviewed — {reason}"
            for file_path, reason in self.failed_files
        ]
        return gate_warnings + failures

    @property
    def files_considered(self) -> int:
        return len(self.evaluations) + len(self.unevaluated_files) + len(self.failed_files)

    def exit_code(self, policy: ReviewPolicy) -> int:
        """Process exit code implied by this outcome under ``policy``.

        A blocking outcome only fails the pipeline if the policy asks for it,
        which lets a team roll the agent out in observation mode first.
        """
        if self.is_blocking and policy.gate.fail_pipeline_on_critical:
            return 1
        if self.failed_files and policy.gate.fail_on_review_error:
            return 1
        return 0

    def worst_quality_score(self) -> Optional[int]:
        """Lowest reported quality score, or ``None`` if none was reported."""
        scores = [
            evaluation.scores.get("quality")
            for _, evaluation in self.evaluations
            if evaluation.scores.get("quality") is not None
        ]
        return min(scores) if scores else None
