"""GitLab implementation of the :class:`CodeForge` port.

Everything that knows GitLab's field names lives here. The layers above receive
:class:`FileChange` and :class:`MergeRequestRef` value objects, so supporting a
second forge means adding a sibling of this module and nothing else
(finding F-27).
"""

from code_reviewer.application.ports import CodeForge, FileChange, MergeRequestRef

from .gitlab_client import build_gitlab_client


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
        self._merge_request(reference).notes.create({"body": body})

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
