"""One reviewer made of several, and the rules for running them.

The orchestrator implements :class:`~code_reviewer.application.ports.Reviewer`,
so the workflow never learns that there is more than one agent. Swapping a
single reviewer for a committee is a change to the composition root and nothing
else (decision D-1).

Everything it decides — who runs, for how much, in what order, what may be
handed on — is a pure function in
:mod:`code_reviewer.domain.orchestration`. What is left here is the part that
can only be written once: the loop, the failure handling, and the accounting.

Two rules do the load-bearing work.

**One specialist failing costs one section.** An exception, a timeout, an
exhausted loop: recorded against that specialist, stated in the composed
report, and the rest still run. A review with three sections and one stated
failure is worth far more than no review (contract C-4).

**Handoffs are offered once.** The second round is run with ``depth=1``, at
which the domain refuses every request. The bound is structural rather than a
counter, so the number of agent invocations for one file cannot exceed twice
the number of specialisms whatever a model asks for (decision D-3).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from code_reviewer.domain.orchestration import (
    AgentReport,
    Assignment,
    OrchestrationOutcome,
    Specialism,
    accept_handoffs,
    compose,
    is_manifest_path,
    plan_assignments,
    split_budget,
)

from .ports import ReviewBrief, Reviewer, Specialist

logger = logging.getLogger(__name__)

#: Tokens one file's committee may spend in total.
DEFAULT_FILE_BUDGET = 12_000

#: The share held back for handoffs, as a divisor. A quarter: enough for one
#: specialist to do real work, small enough that the first round is not
#: crippled by a reserve nobody uses.
#:
#: Unspent when no handoff happens, which is correct — a budget is a ceiling,
#: not a quota, and a round that returns tokens is a round that did its job.
HANDOFF_RESERVE_DIVISOR = 4


@dataclass(frozen=True)
class AgentTotals:
    """One specialist's whole run, for the metrics export."""

    runs: int = 0
    failures: int = 0
    tool_calls: int = 0
    tokens_allowed: int = 0
    duration_ms: int = 0


class ReviewOrchestrator(Reviewer):
    """A committee of specialists, presented to the workflow as one reviewer.

    Args:
        specialists: The registered agents. A specialism with nobody
            registered is skipped with a stated reason rather than raising —
            a composition root that forgot to wire one should produce a
            legible report, not a crash.
        total_budget: Tokens the whole committee may spend on one file.
    """

    def __init__(
        self,
        specialists: Mapping[Specialism, Specialist],
        total_budget: int = DEFAULT_FILE_BUDGET,
    ):
        self._specialists = dict(specialists)
        self._total_budget = total_budget
        self._last_outcome = OrchestrationOutcome()
        #: Across every file of the run, for the metrics export. Per-file
        #: accounting is `last_outcome`; a pipeline wants the totals.
        self._totals: dict[Specialism, AgentTotals] = {}

    @property
    def agent_totals(self) -> dict[Specialism, "AgentTotals"]:
        """What each specialist did across the whole run."""
        return dict(self._totals)

    @property
    def last_outcome(self) -> OrchestrationOutcome:
        """What the most recent file's committee did. Read by the metrics."""
        return self._last_outcome

    def review_diff(self, brief: ReviewBrief) -> str:
        plan = plan_assignments(brief.findings, is_manifest_path(brief.file_path))
        reserve = max(len(Specialism), self._total_budget // HANDOFF_RESERVE_DIVISOR)
        budgets = split_budget(max(len(plan), self._total_budget - reserve), plan)

        reports: list[AgentReport] = []
        skipped: list[tuple[Specialism, str]] = []
        ran: set[Specialism] = set()

        for specialism in plan:
            assignment = Assignment(specialism=specialism, token_budget=budgets[specialism])
            report = self._run(brief, assignment, skipped)
            if report is not None:
                reports.append(report)
                ran.add(specialism)

        decision = accept_handoffs(
            [handoff for report in reports for handoff in report.handoffs], ran, depth=0
        )
        if decision.accepted:
            handoff_budgets = split_budget(max(len(decision.accepted), reserve), decision.accepted)
            for specialism in decision.accepted:
                source = _requester(reports, specialism)
                assignment = Assignment(
                    specialism=specialism,
                    token_budget=handoff_budgets[specialism],
                    handed_from=source[0],
                    handoff_reason=source[1],
                )
                report = self._run(brief, assignment, skipped)
                if report is not None:
                    reports.append(report)

        self._last_outcome = OrchestrationOutcome(
            reports=tuple(reports),
            refused_handoffs=decision.refused,
            skipped=tuple(skipped),
        )
        self._accumulate(reports)
        return compose(reports) + _footer(self._last_outcome, budgets)

    def _accumulate(self, reports: list[AgentReport]) -> None:
        for report in reports:
            totals = self._totals.setdefault(report.specialism, AgentTotals())
            self._totals[report.specialism] = AgentTotals(
                runs=totals.runs + 1,
                failures=totals.failures + (0 if report.succeeded else 1),
                tool_calls=totals.tool_calls + report.tool_calls,
                tokens_allowed=totals.tokens_allowed + report.tokens_allowed,
                duration_ms=totals.duration_ms + report.duration_ms,
            )

    # -- internals ----------------------------------------------------------

    def _run(
        self,
        brief: ReviewBrief,
        assignment: Assignment,
        skipped: list[tuple[Specialism, str]],
    ) -> AgentReport | None:
        """Runs one specialist, turning any failure into a stated report."""
        specialist = self._specialists.get(assignment.specialism)
        if specialist is None:
            reason = "no specialist is registered for this subject"
            logger.warning("Skipping %s: %s", assignment.specialism.value, reason)
            skipped.append((assignment.specialism, reason))
            return None

        try:
            return specialist.review(brief, assignment)
        except Exception as error:
            logger.error(
                "Specialist failed",
                extra={
                    "fields": {
                        "specialism": assignment.specialism.value,
                        "path": brief.file_path,
                        "error": str(error),
                    }
                },
                exc_info=True,
            )
            return AgentReport.failed(
                assignment.specialism,
                f"{type(error).__name__}: {error}",
                tokens_allowed=assignment.token_budget,
            )


def _requester(reports: list[AgentReport], target: Specialism) -> tuple[Specialism | None, str]:
    """Which agent asked for ``target``, and why. The first request wins."""
    for report in reports:
        for handoff in report.handoffs:
            if handoff.target.strip().lower() == target.value:
                return (report.specialism, handoff.reason)
    return (None, "")


def _footer(outcome: OrchestrationOutcome, budgets: Mapping[Specialism, int]) -> str:
    """What the committee cost, and what it refused.

    "Why did this review stop early" is a question a budget has to be able to
    answer, and "which agent said this" is the question multi-agent review
    exists to make answerable (contracts C-3, C-7).
    """
    lines = [
        "\n<details><summary>Review agents</summary>\n",
        "| agent | budget | tool calls | outcome |",
        "|---|---:|---:|---|",
    ]

    for report in outcome.reports:
        state = "ok" if report.succeeded else f"failed — {report.failure_reason}"
        allowed = report.tokens_allowed or budgets.get(report.specialism, 0)
        lines.append(f"| {report.specialism.value} | {allowed} | {report.tool_calls} | {state} |")

    for specialism, reason in outcome.skipped:
        lines.append(f"| {specialism.value} | — | — | skipped — {reason} |")

    for target, reason in outcome.refused_handoffs:
        lines.append(f"| {target} | — | — | handoff refused — {reason} |")

    lines.append("\n</details>\n")
    return "\n".join(lines)
