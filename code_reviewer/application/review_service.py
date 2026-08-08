"""The review workflow.

Receives every collaborator through its constructor and talks to the outside
world only through ports, so the whole workflow — triage, review, gate,
metrics, publishing — runs against in-memory fakes in a unit test. It used to
be a 150-line function that reached into ``project.mergerequests.get(...)``
directly and therefore had no tests at all (findings F-25, F-27).
"""

import logging
from dataclasses import dataclass, field

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.gate import ReviewGate
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.triage import ReviewDecision, ReviewTriage

from .ports import (
    AccessAuditor,
    AccessViolation,
    CodeForge,
    FileChange,
    MergeRequestRef,
    Reviewer,
    StaticAnalysis,
)
from .report import render_review_comment

# Standard logging, not the infrastructure helper: the application layer may
# not import downwards. Every module in this package lives under the
# `code_reviewer` logger hierarchy, so the configuration applied in
# infrastructure.observability still governs these records.
logger = logging.getLogger(__name__)

#: Triage decisions that call for the model rather than a rule.
NEEDS_REVIEWER = frozenset({ReviewDecision.QUICK_SCAN, ReviewDecision.FULL_REVIEW, ReviewDecision.CRITICAL})


@dataclass
class FileMetric:
    """What one file cost and what it produced.

    Deliberately not the infrastructure's ``ReviewMetrics``: the workflow
    reports facts, and the exporter decides how to serialise them.
    """

    file_path: str
    triage_decisions: dict
    gate_result: str
    quality_score: int | None
    lines_analyzed: int
    duration_ms: int = 0
    findings_by_severity: dict = field(default_factory=dict)


@dataclass
class ReviewResult:
    """Everything one review run produced."""

    outcome: ReviewOutcome
    metrics: list[FileMetric] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
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
        analysis: StaticAnalysis | None = None,
        gate: ReviewGate | None = None,
        access_auditor: AccessAuditor | None = None,
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
        # Optional so a caller without a sandbox still reviews. When present,
        # a refused file access becomes a finding on the file being reviewed.
        self._access_auditor = access_auditor
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
            # One file's failure costs that file, not the run: propagating the
            # exception discarded every review completed so far and posted
            # nothing (finding F-58).
            try:
                section, metric, findings = self._review_one(reference, change, sibling_paths, outcome)
            except Exception as exc:
                logger.error(
                    "Could not review file",
                    extra={"fields": {"path": change.path, "error": str(exc)}},
                    exc_info=True,
                )
                outcome.record_failure(change.path, str(exc))
                sections.append(
                    f"## ⚠️ Could not review `{change.path}`\n"
                    f"> The reviewer failed on this file: {exc}\n"
                    f"> Treat it as unreviewed rather than as approved.\n\n---\n"
                )
                continue
            if section:
                sections.append(section)
            if metric:
                result.metrics.append(metric)
            result.findings.extend(findings or [])

        if sections:
            result.comment = render_review_comment(self._policy.version, outcome, sections, result.findings)
            self._forge.publish_comment(reference, result.comment)

        result.exit_code = outcome.exit_code(self._policy)
        return result

    def _review_one(
        self,
        reference: MergeRequestRef,
        change: FileChange,
        sibling_paths: list[str],
        outcome: ReviewOutcome,
    ):
        """Triages one file and, if it warrants it, reviews and gates it."""
        started_at = self._clock()

        full_content = self._forge.fetch_file(reference, change.path)
        decision = self._triage.decide(change.diff, change.path, full_content)
        logger.info(
            "Triaged",
            extra={
                "fields": {
                    "path": change.path,
                    "decision": decision.decision.value,
                    "reason": decision.reason,
                }
            },
        )

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
            # one (finding F-32). A failing analyzer degrades the review to
            # prose rather than losing the file entirely.
            findings = self._analyse(change, full_content)

            # Counted before the reviewer runs, so what it triggers is
            # attributable to *this* file rather than to the whole run.
            violations_before = self._violation_count()

            review_text = self._reviewer.review_diff(
                change.path,
                change.diff,
                full_content,
                other_files=sibling_paths,
            )

            refusals = self._refusal_findings(change.path, violations_before)
            if refusals:
                findings = list(findings or []) + refusals

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

    def _violation_count(self) -> int:
        """How many refusals the auditor has seen so far, or zero without one."""
        if self._access_auditor is None:
            return 0
        return len(self._access_auditor.access_violations())

    def _refusal_findings(self, file_path: str, seen_before: int) -> list[Finding]:
        """Turns refusals raised while reviewing ``file_path`` into findings.

        The agent asked for those paths because something in this file's diff
        led it to, so the refusal is evidence about the merge request. Making
        it a `Finding` is what puts it in front of the gate: prose warns,
        findings block (ADR 0004), and an injection attempt is worth blocking.
        """
        if self._access_auditor is None:
            return []

        new_violations = self._access_auditor.access_violations()[seen_before:]
        return [self._to_finding(file_path, violation) for violation in new_violations]

    @staticmethod
    def _to_finding(file_path: str, violation: AccessViolation) -> Finding:
        return Finding(
            category=FindingCategory.SECURITY,
            severity=Severity.CRITICAL,
            file_path=file_path,
            line_number=0,
            title="Refused File Access",
            description=(
                f"While reviewing this file the agent attempted to read "
                f"'{violation.path}', which was refused: {violation.reason}. The paths "
                f"the agent asks for come from the content under review, so this is a "
                f"likely prompt-injection attempt in the diff."
            ),
            remediation=(
                "Read the diff for text addressed to an automated reviewer. If the "
                "attempt is deliberate, treat the merge request as hostile; if it is "
                "not, the file path came from somewhere and that source is worth finding."
            ),
            rule_id="sandbox_violation",
            cwe_id="CWE-77",
            owasp_category="LLM01:2025 Prompt Injection",
            evidence=violation.path,
        )

    def _analyse(self, change: FileChange, full_content):
        """Runs the analysis suite, returning None when none ran.

        A broken analyzer must not cost the file its model review: the result
        is a review with less evidence, which the gate handles by falling back
        to the prose path.
        """
        if self._analysis is None:
            return None
        try:
            return self._analysis.analyze(change.path, full_content or "", change.diff)
        except Exception as exc:
            logger.error(
                "Static analysis failed; continuing without it",
                extra={"fields": {"path": change.path, "error": str(exc)}},
                exc_info=True,
            )
            return None

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
