"""Metrics collection and export.

GitLab reads ``metrics.txt`` as an OpenMetrics text report and shows the values
on the merge request. Two things made that report untrustworthy:

- only the last analysed file was serialised, so a merge request touching
  twelve files reported the twelfth and discarded eleven (finding F-16);
- ``security_score``, ``performance_score``, ``critical_issues``,
  ``high_issues`` and ``medium_issues`` were declared, exported and never
  populated, so a dashboard built on them showed a flat line and was believed
  (finding F-17).

The collector now aggregates every recorded file, and every exported series is
derived from something the review actually produced. Fields nothing could fill
were removed rather than exported as zero.
"""

import json
import time
from dataclasses import asdict, dataclass, field

from code_reviewer.infrastructure.observability.logging import get_logger

logger = get_logger(__name__)

#: Gate results ordered from best to worst; the aggregate takes the worst.
_GATE_SEVERITY = {"pass": 0, "warn": 1, "fail": 2}

#: Series descriptions, emitted as `# HELP`. Every series needs one: a metric
#: whose meaning has to be guessed is a metric that gets misread.
_HELP = {
    "code_review_files_analyzed": ("Files analysed in this review", "gauge"),
    "code_review_lines_analyzed": ("Diff lines analysed in this review", "gauge"),
    "code_review_quality_score": ("Lowest quality score across analysed files", "gauge"),
    "code_review_findings": ("Static analysis findings, by severity", "gauge"),
    "code_review_triage_decisions": ("Triage decisions, by decision", "gauge"),
    "code_review_gate_passed": ("1 when the gate passed, 0 when it failed", "gauge"),
    "code_review_duration_ms": ("Total time spent analysing, in milliseconds", "gauge"),
    "code_review_slowest_file_ms": ("Time spent on the slowest single file", "gauge"),
    "code_review_agent_runs": ("Specialist agent invocations, by agent", "gauge"),
    "code_review_agent_failures": ("Specialist agents that did not complete, by agent", "gauge"),
    "code_review_agent_tool_calls": ("Tool calls made by a specialist agent, by agent", "gauge"),
    "code_review_recurring_findings": (
        "Findings this project has reported before, from its own review history",
        "gauge",
    ),
}


@dataclass
class ReviewMetrics:
    """What one file's review cost and produced."""

    project_id: str
    mr_id: str
    file_path: str = ""
    timestamp: float = field(default_factory=time.time)

    lines_analyzed: int = 0
    triage_decisions: dict[str, int] = field(default_factory=dict)
    gate_result: str = "pass"

    #: ``None`` when no score could be established, which is not the same as 0.
    quality_score: int | None = None

    #: Counts keyed by severity value, from the findings the workflow recorded.
    findings_by_severity: dict[str, int] = field(default_factory=dict)

    #: How many of this file's findings previous reviews had already reported.
    #: Zero without a project memory, which is also the honest answer: with no
    #: history, nothing is known to recur (Level 14).
    recurring_findings: int = 0

    duration_ms: int = 0


@dataclass
class ReviewAggregate:
    """Every recorded file, reduced to the numbers worth exporting."""

    project_id: str = ""
    mr_id: str = ""
    files_analyzed: int = 0
    lines_analyzed: int = 0
    triage_decisions: dict[str, int] = field(default_factory=dict)
    findings_by_severity: dict[str, int] = field(default_factory=dict)
    gate_result: str = "pass"
    quality_score: int | None = None
    duration_ms: int = 0
    slowest_file_ms: int = 0
    recurring_findings: int = 0
    #: Per specialist agent: runs, failures and tool calls, keyed by the
    #: agent's name. Empty under `--single-agent`, which is the honest answer:
    #: with one agent there is nothing to attribute (Level 15).
    agents: dict[str, tuple[int, int, int]] = field(default_factory=dict)

    @property
    def total_findings(self) -> int:
        return sum(self.findings_by_severity.values())


class MetricsCollector:
    """Collects per-file metrics and exports the review as a whole."""

    def __init__(self):
        self._metrics: list[ReviewMetrics] = []

    def record(self, metrics: ReviewMetrics) -> None:
        self._metrics.append(metrics)

    @property
    def records(self) -> list[ReviewMetrics]:
        return list(self._metrics)

    def aggregate(self) -> ReviewAggregate:
        """Reduces every recorded file to one review-level view."""
        aggregate = ReviewAggregate()
        if not self._metrics:
            return aggregate

        first = self._metrics[0]
        aggregate.project_id = first.project_id
        aggregate.mr_id = first.mr_id
        aggregate.files_analyzed = len(self._metrics)

        scores = []
        for metric in self._metrics:
            aggregate.lines_analyzed += metric.lines_analyzed
            aggregate.duration_ms += metric.duration_ms
            aggregate.slowest_file_ms = max(aggregate.slowest_file_ms, metric.duration_ms)
            aggregate.recurring_findings += metric.recurring_findings

            for decision, count in metric.triage_decisions.items():
                aggregate.triage_decisions[decision] = aggregate.triage_decisions.get(decision, 0) + count

            for severity, count in metric.findings_by_severity.items():
                aggregate.findings_by_severity[severity] = (
                    aggregate.findings_by_severity.get(severity, 0) + count
                )

            if _GATE_SEVERITY.get(metric.gate_result, 0) > _GATE_SEVERITY.get(aggregate.gate_result, 0):
                aggregate.gate_result = metric.gate_result

            if metric.quality_score is not None:
                scores.append(metric.quality_score)

        # The lowest score is the one worth alerting on: an average would let a
        # clean file hide a bad one.
        aggregate.quality_score = min(scores) if scores else None

        return aggregate

    def export_prometheus(self, agents: dict[str, tuple[int, int, int]] | None = None) -> str:
        """Renders the aggregate as OpenMetrics text.

        Each series carries ``# HELP`` and ``# TYPE``; without them GitLab's
        metrics report and most scrapers treat the file as malformed.

        ``agents`` carries per-specialist totals, which are a property of the
        reviewer rather than of any one file — so they arrive here rather than
        being summed out of the per-file records (Level 15).
        """
        if not self._metrics:
            return ""

        aggregate = self.aggregate()
        aggregate.agents = dict(agents or {})
        labels = f'project_id="{aggregate.project_id}",mr_id="{aggregate.mr_id}"'
        lines: list[str] = []

        def emit(name: str, value, extra_labels: str = "") -> None:
            help_text, metric_type = _HELP[name]
            if not any(line.startswith(f"# HELP {name} ") for line in lines):
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {metric_type}")
            all_labels = f"{labels},{extra_labels}" if extra_labels else labels
            lines.append(f"{name}{{{all_labels}}} {value}")

        emit("code_review_files_analyzed", aggregate.files_analyzed)
        emit("code_review_lines_analyzed", aggregate.lines_analyzed)

        if aggregate.quality_score is not None:
            emit("code_review_quality_score", aggregate.quality_score)

        for severity, count in sorted(aggregate.findings_by_severity.items()):
            emit("code_review_findings", count, f'severity="{severity}"')

        for decision, count in sorted(aggregate.triage_decisions.items()):
            emit("code_review_triage_decisions", count, f'decision="{decision}"')

        emit("code_review_gate_passed", 1 if aggregate.gate_result != "fail" else 0)
        emit("code_review_duration_ms", aggregate.duration_ms)
        emit("code_review_slowest_file_ms", aggregate.slowest_file_ms)
        emit("code_review_recurring_findings", aggregate.recurring_findings)

        for agent, (runs, failures, tool_calls) in sorted(aggregate.agents.items()):
            label = f'agent="{agent}"'
            emit("code_review_agent_runs", runs, label)
            emit("code_review_agent_failures", failures, label)
            emit("code_review_agent_tool_calls", tool_calls, label)

        return "\n".join(lines)

    def export_gitlab_metrics(
        self, file_path: str = "metrics.txt", agents: dict[str, tuple[int, int, int]] | None = None
    ) -> None:
        """Writes the OpenMetrics report GitLab picks up as an artifact."""
        content = self.export_prometheus(agents)
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(content)
        except Exception as e:
            logger.error(
                "Could not export metrics",
                extra={"fields": {"path": file_path, "error": str(e)}},
            )

    def export_json(self, file_path: str = "review_metrics.json") -> None:
        """Writes every per-file record, for offline analysis."""
        data = [asdict(metric) for metric in self._metrics]
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
        except Exception as e:
            logger.error(
                "Could not export JSON metrics",
                extra={"fields": {"path": file_path, "error": str(e)}},
            )
