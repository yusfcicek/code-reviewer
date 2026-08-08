"""Ports the review workflow depends on.

Each port is declared by the layer that *needs* it, not by the layer that
implements it, so the dependency arrow points inwards. Adapters live in
``code_reviewer.infrastructure``.

Every signature here uses builtins or domain types. ``MemoryStrategy`` used to
expose ``get_memory_object() -> "the underlying LangChain memory object"``,
which handed callers a framework type through the abstraction meant to hide it
(finding F-26).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from code_reviewer.domain.evaluation import EvaluationCase
from code_reviewer.domain.retrieval import CodeChunk, ScoredChunk, Vector
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


class Reviewer(ABC):
    """Produces a written review for a single file's diff."""

    @abstractmethod
    def review_diff(
        self,
        filename: str,
        diff_content: str,
        full_file_content: str | None = None,
        other_files: list[str] | None = None,
        related: list[CodeChunk] | None = None,
    ) -> str:
        """Returns the review report for one file, as markdown.

        ``related`` is code retrieved from elsewhere in the checkout. It is
        optional and it defaults to nothing, because a reviewer that cannot
        retrieve is a complete reviewer — it is what this project was for
        twelve levels.
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

    @abstractmethod
    def related(self, query: str, limit: int = 5, exclude_path: str = "") -> list[CodeChunk]:
        """Chunks worth showing alongside ``query``.

        ``exclude_path`` drops chunks from a file the caller already has in
        full. Returns an empty list rather than raising when there is nothing
        to say: retrieval is an improvement to the prompt, never a
        precondition for reviewing (Level 13, decision D-5).
        """


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
