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

from .gate import GateEvaluation, ReviewGateResult
from .policy import ReviewPolicy

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

    evaluations: list[tuple[str, GateEvaluation]] = field(default_factory=list)
    unevaluated_files: list[str] = field(default_factory=list)
    #: Files the reviewer could not process, with the reason. "The reviewer
    #: crashed here" is not evidence that the file is fine (finding F-58).
    failed_files: list[tuple[str, str]] = field(default_factory=list)
    #: Files whose static analysis could not run, with the reason. Distinct
    #: from `failed_files`: the narration failing costs the report its prose,
    #: while the analysis failing costs it its evidence (finding G-09).
    unanalysed_files: list[tuple[str, str]] = field(default_factory=list)

    def record(self, file_path: str, evaluation: GateEvaluation) -> None:
        self.evaluations.append((file_path, evaluation))

    def record_unevaluated(self, file_path: str) -> None:
        self.unevaluated_files.append(file_path)

    def record_failure(self, file_path: str, reason: str) -> None:
        """Records that a file could not be reviewed at all."""
        self.failed_files.append((file_path, reason))

    def record_unanalysed(self, file_path: str, reason: str) -> None:
        """Records that static analysis could not run on a file.

        Zero findings from a crashed analyzer is not the same fact as zero
        findings from a clean one, and only one of them is evidence.
        """
        self.unanalysed_files.append((file_path, reason))

    @property
    def result(self) -> ReviewGateResult:
        """The worst verdict across all evaluated files.

        A file that could not be reviewed is at least a warning: the review
        has less evidence than it appears to.
        """
        verdicts = [evaluation.result for _, evaluation in self.evaluations]
        if self.failed_files:
            verdicts.append(ReviewGateResult.WARN)
        if self.unanalysed_files:
            # Not a warning. A file nobody could analyse is a file nobody
            # knows anything about, and the review says less than it appears
            # to (finding G-09).
            verdicts.append(ReviewGateResult.FAIL)
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
    def has_unanalysed(self) -> bool:
        return bool(self.unanalysed_files)

    @property
    def blocking_issues(self) -> list[str]:
        """Blocking issues, each attributed to the file that raised it."""
        from_findings = [
            f"{file_path}: {issue}"
            for file_path, evaluation in self.evaluations
            for issue in evaluation.blocking_issues
        ]
        from_analysis = [
            f"{file_path}: [analysis] static analysis could not run — {reason}. "
            f"Zero findings here means the file was not examined, not that it is clean."
            for file_path, reason in self.unanalysed_files
        ]
        return from_findings + from_analysis

    @property
    def warnings(self) -> list[str]:
        gate_warnings = [
            f"{file_path}: {reason}"
            for file_path, evaluation in self.evaluations
            for reason in evaluation.reasons
        ]
        failures = [
            f"{file_path}: could not be reviewed — {reason}" for file_path, reason in self.failed_files
        ]
        # Listed as warnings too, so that turning the block off with
        # `fail_pipeline_on_analysis_error: false` does not also turn off the
        # knowledge that it happened.
        unanalysed = [
            f"{file_path}: static analysis could not run — {reason}"
            for file_path, reason in self.unanalysed_files
        ]
        return gate_warnings + failures + unanalysed

    @property
    def files_considered(self) -> int:
        return (
            len(self.evaluations)
            + len(self.unevaluated_files)
            + len(self.failed_files)
            + len(self.unanalysed_files)
        )

    def exit_code(self, policy: ReviewPolicy) -> int:
        """Process exit code implied by this outcome under ``policy``.

        A blocking outcome only fails the pipeline if the policy asks for it,
        which lets a team roll the agent out in observation mode first.
        """
        if self.unanalysed_files and policy.gate.fail_pipeline_on_analysis_error:
            return 1
        if self.is_blocking and policy.gate.fail_pipeline_on_critical:
            # An unanalysed file makes `result` FAIL on its own, so without
            # the check above this branch would block even when the operator
            # asked it not to.
            if not self._blocking_is_only_unanalysed():
                return 1
        if self.failed_files and policy.gate.fail_on_review_error:
            return 1
        return 0

    def _blocking_is_only_unanalysed(self) -> bool:
        """True when nothing but an unanalysed file made the verdict FAIL."""
        return not any(evaluation.result is ReviewGateResult.FAIL for _, evaluation in self.evaluations)

    def worst_quality_score(self) -> int | None:
        """Lowest reported quality score, or ``None`` if none was reported."""
        scores: list[int] = []
        for _, evaluation in self.evaluations:
            score = evaluation.scores.get("quality")
            if score is not None:
                scores.append(score)
        return min(scores) if scores else None
