"""GitLab implementation of the :class:`CodeForge` port.

Everything that knows GitLab's field names lives here. The layers above receive
:class:`FileChange` and :class:`MergeRequestRef` value objects, so supporting a
second forge means adding a sibling of this module and nothing else
(finding F-27).
"""

from collections.abc import Mapping

from code_reviewer.application.ports import CodeForge, DiffPosition, FileChange, MergeRequestRef
from code_reviewer.application.report import REVIEW_COMMENT_MARKER
from code_reviewer.infrastructure.observability.logging import get_logger
from code_reviewer.infrastructure.security.redaction import SecretRedactor

from .gitlab_client import build_gitlab_client

logger = get_logger(__name__)


def suggestion_marker(path: str, line: int) -> str:
    """Identifies a suggestion this agent already posted, by where it applies.

    Keyed on the location rather than on the rule: two runs proposing
    different edits for one line still produce two buttons on one line, and a
    reader cannot tell which they clicked (self-review S-03).
    """
    return f"<!-- code-reviewer:suggestion:{path}:{line} -->"


class GitLabForge(CodeForge):
    """Reads merge requests from GitLab and posts reviews back."""

    def __init__(self, client=None, redactor: SecretRedactor | None = None):
        # The client is injectable so that a caller can supply a pre-configured
        # or recorded session; by default it is built from the environment.
        self._client = client or build_gitlab_client()
        # Read once: the values this process holds are set before it starts
        # reviewing, and re-reading the environment per comment would only
        # make the masking depend on when it happened.
        self._redactor = redactor or SecretRedactor.from_environment()
        self._projects: dict[str, object] = {}
        self._merge_requests: dict[str, object] = {}

    def fetch_merge_request(self, project_id: int, merge_request_iid: int) -> MergeRequestRef:
        project = self._client.projects.get(project_id)
        merge_request = project.mergerequests.get(merge_request_iid)

        # The commits a note anchors on. Absent on older instances and in
        # unusual states; empty then, which costs suggestions and nothing else
        # (Level 22).
        # Read as a mapping or not at all: the client returns a dict, and
        # anything else is a shape this adapter does not understand.
        raw_refs = getattr(merge_request, "diff_refs", None)
        refs: Mapping[str, object] = raw_refs if isinstance(raw_refs, Mapping) else {}

        reference = MergeRequestRef(
            project_id=str(project_id),
            merge_request_id=str(merge_request_iid),
            project_name=getattr(project, "name", ""),
            head_sha=str(refs.get("head_sha") or getattr(merge_request, "sha", "") or ""),
            base_sha=str(refs.get("base_sha") or ""),
            start_sha=str(refs.get("start_sha") or ""),
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
        body = self._redact(body)

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

    def publish_suggestion(self, reference: MergeRequestRef, position: DiffPosition, body: str) -> None:
        """Posts an applicable suggestion as a note on the line it edits.

        A discussion rather than a note: GitLab applies a `suggestion` block
        only from a note attached to the diff. It is still a comment — nothing
        here writes to the repository, and applying the change stays a
        deliberate click by somebody with commit rights (Level 22, D-1).
        """
        merge_request = self._merge_request(reference)
        marker = suggestion_marker(position.path, position.line)
        if self._already_suggested(merge_request, marker):
            logger.info(
                "A suggestion is already posted on this line; not posting a second",
                extra={"fields": {"path": position.path, "line": position.line}},
            )
            return

        merge_request.discussions.create(
            {
                "body": f"{self._redact(body)}\n\n{marker}",
                "position": {
                    "position_type": "text",
                    "base_sha": position.base_sha,
                    "start_sha": position.start_sha,
                    "head_sha": position.head_sha,
                    "new_path": position.path,
                    "old_path": position.path,
                    "new_line": position.line,
                },
            }
        )

    @staticmethod
    def _already_suggested(merge_request, marker: str) -> bool:
        """Whether this suggestion is already on the thread.

        Level 5 solved this for the review comment by putting a marker in the
        body, because the body is the one thing guaranteed to travel with the
        note. The same answer here, for the same reason (finding G-12,
        self-review S-03).

        A forge that cannot list its discussions posts anyway: losing the
        idempotency is cosmetic, and losing the suggestion is not.
        """
        try:
            discussions = merge_request.discussions.list(all=True)
        except Exception as exc:
            logger.warning(
                "Could not read existing suggestions; posting this one",
                extra={"fields": {"error": str(exc)}},
            )
            return False

        for discussion in discussions:
            for note in (getattr(discussion, "attributes", {}) or {}).get("notes", []):
                if marker in str(note.get("body", "")):
                    return True
        return False

    def _redact(self, body: str) -> str:
        """Masks anything secret-shaped on the way to the merge request.

        The model's prose is already masked where it is produced. This is the
        layer for everything else that ends up in the comment: an exception
        message from a specialist, a stack-free `str(exc)` from a file that
        could not be reviewed, a tool's error string. None of those is model
        output and none of them went through a redactor before (self-review
        R-03).

        Here rather than in the renderer because this is the one choke point
        every published body goes through, and because the layer that cannot
        produce a false negative -- the values this process holds -- is an
        adapter's knowledge rather than the application's.
        """
        result = self._redactor.redact_with_report(body)
        if result.count:
            logger.warning(
                "Masked secret-shaped text in the review comment",
                extra={"fields": {"count": result.count}},
            )
        return result.text

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
