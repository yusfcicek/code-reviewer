"""Reading a GitLab webhook payload into something this project understands.

Separate from the routing because it is the one part that knows GitLab's field
names, and because the rule about what to do with an event nobody asked for is
worth stating in one place: an endpoint that returns an error for events it does
not care about gets disabled by whoever is watching the delivery log.
"""

from typing import Any

from code_reviewer.domain.job import ReviewTarget

#: Merge-request actions worth reviewing. `close`, `merge` and `approved` are
#: not: the code either stopped mattering or already landed.
REVIEWABLE_ACTIONS = frozenset({"open", "reopen", "update"})


class EventError(ValueError):
    """The payload is a merge-request event and cannot be acted on."""


def read_merge_request_event(document: dict[str, Any]) -> ReviewTarget | None:
    """The review this event asks for, or ``None`` if it asks for none.

    Raises:
        EventError: when it *is* a reviewable merge-request event but is
            missing something the review needs. That is a 400 — the sender
            has a bug — rather than a silent skip.
    """
    if document.get("object_kind") != "merge_request":
        return None

    attributes = document.get("object_attributes")
    if not isinstance(attributes, dict):
        raise EventError("a merge_request event must carry object_attributes")

    if attributes.get("action") not in REVIEWABLE_ACTIONS:
        return None

    project = document.get("project")
    project_id = (project or {}).get("id") if isinstance(project, dict) else None
    if project_id is None:
        project_id = attributes.get("target_project_id")

    iid = attributes.get("iid")
    if not isinstance(project_id, int) or not isinstance(iid, int):
        raise EventError("a merge_request event must carry a project id and an iid")

    head_sha = attributes.get("last_commit", {})
    head_sha = head_sha.get("id", "") if isinstance(head_sha, dict) else ""

    return ReviewTarget(
        project_id=project_id,
        merge_request_iid=iid,
        head_sha=head_sha if isinstance(head_sha, str) else "",
    )
