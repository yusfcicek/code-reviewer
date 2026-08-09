"""Who reviews a file, for how much, in what order, and what they may hand on.

There was one agent, with one prompt asking it to do six unrelated jobs at
once: classify the change, scan for vulnerabilities, judge the architecture,
find performance problems, trace dependencies and write a report. Every level
that added a concern lengthened that prompt, and nothing could say which of its
numbered steps a given response had actually followed (capability C-09).

The failure mode of a multi-agent system is that nobody can say what it will
do. So everything here is a pure function over enums and lists — routing,
budget arithmetic, composition order and the handoff rule — and every one of
those questions is answered by reading a page rather than by running a model.

Two properties are load-bearing.

**The plan is derived from evidence, not from a model.** By the time an
orchestrator is called the analyzers have already run, and what they found is
the best available statement of what the file needs. Asking a model which
specialists to invoke would spend a call to make a decision two conditionals
make correctly, and would make the plan unreproducible (decision D-2).

**Handoff depth is structural.** A specialist may ask for one other, once. The
orchestrator offers the protocol only on the first round, so the bound is not a
counter anybody can get wrong — and the total number of agent invocations for
one file is bounded by twice the number of specialisms, whatever a model says
(decision D-3).
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from .finding import Finding, FindingCategory
from .policy import DEFAULT_MANIFEST_PATTERNS


class Specialism(Enum):
    """What one reviewer is for."""

    #: The generalist. Owns the summary, because some agent has to write the
    #: sentence a reader sees first and this is the one with the whole file in
    #: view (decision D-6).
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DEPENDENCY = "dependency"


#: The order sections appear in, whatever order the agents ran or finished in.
#: Two runs over the same inputs produce the same document (contract C-5).
COMPOSITION_ORDER: tuple[Specialism, ...] = (
    Specialism.ARCHITECTURE,
    Specialism.SECURITY,
    Specialism.PERFORMANCE,
    Specialism.DEPENDENCY,
)

#: Shares of the file's budget. Security is the largest because "spend more on
#: security than on style" has to be something the system holds rather than
#: something it hopes (decision D-5).
SPECIALIST_WEIGHTS: dict[Specialism, int] = {
    Specialism.SECURITY: 4,
    Specialism.ARCHITECTURE: 3,
    Specialism.PERFORMANCE: 2,
    Specialism.DEPENDENCY: 2,
}

#: Every specialist can read a file, list a directory, find one by name and
#: search the index. Those are how you look at code at all.
_SHARED_TOOLS = ("read_file", "list_files", "find_file", "search_related_code")

#: What each specialism may call. Data rather than prose in a prompt: an agent
#: told in English not to use a tool is an agent that sometimes uses it.
SPECIALIST_TOOLS: dict[Specialism, tuple[str, ...]] = {
    Specialism.ARCHITECTURE: (
        *_SHARED_TOOLS,
        "run_semantic_analysis",
        "check_code_quality",
        "read_symbol_definition",
    ),
    Specialism.SECURITY: (*_SHARED_TOOLS, "run_sast_scan", "grep_search"),
    Specialism.PERFORMANCE: (*_SHARED_TOOLS, "analyze_performance", "read_symbol_definition"),
    Specialism.DEPENDENCY: (
        *_SHARED_TOOLS,
        "get_file_imports",
        "find_references",
        "find_ripple_effects",
        "find_affected_by_change",
    ),
}

#: Which finding category calls for which specialist. `QUALITY` is absent on
#: purpose: it is the generalist's own subject, and every file gets that one.
_CATEGORY_ROUTING: dict[FindingCategory, Specialism] = {
    FindingCategory.SECURITY: Specialism.SECURITY,
    FindingCategory.PERFORMANCE: Specialism.PERFORMANCE,
    FindingCategory.DEPENDENCY: Specialism.DEPENDENCY,
}

_MANIFEST_MATCHERS = tuple(re.compile(pattern) for pattern in DEFAULT_MANIFEST_PATTERNS)


def is_manifest_path(file_path: str) -> bool:
    """True when the path names a dependency manifest or a CI definition.

    The patterns are the policy's, so there is one list; the matching is here
    because two callers need it and neither owns the other.
    """
    return any(matcher.search(file_path) for matcher in _MANIFEST_MATCHERS)


def plan_assignments(findings: Sequence[Finding], is_manifest: bool) -> tuple[Specialism, ...]:
    """Which specialists this file warrants, in composition order.

    The generalist always runs: a file worth reviewing is worth an
    architectural read even when no rule fired on it. Everything else is
    earned by evidence — a category that was reported, or a path that is a
    manifest, which is itself the evidence a lock file offers.
    """
    assigned = {Specialism.ARCHITECTURE}
    assigned.update(
        _CATEGORY_ROUTING[finding.category] for finding in findings if finding.category in _CATEGORY_ROUTING
    )
    if is_manifest:
        assigned.add(Specialism.DEPENDENCY)

    return tuple(specialism for specialism in COMPOSITION_ORDER if specialism in assigned)


def split_budget(total: int, specialisms: Sequence[Specialism]) -> dict[Specialism, int]:
    """Divides ``total`` between ``specialisms`` by weight.

    Every assigned specialist gets at least one, the shares sum exactly to the
    total, and the result does not depend on the order the specialisms arrived
    in. The remainder goes to the heaviest rather than being dropped: a split
    that loses tokens is a split somebody debugs on a Friday.
    """
    if not specialisms:
        raise ValueError("A budget cannot be split between nobody.")

    unique = [item for item in COMPOSITION_ORDER if item in set(specialisms)]
    if total < len(unique):
        raise ValueError(
            f"A budget of {total} cannot give {len(unique)} specialist(s) anything to work with."
        )

    # One each first, then the rest apportioned by weight. Starting from one
    # is what makes "nobody gets zero" true by construction rather than by a
    # clamp that then has to be rebalanced.
    remaining = total - len(unique)
    weights = {item: SPECIALIST_WEIGHTS[item] for item in unique}
    weight_total = sum(weights.values())

    shares = dict.fromkeys(unique, 1)
    quotas = {item: remaining * weights[item] / weight_total for item in unique}
    for item in unique:
        shares[item] += int(quotas[item])

    # Largest remainder, tie-broken by weight and then by composition order, so
    # the same inputs always produce the same split.
    leftover = total - sum(shares.values())
    ranked = sorted(
        unique,
        key=lambda item: (-(quotas[item] % 1), -weights[item], COMPOSITION_ORDER.index(item)),
    )
    for index in range(leftover):
        shares[ranked[index % len(ranked)]] += 1

    return shares


# -- what an agent reports ---------------------------------------------------


@dataclass(frozen=True)
class Handoff:
    """One specialist asking for another.

    ``target`` is text rather than a :class:`Specialism` because it comes from
    a model, and "the model named something that does not exist" is a case the
    protocol has to answer rather than a case that cannot arise.
    """

    target: str
    reason: str = ""


@dataclass(frozen=True)
class Assignment:
    """One specialist's instructions for one file."""

    specialism: Specialism
    token_budget: int
    #: Set when this agent is running because another asked for it. Carried so
    #: the specialist can be told *why* it was called, which is the difference
    #: between a handoff and a second opinion.
    handed_from: Specialism | None = None
    handoff_reason: str = ""

    @property
    def tools(self) -> tuple[str, ...]:
        return SPECIALIST_TOOLS[self.specialism]


@dataclass(frozen=True)
class AgentReport:
    """What one specialist produced, and what it cost."""

    specialism: Specialism
    prose: str = ""
    succeeded: bool = True
    failure_reason: str = ""
    tokens_allowed: int = 0
    tool_calls: int = 0
    duration_ms: int = 0
    handoffs: tuple[Handoff, ...] = ()

    def __post_init__(self) -> None:
        if not self.succeeded and not self.failure_reason:
            # A section that says "this agent failed" and nothing else is a
            # section nobody can act on.
            raise ValueError(f"A failed {self.specialism.value} report must say why.")

    @classmethod
    def failed(cls, specialism: Specialism, reason: str, **details) -> "AgentReport":
        return cls(specialism=specialism, succeeded=False, failure_reason=reason, **details)


@dataclass(frozen=True)
class HandoffDecision:
    """What the orchestrator will honour, and what it refused."""

    accepted: tuple[Specialism, ...] = ()
    #: `(target, why)` per refusal. Recorded rather than dropped, in the way a
    #: refused file read is: a request nobody can see was never answered.
    refused: tuple[tuple[str, str], ...] = ()


def accept_handoffs(requests: Iterable[Handoff], already_run: set[Specialism], depth: int) -> HandoffDecision:
    """Decides which handoff requests the orchestrator will honour.

    Everything is refused at depth 1 — the protocol is offered once, which is
    what makes it terminating by construction rather than by a counter
    (decision D-3).
    """
    accepted: set[Specialism] = set()
    refused: list[tuple[str, str]] = []

    for request in requests:
        target = request.target.strip().lower()
        if depth > 0:
            refused.append((request.target, "a handoff is offered once, and this agent was handed to"))
            continue

        try:
            specialism = Specialism(target)
        except ValueError:
            refused.append((request.target, f"'{request.target}' is not a specialism"))
            continue

        if specialism in already_run:
            refused.append((request.target, f"{specialism.value} has already run for this file"))
            continue

        accepted.add(specialism)

    ordered = tuple(item for item in COMPOSITION_ORDER if item in accepted)
    return HandoffDecision(accepted=ordered, refused=tuple(refused))


# -- composition -------------------------------------------------------------

_HEADINGS = {
    Specialism.ARCHITECTURE: "🏛️ Architecture",
    Specialism.SECURITY: "🔒 Security",
    Specialism.PERFORMANCE: "⚡ Performance",
    Specialism.DEPENDENCY: "🔗 Dependencies",
}


def compose(reports: Sequence[AgentReport]) -> str:
    """One document from several agents' work, in a fixed order.

    Every section is attributed. An unattributed paragraph is exactly what
    multi-agent review is supposed to stop producing, and a failure is stated
    rather than omitted — a review with three sections and one stated failure
    is worth much more than no review (contract C-4).
    """
    if not reports:
        # An empty review reads as an approval. It is not one.
        return "_No agent produced a review for this file._"

    by_specialism = {report.specialism: report for report in reports}
    sections: list[str] = []

    for specialism in COMPOSITION_ORDER:
        report = by_specialism.get(specialism)
        if report is None:
            continue
        sections.append(f"### {_HEADINGS[specialism]}\n")
        sections.append(_body(report))

    return "\n".join(sections)


def _body(report: AgentReport) -> str:
    if not report.succeeded:
        return (
            f"> This agent did not complete: {report.failure_reason}\n"
            f"> Treat this aspect as unreviewed rather than as clear.\n"
        )
    if not report.prose.strip():
        return "_Nothing to report._\n"
    return f"{report.prose.strip()}\n"


@dataclass(frozen=True)
class OrchestrationOutcome:
    """Everything one file's committee did, for the report and the metrics."""

    reports: tuple[AgentReport, ...] = ()
    refused_handoffs: tuple[tuple[str, str], ...] = ()
    skipped: tuple[tuple[Specialism, str], ...] = field(default=())

    @property
    def tool_calls(self) -> int:
        return sum(report.tool_calls for report in self.reports)

    @property
    def failures(self) -> tuple[AgentReport, ...]:
        return tuple(report for report in self.reports if not report.succeeded)
