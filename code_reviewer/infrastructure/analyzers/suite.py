"""Runs every analyzer over a file and returns findings in one vocabulary.

Two problems this solves.

The analyzers were reachable only as agent tools, so whether a file got a
security scan depended on whether the model chose to ask for one. A review
could be produced with no analysis behind it, and nothing in the report said
so.

And each analyzer returned its own result type, so the gate could not read
them. It recovered a quality score and a risk level by running regular
expressions over the model's prose instead — which meant the pipeline decision
rested on the model's formatting (finding F-32).

The suite runs the analyzers unconditionally and translates their reports into
the shared :class:`~code_reviewer.domain.finding.Finding`. Each analyzer keeps
its own internal report type: rewriting five of them to emit the domain type
directly would be a large change with no behavioural gain, and their tests pin
the current output (decision D-2).
"""

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.severity import Severity

from .performance import PerformanceAnalyzer
from .quality import QualityAnalyzer
from .sast import SASTAnalyzer
from .semantic import SemanticChangeAnalyzer

#: Change types the semantic analyzer reports that warrant a finding of their
#: own. A refactor or a feature is normal; a breaking change is not.
_SEMANTIC_SEVERITY = {
    "breaking": Severity.HIGH,
}


class StaticAnalysisSuite:
    """Every analyzer, one call, one vocabulary."""

    def __init__(self, policy: ReviewPolicy | None = None):
        self._policy = policy
        self._sast = SASTAnalyzer()
        self._quality = QualityAnalyzer(policy.quality if policy else None)
        self._performance = PerformanceAnalyzer(policy.performance if policy else None)
        self._semantic = SemanticChangeAnalyzer()

    def analyze(self, file_path: str, content: str, diff: str = "") -> list[Finding]:
        """Analyses one file, returning findings most severe first.

        An analyzer that cannot handle the input contributes nothing rather
        than failing the review: a syntax error in a half-finished branch is a
        reason to say less, not a reason to abort.
        """
        findings: list[Finding] = []

        if content:
            findings.extend(self._security_findings(file_path, content))
            findings.extend(self._quality_findings(file_path, content))
            findings.extend(self._performance_findings(file_path, content))

        if diff:
            findings.extend(self._semantic_findings(file_path, content, diff))

        return sorted(findings)

    # -- per-analyzer adapters ----------------------------------------------

    def _security_findings(self, file_path: str, content: str) -> list[Finding]:
        try:
            report = self._sast.analyze(content, file_path)
        except Exception:
            return []

        return [
            Finding(
                category=FindingCategory.SECURITY,
                severity=item.severity,
                file_path=file_path,
                line_number=item.line_number,
                title=item.vulnerability_type.value.replace("_", " ").title(),
                description=item.description,
                remediation=item.recommendation,
                rule_id=item.vulnerability_type.value,
                cwe_id=item.cwe_id,
                owasp_category=item.owasp_category,
                evidence=item.line_content,
            )
            for item in report.findings
        ]

    def _quality_findings(self, file_path: str, content: str) -> list[Finding]:
        try:
            report = self._quality.analyze(content, file_path)
        except Exception:
            return []

        return [
            Finding(
                category=FindingCategory.QUALITY,
                severity=issue.severity,
                file_path=file_path,
                line_number=issue.line_number,
                title=issue.category.value.replace("_", " ").upper(),
                description=issue.description,
                remediation=issue.suggestion,
                rule_id=issue.category.value,
                evidence=issue.symbol_name,
                metrics=dict(issue.metrics),
            )
            for issue in report.all_issues
        ]

    def _performance_findings(self, file_path: str, content: str) -> list[Finding]:
        try:
            report = self._performance.analyze(content, file_path)
        except Exception:
            return []

        return [
            Finding(
                category=FindingCategory.PERFORMANCE,
                severity=issue.severity,
                file_path=file_path,
                line_number=issue.line_number,
                title=issue.issue_type.value.replace("_", " ").title(),
                description=issue.description,
                remediation=issue.suggestion,
                rule_id=issue.issue_type.value,
                evidence=issue.complexity or issue.symbol_name,
                metrics=dict(issue.metrics),
            )
            for issue in report.issues
        ]

    def _semantic_findings(self, file_path: str, content: str, diff: str) -> list[Finding]:
        try:
            analysis = self._semantic.analyze_diff(diff, content or None, file_path)
        except Exception:
            return []

        findings = []

        severity = _SEMANTIC_SEVERITY.get(analysis.change_type.value)
        for breaking in analysis.breaking_changes:
            findings.append(
                Finding(
                    category=FindingCategory.SEMANTIC,
                    severity=severity or Severity.HIGH,
                    file_path=file_path,
                    line_number=breaking.symbol.line_start,
                    title="Breaking Change",
                    description=breaking.reason,
                    remediation="Update every caller, or keep a deprecated shim for one release",
                    rule_id="breaking_change",
                    evidence=breaking.symbol.name,
                )
            )

        for issue in analysis.integrity_issues:
            findings.append(
                Finding(
                    category=FindingCategory.SEMANTIC,
                    severity=Severity.LOW,
                    file_path=file_path,
                    line_number=0,
                    title=issue.issue_type.replace("_", " ").title(),
                    description=issue.description,
                    remediation=issue.suggestion,
                    rule_id=issue.issue_type,
                )
            )

        return findings
