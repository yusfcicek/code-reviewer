"""Turning a finished review into a record somebody can audit.

Built from what the review already produced — the outcome, its findings, the
policy, the run's identity and the orchestrator's totals. No second pass, no
re-analysis, no extra model call: anything the record cannot get from those is
a thing this level does not claim (decision D-6).

The attribution table is the part worth reading twice. A finding's producer is
derived from its rule namespace, and the **default is an agent** — that is,
non-deterministic, and therefore unable to block. An unattributable claim is
treated as an opinion, which is the fail-closed reading; a test asserts that
every namespace the analysis suite can emit is registered, so the default
never fires in practice and a new one is a red test rather than a silent
misattribution.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from code_reviewer.domain.finding import Finding
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.provenance import (
    AgentCost,
    DecisionRecord,
    Producer,
    ProducerKind,
    Provenance,
    RunIdentity,
    SuppressionRecord,
)

logger = logging.getLogger(__name__)

#: Which rule namespace was produced by what. The analyzers are deterministic;
#: the sandbox is a tool reporting a fact about the request rather than an
#: opinion about the code, which is why a refused read has been allowed to
#: block since Level 8.
PRODUCERS: Mapping[str, tuple[ProducerKind, str]] = {
    "SAST": (ProducerKind.ANALYZER, "SASTAnalyzer"),
    "QUALITY": (ProducerKind.ANALYZER, "QualityAnalyzer"),
    "PERFORMANCE": (ProducerKind.ANALYZER, "PerformanceAnalyzer"),
    "SEMANTIC": (ProducerKind.ANALYZER, "SemanticChangeAnalyzer"),
    "DEPENDENCY": (ProducerKind.ANALYZER, "DependencyTracker"),
    "SANDBOX": (ProducerKind.TOOL, "Workspace"),
}

#: What an unregistered namespace is treated as. Non-deterministic, and
#: therefore unable to block: an unattributable claim is an opinion until
#: somebody says otherwise.
UNKNOWN_PRODUCER = (ProducerKind.AGENT, "unattributed")


class AuditSink(ABC):
    """Where a decision record goes.

    A port because integrity against a hostile operator needs a key nobody in
    this repository holds and a store nobody has chosen. Saying that is more
    honest than a hash chain anyone with write access can rebuild
    (decision D-5).
    """

    @abstractmethod
    def write(self, record: DecisionRecord) -> None:
        """Records the decision. Never raises for an ordinary failure."""


def producer_for(rule_id: str, version: str) -> Producer:
    """What produced a finding with this rule id."""
    namespace = rule_id.split(".", 1)[0] if "." in rule_id else rule_id
    kind, name = PRODUCERS.get(namespace.upper(), UNKNOWN_PRODUCER)
    if (kind, name) == UNKNOWN_PRODUCER and rule_id:
        logger.warning(
            "Unattributed rule namespace; treating it as non-deterministic",
            extra={"fields": {"rule_id": rule_id}},
        )
    return Producer(kind=kind, name=name, version=version)


def provenance_of(finding: Finding, version: str) -> Provenance:
    """One finding, as a claim with an origin.

    Identifiers only: rule, location, severity, and the citations the claim
    rested on. Never the evidence line, the description or the remediation —
    all three are built from the file under review.
    """
    return Provenance(
        producer=producer_for(finding.rule_id, version),
        rule_id=finding.rule_id,
        location=finding.location,
        severity=finding.severity.value,
        evidence=(finding.cwe_id,) if finding.cwe_id else (),
    )


class DecisionRecorder:
    """Assembles one review's record and hands it to a sink."""

    def __init__(
        self,
        sink: AuditSink,
        identity: RunIdentity,
        clock: Callable[[], datetime] | None = None,
    ):
        self._sink = sink
        self._identity = identity
        self._clock = clock or (lambda: datetime.now(UTC))

    def record(
        self,
        outcome: ReviewOutcome,
        findings: Sequence[Finding],
        blocking_severity_reached: Callable[[Finding], bool],
        project: str = "",
        merge_request: str = "",
        trace_id: str = "",
        exit_code: int = 0,
        agent_costs: Sequence[AgentCost] = (),
    ) -> DecisionRecord | None:
        """Builds the record and writes it. Returns what was written.

        Never raises. A sink that cannot write is a warning, and a record that
        cannot be built is written as an incomplete one rather than as nothing
        — a missing file is indistinguishable from a review nobody ran
        (contract C-8, C-9).
        """
        version = self._identity.package_version
        claims = tuple(provenance_of(finding, version) for finding in findings)
        blocking = tuple(
            provenance_of(finding, version)
            for finding in findings
            if blocking_severity_reached(finding)
        )

        try:
            built = DecisionRecord(
                verdict=outcome.result.value,
                exit_code=exit_code,
                identity=self._identity,
                project=project,
                merge_request=merge_request,
                trace_id=trace_id,
                findings=claims,
                blocking=blocking if outcome.is_blocking else (),
                suppressions=_suppressions(outcome),
                agent_costs=tuple(agent_costs),
                files_considered=outcome.files_considered,
                recorded_at=self._clock().isoformat(),
                warnings=tuple(outcome.warnings),
            )
        except ValueError as refusal:
            # The record refused itself. That is the invariant doing its job,
            # and the honest response is a record saying so rather than none.
            logger.error("The decision could not be recorded as valid: %s", refusal)
            built = DecisionRecord(
                verdict="warn",
                exit_code=exit_code,
                identity=self._identity,
                project=project,
                merge_request=merge_request,
                trace_id=trace_id,
                completed=False,
                failure_reason=str(refusal),
                recorded_at=self._clock().isoformat(),
            )

        try:
            self._sink.write(built)
        except Exception as error:
            logger.warning("The decision record could not be written: %s", error)
        return built


def _suppressions(outcome: ReviewOutcome) -> tuple[SuppressionRecord, ...]:
    return tuple(
        SuppressionRecord(
            rule_id=item.directive.rule_id,
            location=f"{path}:{item.directive.line}",
            reason=item.directive.reason,
        )
        for path, item in outcome.suppressions
    )
