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
from typing import Any, List, Optional


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
    def fetch_changes(self, reference: MergeRequestRef) -> List[FileChange]:
        """Returns every file the merge request touches."""

    @abstractmethod
    def fetch_file(self, reference: MergeRequestRef, path: str) -> Optional[str]:
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


class Reviewer(ABC):
    """Produces a written review for a single file's diff."""

    @abstractmethod
    def review_diff(
        self,
        filename: str,
        diff_content: str,
        full_file_content: Optional[str] = None,
        other_files: Optional[List[str]] = None,
    ) -> str:
        """Returns the review report for one file, as markdown."""
