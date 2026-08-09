"""One agent with one subject.

A :class:`~code_reviewer.application.ports.Specialist` built out of the review
agent this project already owns: the same tool loop, the same trust boundary,
the same redaction on the way out. What differs is the three things a
specialism *is* — its instructions, its tools and its budget.

The tools are a narrowed catalogue rather than a sentence in the prompt. An
agent told in English not to use a tool is an agent that sometimes uses it;
one that was never offered the tool cannot.

The budget becomes a cap on tool-call iterations. That is a coarse instrument —
a loop iteration is not a token — but it is an enforceable one, and an
enforceable ceiling is worth more than an exact number the model is asked to
respect.

The trust boundary is inherited whole. It is not something one of four agents
may forget: every specialism's prompt opens with it, and there is a test that
each one does.
"""

import logging
import re
import time
from collections.abc import Sequence
from typing import Any

from code_reviewer.application.ports import (
    LLMProvider,
    MemoryStrategy,
    ReviewBrief,
    Specialist,
)
from code_reviewer.domain.orchestration import (
    SPECIALIST_TOOLS,
    AgentReport,
    Assignment,
    Handoff,
    Specialism,
)
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from code_reviewer.infrastructure.tools import get_tools

logger = logging.getLogger(__name__)

#: Tokens a tool-call iteration is assumed to cost. Used only to turn a budget
#: into an iteration cap, which is the enforceable half of "this agent gets
#: this much".
TOKENS_PER_ITERATION = 1_500

#: However small the budget, an agent gets enough iterations to call one tool
#: and then say something about what it found.
MIN_ITERATIONS = 2

#: What a specialist writes when it wants another one. Parsed out of the prose
#: rather than requested as JSON: the response is markdown for a human, and a
#: line the human can also read is a protocol that degrades into documentation.
_HANDOFF = re.compile(r"^\s*HANDOFF\s*:\s*([A-Za-z_-]+)\s*(?:[-—:]\s*(.*))?$", re.MULTILINE)

_BRIEFS: dict[Specialism, str] = {
    Specialism.ARCHITECTURE: (
        "You are the ARCHITECTURE reviewer, and the generalist of this review. "
        "Judge the shape of the change: layering, coupling, naming, error handling, "
        "testability, and whether the change is complete. You also write the summary "
        "a reader sees first."
    ),
    Specialism.SECURITY: (
        "You are the SECURITY reviewer. Judge only security: injection, authentication "
        "and authorisation, secrets, cryptography, unsafe deserialisation, and input that "
        "reaches a dangerous sink. Say nothing about style or performance — other agents "
        "are reviewing those, and a paragraph from you about naming costs the budget that "
        "was given to you for this."
    ),
    Specialism.PERFORMANCE: (
        "You are the PERFORMANCE reviewer. Judge only cost: algorithmic complexity, "
        "queries inside loops, unbounded memory, unclosed resources, and work done per "
        "request that could be done once. Say nothing about security or style."
    ),
    Specialism.DEPENDENCY: (
        "You are the DEPENDENCY reviewer. Judge what this change pulls in and what it "
        "breaks: added, removed or upgraded packages, transitive changes recorded in a "
        "lock file, and code elsewhere in the repository that this change reaches. Say "
        "nothing about style."
    ),
}

_HANDOFF_INSTRUCTION = (
    "\n\nIf your subject leads somewhere outside it, you may hand off ONCE by writing a "
    "line of the form `HANDOFF: <specialism> - <reason>`, where <specialism> is one of "
    "architecture, security, performance, dependency. Do not hand off to yourself, and "
    "do not hand off for work you could do within your own budget. A handoff you were "
    "handed to is refused."
)


def tools_for(specialism: Specialism, available: Sequence[Any] | None = None) -> list[Any]:
    """The catalogue this specialism is offered, and nothing else."""
    catalogue = list(available) if available is not None else get_tools()
    permitted = set(SPECIALIST_TOOLS[specialism])
    return [tool for tool in catalogue if tool.name in permitted]


def system_prompt_for(specialism: Specialism) -> str:
    """The specialism's instructions, on top of the shared trust boundary."""
    return (
        f"{ReviewAgent.SYSTEM_TEMPLATE}\n\n"
        "═══════════════════════════════════════════════════════════════════════════════\n"
        "🎯 YOUR SUBJECT\n"
        "═══════════════════════════════════════════════════════════════════════════════\n"
        f"{_BRIEFS[specialism]}"
        f"{_HANDOFF_INSTRUCTION}"
    )


def parse_handoffs(text: str) -> tuple[tuple[Handoff, ...], str]:
    """Pulls handoff requests out of a response, and returns the rest.

    The requests are stripped from the prose: a reader of the report wants the
    review, and the orchestrator's footer already states which handoffs were
    honoured and which were refused.
    """
    requests = tuple(
        Handoff(target=match.group(1), reason=(match.group(2) or "").strip())
        for match in _HANDOFF.finditer(text)
    )
    return requests, _HANDOFF.sub("", text).strip()


class SpecialistAgent(Specialist):
    """A review agent narrowed to one subject.

    Args:
        specialism: What this agent is for.
        llm_provider: The chat model factory.
        memory_strategy: Carried between files, as for any agent.
    """

    def __init__(
        self,
        specialism: Specialism,
        llm_provider: LLMProvider,
        memory_strategy: MemoryStrategy,
        **agent_options: Any,
    ):
        self.specialism = specialism
        self._agent = ReviewAgent(
            llm_provider,
            memory_strategy,
            tools=tools_for(specialism),
            system_template=system_prompt_for(specialism),
            **agent_options,
        )

    def review(self, brief: ReviewBrief, assignment: Assignment) -> AgentReport:
        """Reviews within this specialism, and reports its own failure.

        Returns a failed report rather than raising. The orchestrator catches
        exceptions too, but an adapter that reports its own failure can say
        something more useful about it than a type name.
        """
        self._agent.loop.max_iterations = _iterations_for(assignment.token_budget)

        started = time.monotonic()
        try:
            text = self._agent.review_diff(_with_assignment(brief, assignment))
        except Exception as error:
            logger.error(
                "Specialist agent failed",
                extra={
                    "fields": {
                        "specialism": self.specialism.value,
                        "path": brief.file_path,
                        "error": str(error),
                    }
                },
                exc_info=True,
            )
            return AgentReport.failed(
                self.specialism,
                f"{type(error).__name__}: {error}",
                tokens_allowed=assignment.token_budget,
                duration_ms=_elapsed_ms(started),
            )

        handoffs, prose = parse_handoffs(text)
        # A handed-to agent's requests are refused by the orchestrator anyway;
        # dropping them here keeps the report free of a request that was never
        # going to be honoured.
        if assignment.handed_from is not None:
            handoffs = ()

        return AgentReport(
            specialism=self.specialism,
            prose=prose,
            tokens_allowed=assignment.token_budget,
            tool_calls=self._agent.loop.last_tool_call_count,
            duration_ms=_elapsed_ms(started),
            handoffs=handoffs,
        )


def _with_assignment(brief: ReviewBrief, assignment: Assignment) -> ReviewBrief:
    """The brief, with the reason this agent was called written into the diff.

    A handoff that does not say why it happened is a second opinion, and a
    second opinion nobody asked a question for is a paragraph.
    """
    if assignment.handed_from is None:
        return brief

    note = (
        f"\n\n[HANDOFF] The {assignment.handed_from.value} reviewer asked for you: "
        f"{assignment.handoff_reason or 'no reason given'}\n"
    )
    return ReviewBrief(
        file_path=brief.file_path,
        diff=brief.diff + note,
        full_content=brief.full_content,
        other_files=brief.other_files,
        related=brief.related,
        recollections=brief.recollections,
        findings=brief.findings,
    )


def _iterations_for(token_budget: int) -> int:
    return max(MIN_ITERATIONS, token_budget // TOKENS_PER_ITERATION)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
