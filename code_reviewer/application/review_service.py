"""The review workflow.

Receives every collaborator through its constructor and talks to the outside
world only through ports, so the whole workflow — triage, review, gate,
metrics, publishing — runs against in-memory fakes in a unit test. It used to
be a 150-line function that reached into ``project.mergerequests.get(...)``
directly and therefore had no tests at all (findings F-25, F-27).
"""

from dataclasses import dataclass, field
from typing import List, Optional

from code_reviewer.domain.finding import Finding
from code_reviewer.domain.gate import ReviewGate
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.triage import ReviewDecision, ReviewTriage

from .ports import CodeForge, FileChange, MergeRequestRef, Reviewer, StaticAnalysis
from .report import render_review_comment

#: Triage decisions that call for the model rather than a rule.
NEEDS_REVIEWER = frozenset(
    {ReviewDecision.QUICK_SCAN, ReviewDecision.FULL_REVIEW, ReviewDecision.CRITICAL}
)


@dataclass
class FileMetric:
    """What one file cost and what it produced.

    Deliberately not the infrastructure's ``ReviewMetrics``: the workflow
    reports facts, and the exporter decides how to serialise them.
    """

    file_path: str
    triage_decisions: dict
    gate_result: str
    quality_score: Optional[int]
    lines_analyzed: int
    duration_ms: int = 0
    findings_by_severity: dict = field(default_factory=dict)


@dataclass
class ReviewResult:
    """Everything one review run produced."""

    outcome: ReviewOutcome
    metrics: List[FileMetric] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    comment: str = ""
    exit_code: int = 0


class ReviewService:
    """Reviews one merge request."""

    def __init__(
        self,
        forge: CodeForge,
        reviewer: Reviewer,
        triage: ReviewTriage,
        policy: ReviewPolicy,
        analysis: Optional[StaticAnalysis] = None,
        gate: Optional[ReviewGate] = None,
        clock=None,
    ):
        self._forge = forge
        self._reviewer = reviewer
        self._triage = triage
        self._policy = policy
        # Optional so a caller can review without static analysis; the gate
        # then falls back to reading the model's prose.
        self._analysis = analysis
        self._gate = gate or ReviewGate(policy)
        # Injected so tests are not at the mercy of wall-clock timing.
        self._clock = clock or _monotonic_milliseconds

    def review(self, project_id: int, merge_request_iid: int) -> ReviewResult:
        """Runs the full workflow and returns what happened."""
        reference = self._forge.fetch_merge_request(project_id, merge_request_iid)
        changes = [change for change in self._forge.fetch_changes(reference) if not change.is_deleted]

        outcome = ReviewOutcome()
        result = ReviewResult(outcome=outcome)

        if not changes:
            return result

        # Cross-file context: what else moved in this merge request.
        sibling_paths = [change.path for change in changes]

        sections = []
        for change in changes:
            section, metric, findings = self._review_one(
                reference, change, sibling_paths, outcome
            )
            if section:
                sections.append(section)
            if metric:
                result.metrics.append(metric)
            result.findings.extend(findings or [])

        if sections:
            result.comment = render_review_comment(
                self._policy.version, outcome, sections, result.findings
            )
            self._forge.publish_comment(reference, result.comment)

        result.exit_code = outcome.exit_code(self._policy)
        return result

    def _review_one(
        self,
        reference: MergeRequestRef,
        change: FileChange,
        sibling_paths: List[str],
        outcome: ReviewOutcome,
    ):
        """Triages one file and, if it warrants it, reviews and gates it."""
        started_at = self._clock()

        full_content = self._forge.fetch_file(reference, change.path)
        decision = self._triage.decide(change.diff, change.path, full_content)

        if decision.decision is ReviewDecision.SKIP:
            return None, None, []

        section = None
        gate_result = "pass"
        quality_score = None
        findings = []

        if decision.decision is ReviewDecision.AUTO_APPROVE:
            section = f"## ✅ Auto-Approved: `{change.path}`\n> {decision.reason}\n\n---\n"
            outcome.record_unevaluated(change.path)
        elif decision.decision in NEEDS_REVIEWER:
            # Analysis runs first and unconditionally: whether a file gets a
            # security scan must not depend on the model deciding to ask for
            # one (finding F-32).
            findings = self._analyse(change, full_content)

            review_text = self._reviewer.review_diff(
                change.path,
                change.diff,
                full_content,
                other_files=sibling_paths,
            )
            section = self._render_section(change.path, review_text, findings)

            evaluation = self._gate.evaluate(review_text, findings)
            outcome.record(change.path, evaluation)
            gate_result = evaluation.result.value
            quality_score = evaluation.scores.get("quality")

        metric = FileMetric(
            file_path=change.path,
            triage_decisions={decision.decision.value: 1},
            gate_result=gate_result,
            quality_score=quality_score,
            lines_analyzed=change.changed_line_count,
            duration_ms=self._clock() - started_at,
            findings_by_severity={
                severity.value: count
                for severity, count in Finding.count_by_severity(findings or []).items()
                if count
            },
        )
        return section, metric, findings or []

    def _analyse(self, change: FileChange, full_content):
        """Runs the analysis suite, returning None when none is configured."""
        if self._analysis is None:
            return None
        return self._analysis.analyze(change.path, full_content or "", change.diff)

    @staticmethod
    def _render_section(path: str, review_text: str, findings) -> str:
        """One file's section: what the analyzers found, then what the model said."""
        parts = [f"## Review for `{path}`\n"]

        if findings:
            parts.append("**Static analysis**\n")
            parts.append("| Severity | Finding | Location | Fix |")
            parts.append("|---|---|---|---|")
            for finding in findings[:10]:
                parts.append(
                    f"| {finding.severity.value} | {finding.title} | "
                    f"`{finding.location}` | {finding.remediation} |"
                )
            if len(findings) > 10:
                parts.append(f"\n_{len(findings) - 10} further finding(s) not shown._")
            parts.append("")

        parts.append(review_text)
        parts.append("\n---\n")
        return "\n".join(parts)


def _monotonic_milliseconds() -> int:
    import time

    return int(time.monotonic() * 1000)
