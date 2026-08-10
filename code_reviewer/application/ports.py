"""Ports the review workflow depends on.

Each port is declared by the layer that *needs* it, not by the layer that
implements it, so the dependency arrow points inwards. Adapters live in
``code_reviewer.infrastructure``.

Every signature here uses builtins or domain types. ``MemoryStrategy`` used to
expose ``get_memory_object() -> "the underlying LangChain memory object"``,
which handed callers a framework type through the abstraction meant to hide it
(finding F-26).
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from code_reviewer.domain.drift import DriftCandidate, DriftVerdict
from code_reviewer.domain.evaluation import EvaluationCase
from code_reviewer.domain.finding import Finding
from code_reviewer.domain.orchestration import AgentReport, Assignment
from code_reviewer.domain.recollection import Recollection
from code_reviewer.domain.retrieval import UNSCORED, CodeChunk, ScoredChunk, Vector
from code_reviewer.domain.suppression import SuppressionResult


@dataclass(frozen=True)
class FileChange:
    """One file's change within a merge request.

    A value object, deliberately free of the forge's own representation: the
    GitLab adapter converts its payload into this, so nothing above the
    infrastructure layer learns GitLab's field names.
    """

    path: str
    diff: str
    is_deleted: bool = False
    is_new: bool = False
    previous_path: str = ""

    @property
    def changed_line_count(self) -> int:
        return len(self.diff.splitlines())


@dataclass(frozen=True)
class MergeRequestRef:
    """Where a review is happening, in forge-neutral terms."""

    project_id: str
    merge_request_id: str
    project_name: str = ""
    head_sha: str = ""
    #: The commits the platform diffs between. Needed to anchor a note on a
    #: line; empty when the forge did not report them, which costs suggestions
    #: and nothing else.
    base_sha: str = ""
    start_sha: str = ""


@dataclass(frozen=True)
class DiffPosition:
    """Where a note attaches to a line of the diff.

    A suggestion is only applicable in a note anchored on the change it edits,
    which needs the three commits the platform compares. A position missing one
    of them is a note posted at the top of the file, or rejected, depending on
    the platform's mood — so it is refused here (Level 22).
    """

    path: str
    line: int
    base_sha: str
    start_sha: str
    head_sha: str

    def __post_init__(self) -> None:
        if not all((self.base_sha, self.start_sha, self.head_sha)):
            raise ValueError(
                "A diff position needs the base, start and head commits; without them a note "
                "cannot be anchored on the line it is about."
            )
        if self.line < 1:
            raise ValueError("A diff position names a line, and files start at line 1.")


class CodeForge(ABC):
    """The system hosting the merge request under review.

    GitLab is one implementation; nothing in this layer or the domain names it.
    """

    @abstractmethod
    def fetch_merge_request(self, project_id: int, merge_request_iid: int) -> MergeRequestRef:
        """Identifies the merge request and the commit under review."""

    @abstractmethod
    def fetch_changes(self, reference: MergeRequestRef) -> list[FileChange]:
        """Returns every file the merge request touches."""

    @abstractmethod
    def fetch_file(self, reference: MergeRequestRef, path: str) -> str | None:
        """Returns a file's full contents at the reviewed commit.

        ``None`` when the file cannot be read — it may be binary, or the ref may
        have moved. That is not a reason to abandon the review.
        """

    def publish_suggestion(self, reference: MergeRequestRef, position: DiffPosition, body: str) -> None:
        """Posts an applicable suggestion against one line of the diff.

        Not abstract: a forge that cannot anchor a note on a line is still a
        forge, and the review it publishes is unchanged. The default says so
        rather than doing nothing quietly — a feature that silently does not
        exist is the hardest kind to notice (Level 22, contract C-6).
        """
        logging.getLogger(__name__).warning(
            "This forge cannot post suggestions; the finding keeps its written advice",
            extra={"fields": {"forge": type(self).__name__, "path": position.path}},
        )

    @abstractmethod
    def publish_comment(self, reference: MergeRequestRef, body: str) -> None:
        """Posts the review back onto the merge request."""


class LLMProvider(ABC):
    """Factory for the chat model the review agent drives."""

    @abstractmethod
    def get_chat_model(self) -> Any:
        """Returns a chat model object the agent's adapter understands."""


class MemoryStrategy(ABC):
    """Carries findings from one reviewed file to the next."""

    @abstractmethod
    def load_context(self) -> str:
        """Returns the context string to inject into the next prompt."""

    @abstractmethod
    def save_context(self, input_text: str, output_text: str) -> None:
        """Records an interaction and compacts memory if it is under pressure."""

    @abstractmethod
    def log_insight(self, insight: str) -> None:
        """Stores one finding, tagged with its category."""


class StaticAnalysis(ABC):
    """Deterministic analysis of one file.

    Declared here so the workflow can guarantee that every reviewed file is
    analysed, whether or not the model chooses to call a tool (finding F-32).
    """

    @abstractmethod
    def analyze(self, file_path: str, content: str, diff: str = "") -> SuppressionResult:
        """What was found, and what the file asked to be ignored.

        Returns both halves rather than the findings alone. A rule silenced by
        a ``review-ignore`` directive and a rule that never fired look
        identical from the outside otherwise, which is the state suppression
        exists to avoid creating (finding G-07).

        Findings come back most severe first.
        """


@dataclass(frozen=True)
class ReviewBrief:
    """Everything a reviewer is given about one file.

    A value object rather than seven parameters. `review_diff` had grown one
    argument per level — the diff, the file, the siblings, the retrieved code,
    the project's memory, and now the findings the analyzers produced — and a
    seven-parameter signature is both unreadable and past the threshold this
    project's own quality analyzer enforces.

    It also makes the port stable: the next thing a reviewer needs is a field
    here, not a signature change rippling through every implementation and
    every fake.
    """

    file_path: str
    diff: str
    full_content: str | None = None
    #: Everything else the merge request touched, for cross-file context.
    other_files: tuple[str, ...] = ()
    #: Code retrieved from elsewhere in the checkout (Level 13).
    related: tuple[CodeChunk, ...] = ()
    #: What previous reviews of this project recorded about this file (Level 14).
    recollections: tuple[Recollection, ...] = ()
    #: What the analyzers already found. The evidence an orchestrator routes on
    #: (Level 15, decision D-2), and never the source of a verdict — that is
    #: the gate's, from these same findings.
    findings: tuple[Finding, ...] = ()


class Reviewer(ABC):
    """Produces a written review for a single file's diff."""

    @abstractmethod
    def review_diff(self, brief: ReviewBrief) -> str:
        """Returns the review report for one file, as markdown."""


class Specialist(ABC):
    """One agent with one subject.

    Declared separately from :class:`Reviewer` because the two answer different
    questions: a reviewer is asked "review this file", a specialist is asked
    "review this file *as a security problem*, with this budget". The
    orchestrator is a `Reviewer` made of `Specialist`s, which is what keeps the
    workflow unaware that there is more than one agent (Level 15, decision D-1).
    """

    @abstractmethod
    def review(self, brief: ReviewBrief, assignment: Assignment) -> AgentReport:
        """Reviews within its specialism and budget.

        Returns a report rather than raising, including for its own failures:
        one specialist falling over must cost one section and not the file
        (contract C-4). An exception that escapes is caught by the
        orchestrator, but an adapter that reports its own failure can say
        something useful about it.
        """


class EmbeddingModel(ABC):
    """Turns text into a vector.

    Declared here rather than assumed, because this is the one piece of the
    retrieval pipeline everyone eventually replaces: the shipped adapter is a
    deterministic hashed-token embedding that needs no weights and no network,
    and a hosted model is a sibling module behind this signature.
    """

    @abstractmethod
    def embed(self, texts: list[str]) -> list[Vector]:
        """One vector per input, in order, all of the same dimension."""


class LexicalIndex(ABC):
    """Keyword search over chunks.

    An exact identifier is the strongest signal code search has, and an
    embedding blurs it. This is the half of the hybrid that does not.
    """

    @abstractmethod
    def add(self, chunks: list[CodeChunk]) -> None:
        """Indexes chunks. Calling it twice adds; it does not replace."""

    @abstractmethod
    def search(self, query: str, limit: int) -> list[ScoredChunk]:
        """Best matches, most relevant first."""


class VectorIndex(ABC):
    """Nearest-neighbour search over embedded chunks."""

    @abstractmethod
    def add(self, entries: list[tuple[CodeChunk, Vector]]) -> None:
        """Indexes chunks against their vectors."""

    @abstractmethod
    def search(self, vector: Vector, limit: int) -> list[ScoredChunk]:
        """Nearest chunks, closest first."""

    @abstractmethod
    def vector_of(self, chunk: CodeChunk) -> Vector | None:
        """The stored vector, or ``None``.

        Needed because diversification compares candidates with each other,
        not only with the query — and re-embedding a chunk to find out what it
        already embedded to would be work the index has already done.
        """


class CodeRetriever(ABC):
    """Related code from somewhere other than the diff.

    The port the review workflow depends on. Everything behind it — chunking,
    two indexes, fusion, diversification — is one adapter's business, and the
    workflow's whole knowledge of retrieval is this one method.
    """

    def scored(self, query: str, limit: int = 5, exclude_path: str = "") -> list[ScoredChunk]:
        """The same results, with the ranking's score attached.

        The default delegates to :meth:`related` and marks every result
        **unscored**, because a retriever with no notion of a score is a real
        thing — a keyword-only adapter, a stub in a test — and a caller applying
        a relevance floor has to be able to tell. Level 23 described a floor
        this port could not express, dropped it, and then lost a whole tier to
        the silence (Level 27).
        """
        return [
            ScoredChunk(chunk=chunk, score=UNSCORED)
            for chunk in self.related(query, limit=limit, exclude_path=exclude_path)
        ]

    @abstractmethod
    def related(self, query: str, limit: int = 5, exclude_path: str = "") -> list[CodeChunk]:
        """Chunks worth showing alongside ``query``.

        ``exclude_path`` drops chunks from a file the caller already has in
        full. Returns an empty list rather than raising when there is nothing
        to say: retrieval is an improvement to the prompt, never a
        precondition for reviewing (Level 13, decision D-5).
        """


class DriftJudge(ABC):
    """Asks whether one document section still describes the code.

    A port because the question needs a language model and this layer may not
    know which one. The interface is deliberately one method returning one of
    three values: the model selects, it does not author. Nothing it returns
    reaches a reader as prose, and nothing it returns can block — Level 20's
    attribution table registers the `DRIFT` namespace as an `AGENT`, and a
    blocking verdict citing one cannot be constructed (ADR 0022).
    """

    @abstractmethod
    def still_describes(self, candidate: DriftCandidate) -> DriftVerdict:
        """The verdict for one candidate. Raising is allowed; the caller
        treats a failure as `UNSURE` and loses the candidate, not the review."""


class Signer(ABC):
    """Signs a decision record's digest, and checks a signature it made.

    A port because the key is a deployment's and never this repository's — a
    key that could be generated here is one an attacker with the repository can
    generate (Level 24, decision D-2). The default adapter reads a key the
    operator supplies and refuses to construct without one; a deployment that
    supplies none gets a signer that signs nothing and says so.

    Symmetric by default, which is honest about what it buys: the verifier
    needs the key the signer had. An asymmetric adapter is a sibling module and
    a key-distribution problem this repository cannot solve on anybody's behalf.
    """

    @property
    @abstractmethod
    def key_id(self) -> str:
        """Which key this is. Never the key itself."""

    @property
    @abstractmethod
    def is_signing(self) -> bool:
        """Whether anything will actually be signed."""

    @abstractmethod
    def sign(self, digest: str) -> tuple[str, str]:
        """The signature and the key id, or two empty strings."""

    @property
    def key_ids(self) -> "tuple[str, ...]":
        """Every key id this can check a signature against.

        Printed beside a verdict that could not check something, because the
        mistake it is for is a name that does not match: a retired key
        configured as `2025-KEY` against records that wrote `2025-key`. An
        operator shown both halves sees the difference rather than deducing it.
        """
        return (self.key_id,) if self.is_signing else ()

    @abstractmethod
    def accepts(self, digest: str, signature: str, key_id: str) -> bool | None:
        """Whether this key produced that signature. Never raises.

        Three answers since Level 30. ``None`` means **no key of that name is
        held**, which is what a deployment that has rotated its key is in, and
        it is not the same fact as *this signature is wrong*. A verifier reads
        the first as unverifiable and the second as tampered; collapsing them
        into one boolean made a routine rotation read as a forgery.
        """


class NullSigner(Signer):
    """Signs nothing, and says so.

    What a deployment with no key gets, and a null object rather than a `None`
    check at every call site — the same choice `NullTracer` made for the same
    reason.

    Records are still written and still chained, and that is worth exactly what
    it is worth: the digest takes no key, so an unsigned chain catches
    corruption and a careless edit, and catches nothing at all from somebody
    who can run this tool. The verifier says so on every unsigned answer rather
    than leaving a deployment to infer it (self-review 24, S-02).
    """

    @property
    def key_id(self) -> str:
        return ""

    @property
    def is_signing(self) -> bool:
        return False

    def sign(self, digest: str) -> tuple[str, str]:
        return "", ""

    def accepts(self, digest: str, signature: str, key_id: str) -> bool | None:
        """Nothing, and *nothing* is now sayable: this holds no key of any name.

        It used to answer ``False``, which said "that signature is wrong" about
        a signature it had not looked at. A verifier handed one reports
        *unverifiable*, which is what it always meant to say.
        """
        return None


class AuditStore(ABC):
    """A sealed decision-record store, as an operator's tool sees it.

    A port because erasure is policy — what to remove, what to refuse — and the
    file it happens to live in is not. Level 22 made the same move when the
    architecture test caught a service reaching into infrastructure for its
    recipes: the answer is not an exception, it is noticing which half is a
    rule about data and which half is I/O.
    """

    @abstractmethod
    def exists(self) -> bool:
        """Whether there is a store here at all.

        Distinct from an empty one: a store with no records is a deployment
        that has reviewed nothing, and a store that is not there is a path
        somebody got wrong. An erasure refuses the second rather than creating
        it.
        """

    @abstractmethod
    def payloads(self) -> list[dict]:
        """Every record, in stored order. Tombstones included."""

    @abstractmethod
    def is_signed(self) -> bool:
        """Whether anything in the store carries a signature."""

    @abstractmethod
    def is_verifiable(self, signer: "Signer") -> tuple[bool, str]:
        """Whether the store verifies, and what is wrong if it does not."""

    @abstractmethod
    def replace(self, payloads: "Sequence[Mapping[str, Any]]", signer: "Signer") -> None:
        """Re-seals the whole store from the beginning, atomically."""


class MemoryStore(ABC):
    """Where one repository's accumulated review history is kept.

    A port because the shipped adapter is a JSON file in the checkout, and a
    team that wants its history somewhere durable — an object store, a table —
    should be able to have that without the workflow learning about it.

    Neither method may raise for an ordinary failure. A missing file, a corrupt
    file, a read-only directory: each is an empty memory and a log line. Every
    review before Level 14 ran without a history, and that is exactly what a
    failed load produces (contract C-8).
    """

    @abstractmethod
    def load(self) -> list[Recollection]:
        """Everything remembered, or nothing when it cannot be read."""

    @abstractmethod
    def save(self, recollections: list[Recollection]) -> None:
        """Replaces the stored memory. Atomic: a failure leaves the previous one."""


@dataclass(frozen=True)
class CaseFixture:
    """One evaluation case together with the source it is annotated against.

    The case is a domain value and says nothing about where its fixture lives;
    this pairs it with the bytes, which is what the grader needs and what only
    an adapter can supply.
    """

    case: EvaluationCase
    content: str
    diff: str = ""


class EvaluationDataset(ABC):
    """The annotated cases the evaluation harness grades against.

    A port rather than a directory walk in the service, because the useful
    version of this later is not a directory: cases exported from real reviews,
    or fetched from wherever a team keeps its ground truth.
    """

    @abstractmethod
    def cases(self) -> list[CaseFixture]:
        """Every case, in a stable order, so two runs' reports diff cleanly."""


@dataclass(frozen=True)
class AccessViolation:
    """One refused attempt to read something.

    Deliberately not the infrastructure's ``AccessRecord``: the workflow needs
    the path and the reason, and nothing else. Allowed reads are the sandbox's
    own business.
    """

    path: str
    reason: str


class AccessAuditor(ABC):
    """Reports the file accesses that were refused during a review.

    The paths the agent asks for come from the diff, so a refused read is
    evidence about the merge request rather than about the model: it is the
    loudest available signal that the reviewed content contains an injection.
    The workflow turns each one into a ``Finding``, which is what puts it in
    front of the gate instead of into a paragraph of prose (ADR 0004).
    """

    @abstractmethod
    def access_violations(self) -> list[AccessViolation]:
        """Every refusal so far, oldest first."""
