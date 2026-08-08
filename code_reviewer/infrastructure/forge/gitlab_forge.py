"""GitLab implementation of the :class:`CodeForge` port.

Everything that knows GitLab's field names lives here. The layers above receive
:class:`FileChange` and :class:`MergeRequestRef` value objects, so supporting a
second forge means adding a sibling of this module and nothing else
(finding F-27).
"""

from code_reviewer.application.ports import CodeForge, FileChange, MergeRequestRef
from code_reviewer.application.report import REVIEW_COMMENT_MARKER
from code_reviewer.infrastructure.observability.logging import get_logger

from .gitlab_client import build_gitlab_client

logger = get_logger(__name__)


class GitLabForge(CodeForge):
    """Reads merge requests from GitLab and posts reviews back."""

    def __init__(self, client=None):
        # The client is injectable so that a caller can supply a pre-configured
        # or recorded session; by default it is built from the environment.
        self._client = client or build_gitlab_client()
        self._projects = {}
        self._merge_requests = {}

    def fetch_merge_request(self, project_id: int, merge_request_iid: int) -> MergeRequestRef:
        project = self._client.projects.get(project_id)
        merge_request = project.mergerequests.get(merge_request_iid)

        reference = MergeRequestRef(
            project_id=str(project_id),
            merge_request_id=str(merge_request_iid),
            project_name=getattr(project, "name", ""),
            head_sha=getattr(merge_request, "sha", "") or "",
        )
        # Cached so each port call does not re-fetch; one review targets one
        # merge request.
        self._projects[reference.project_id] = project
        self._merge_requests[self._key(reference)] = merge_request
        return reference

    def fetch_changes(self, reference: MergeRequestRef) -> list[FileChange]:
        merge_request = self._merge_request(reference)
        payload = merge_request.changes().get("changes", [])

        return [
            FileChange(
                path=entry["new_path"],
                diff=entry.get("diff", ""),
                is_deleted=bool(entry.get("deleted_file")),
                is_new=bool(entry.get("new_file")),
                previous_path=entry.get("old_path", "") or "",
            )
            for entry in payload
        ]

    def fetch_file(self, reference: MergeRequestRef, path: str) -> str | None:
        project = self._project(reference)
        try:
            blob = project.files.get(file_path=path, ref=reference.head_sha)
            return blob.decode().decode("utf-8")
        except Exception:
            # Binary files, moved refs and permission gaps all land here. None
            # means "review this from the diff alone", not "abort the review".
            return None

    def publish_comment(self, reference: MergeRequestRef, body: str) -> None:
        """Posts the review, editing the previous one rather than adding to it.

        Five pipeline runs used to leave five reports, with the oldest and
        most wrong at the top of the thread (finding G-12). The agent finds
        its own previous comment by the marker the renderer embeds, so the
        state lives in the comment rather than anywhere that could drift out
        of sync with it.

        Every failure here falls back to creating a comment. Losing the
        idempotency is cosmetic; losing the review is not.
        """
        merge_request = self._merge_request(reference)

        existing = self._existing_review_note(merge_request, body)
        if existing is not None:
            try:
                existing.body = body
                existing.save()
                return
            except Exception as exc:
                logger.warning(
                    "Could not update the existing review comment; posting a new one",
                    extra={"fields": {"error": str(exc)}},
                )

        merge_request.notes.create({"body": body})

    @staticmethod
    def _existing_review_note(merge_request, body: str):
        """The note this agent posted last time, or ``None``.

        Matched on the marker, never on authorship or position: a human reply
        and another tool's report both live in the same thread, and neither
        may be overwritten. A body carrying no marker is not looking for a
        note to replace.
        """
        if REVIEW_COMMENT_MARKER not in body:
            return None

        try:
            notes = merge_request.notes.list(all=True)
        except Exception as exc:
            logger.warning(
                "Could not read existing comments; posting a new one",
                extra={"fields": {"error": str(exc)}},
            )
            return None

        for note in notes:
            if REVIEW_COMMENT_MARKER in (getattr(note, "body", "") or ""):
                return note
        return None

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _key(reference: MergeRequestRef) -> str:
        return f"{reference.project_id}!{reference.merge_request_id}"

    def _project(self, reference: MergeRequestRef):
        project = self._projects.get(reference.project_id)
        if project is None:
            project = self._client.projects.get(int(reference.project_id))
            self._projects[reference.project_id] = project
        return project

    def _merge_request(self, reference: MergeRequestRef):
        merge_request = self._merge_requests.get(self._key(reference))
        if merge_request is None:
            merge_request = self._project(reference).mergerequests.get(int(reference.merge_request_id))
            self._merge_requests[self._key(reference)] = merge_request
        return merge_request
