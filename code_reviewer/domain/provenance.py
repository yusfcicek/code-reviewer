"""What decided, under which versions, and on the strength of what.

Nineteen levels produced a system that decides whether a merge may proceed.
None of them could answer, six months later, *why*: a finding names its rule
and its location, and the merge-request comment carrying the rest is a thing
that can be edited, deleted, or lost with the project (capability C-18).

The important part of this module is one invariant.
[ADR 0004](../../docs/adr/0004-findings-drive-the-gate.md) says the gate
decides from findings and never from the model's prose. That has been true by
construction and by review for nineteen levels, and nothing checked it. Here a
:class:`DecisionRecord` whose verdict is blocking and whose blocking findings
name an agent is **refused at construction** — the design principle becomes a
control, and the difference is what an auditor is asking about (decision D-1).

Everything recorded is an identifier. Rule ids, paths, lines, severities,
counts, citations, span ids, versions. Never a diff, a file's contents, a
finding's evidence line or a model's prose: an audit file is read by more
people than a merge request, and a diff may contain a secret. Fourth level with
that rule, and the same two reasons.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum


def one_line(text: str) -> str:
    """The same sentence, on one line.

    The record holds identifiers and short reasons, which is the whole premise
    under this project's refusal to encrypt it (Level 24, restated by Level 30):
    confidentiality is the store's problem because the format cannot carry
    somebody's source. That was enforced by a test over a record the test built
    itself, so it never saw the values the code actually puts here —
    `failure_reason=str(refusal)` takes whatever a `ValueError` says, and an
    exception message with a newline is entirely ordinary (self-review 30,
    S-02).

    Flattened rather than refused. A record that raised on a multi-line reason
    would raise inside the `except` that exists to write a record when
    something has already gone wrong, and an accountability feature may not
    fail the thing it accounts for (Level 20, contract C-9).
    """
    return " ".join(text.split())


#: How much of a prompt digest is kept. Enough to distinguish two prompts by
#: eye in a report; short enough to read out.
FINGERPRINT_LENGTH = 12


class ProducerKind(Enum):
    """What kind of thing made a claim."""

    #: A deterministic rule. The same input produces the same finding.
    ANALYZER = "analyzer"
    #: A model. Useful, and never permitted to decide (D-1).
    AGENT = "agent"
    #: A tool the agent called — the sandbox refusing a read, for instance,
    #: which is a fact about the request rather than a model's opinion.
    TOOL = "tool"

    @property
    def is_deterministic(self) -> bool:
        """Whether a verdict may rest on it.

        A property rather than a convention somebody has to remember, because
        the whole level turns on getting this comparison right.
        """
        return self in (ProducerKind.ANALYZER, ProducerKind.TOOL)


@dataclass(frozen=True)
class Producer:
    """What made a claim, and which version of it."""

    kind: ProducerKind
    name: str
    version: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("'something produced this' is not provenance; a producer needs a name.")

    @property
    def is_deterministic(self) -> bool:
        return self.kind.is_deterministic

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.name}" + (f"@{self.version}" if self.version else "")


@dataclass(frozen=True)
class Provenance:
    """One claim, and where it came from."""

    producer: Producer
    rule_id: str
    location: str
    severity: str
    #: What the claim rested on: chunk citations, span ids, a tool's name.
    #: Identifiers, never the content they point at.
    evidence: tuple[str, ...] = ()

    @property
    def is_deterministic(self) -> bool:
        return self.producer.is_deterministic


@dataclass(frozen=True)
class SuppressionRecord:
    """A rule somebody turned off, where, and why.

    Part of the record because a governance record that omits what was silenced
    is a governance record that can be gamed by silencing things.
    """

    rule_id: str
    location: str
    reason: str = ""

    def __post_init__(self) -> None:
        # A person types this, and a YAML block scalar is multi-line by
        # construction.
        object.__setattr__(self, "reason", one_line(self.reason))

    @property
    def is_explained(self) -> bool:
        return bool(self.reason.strip())


@dataclass(frozen=True)
class SuggestionRecord:
    """An applicable edit the review offered, as identifiers.

    Rule, location, recipe. Never the replacement text: it is derived from the
    file under review, and five levels have kept that out of the artefacts
    (Level 22, decision D-5).
    """

    rule_id: str
    location: str
    recipe: str


@dataclass(frozen=True)
class AgentCost:
    """What one specialism cost, alongside the decision it contributed to."""

    agent: str
    runs: int = 0
    failures: int = 0
    tool_calls: int = 0
    tokens_allowed: int = 0
    duration_ms: int = 0


def fingerprint(*prompts: str) -> str:
    """A short digest of the prompts actually in use.

    Recording the text would put the system's instructions into a file read
    more widely than the repository, for no gain. Recording nothing would make
    "the prompt changed between these two reviews" unprovable. A digest answers
    the question that is actually asked (decision D-3).

    ``blake2b`` rather than the builtin hash, for the reason the embedding uses
    it: a value that changes per process is not an identity.
    """
    digest = hashlib.blake2b(digest_size=16)
    for prompt in prompts:
        digest.update(prompt.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:FINGERPRINT_LENGTH]


@dataclass(frozen=True)
class RunIdentity:
    """Which version of everything produced this review.

    Enough that two reviews which disagree can be attributed to the change
    between them, rather than to the weather (capability C-20).
    """

    package_version: str
    policy_version: str
    #: ``"none"`` rather than absent when no model was used: "this review had no
    #: model" is a fact about it, and a missing field reads as an oversight.
    model: str = "none"
    prompt_fingerprint: str = ""
    ruleset_version: str = ""
    #: What the analyzers last scored against the shipped dataset. A verdict is
    #: worth more when the thing that produced it has a measured accuracy.
    evaluation_baseline: str = ""

    def __post_init__(self) -> None:
        if not self.package_version.strip():
            raise ValueError("A run identity must name the package version that produced it.")
        if not self.model.strip():
            object.__setattr__(self, "model", "none")


@dataclass(frozen=True)
class DecisionRecord:
    """One review's decision, and everything accountable about it."""

    #: `pass`, `warn` or `fail`.
    verdict: str
    exit_code: int
    identity: RunIdentity
    project: str = ""
    merge_request: str = ""
    trace_id: str = ""
    #: Cited rather than embedded: two artefacts, one identifier between them
    #: (decision D-4).
    findings: tuple[Provenance, ...] = ()
    blocking: tuple[Provenance, ...] = ()
    suppressions: tuple[SuppressionRecord, ...] = ()
    agent_costs: tuple[AgentCost, ...] = ()
    #: Edits offered to a human. Offered, never applied — the record says what
    #: was proposed, and applying it stays somebody's deliberate click.
    suggestions: tuple[SuggestionRecord, ...] = ()
    files_considered: int = 0
    failure_reason: str = ""
    recorded_at: str = ""
    #: Set by a review that could not complete. A record still exists, saying
    #: so — a missing file is indistinguishable from a review nobody ran.
    completed: bool = True
    warnings: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_reason", one_line(self.failure_reason))
        object.__setattr__(self, "warnings", tuple(one_line(warning) for warning in self.warnings))

        if self.verdict != "fail":
            return

        if not self.blocking:
            raise ValueError(
                "A blocking verdict with no blocking findings is not a record: "
                "something decided, and this cannot say what."
            )

        opinions = [item for item in self.blocking if not item.is_deterministic]
        if opinions:
            # The invariant this level exists for. ADR 0004 says the gate
            # decides from findings and never from prose; here that stops being
            # a design rule and becomes something a record cannot violate.
            named = ", ".join(f"{item.rule_id} ({item.producer})" for item in opinions)
            raise ValueError(
                "A blocking verdict may not rest on a model's opinion. "
                f"These blocking findings name a non-deterministic producer: {named}. "
                "See ADR 0004."
            )

    @property
    def is_blocking(self) -> bool:
        return self.verdict == "fail"

    @property
    def deciders(self) -> tuple[str, ...]:
        """The producers whose findings blocked, named."""
        return tuple(sorted({str(item.producer) for item in self.blocking}))

    @property
    def unexplained_suppressions(self) -> tuple[SuppressionRecord, ...]:
        return tuple(item for item in self.suppressions if not item.is_explained)

    def summary(self) -> str:
        """One line: what was decided, and by what."""
        if not self.completed:
            return f"not completed: {self.failure_reason}"
        if not self.is_blocking:
            return f"{self.verdict} — nothing blocked the merge"
        return f"blocked by {', '.join(self.deciders)}"


def deterministic_only(claims: Sequence[Provenance]) -> tuple[Provenance, ...]:
    """The claims a verdict is allowed to rest on."""
    return tuple(item for item in claims if item.is_deterministic)
