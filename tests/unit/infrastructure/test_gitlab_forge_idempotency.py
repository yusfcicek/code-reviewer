"""One merge request, one review comment, however often the pipeline runs.

Five runs on a long-lived branch left five reports, and the one at the top of
the thread was the oldest and the most wrong (finding G-12). The agent finds
its own previous comment by the marker the renderer embeds in the body, and
edits it.

The fake client models three calls — `notes.list`, `note.save` and
`notes.create` — because those are the three the adapter makes. Anything more
would be modelling GitLab rather than testing this module.
"""

import unittest

from code_reviewer.application.report import REVIEW_COMMENT_MARKER
from code_reviewer.infrastructure.forge.gitlab_forge import GitLabForge


class _Note:
    def __init__(self, body: str, save_error: Exception | None = None):
        self.body = body
        self.saved = 0
        self._save_error = save_error

    def save(self):
        if self._save_error is not None:
            raise self._save_error
        self.saved += 1


class _Notes:
    def __init__(self, existing=(), list_error=None):
        self.notes = list(existing)
        self.created: list[str] = []
        self._list_error = list_error

    def list(self, **_):
        if self._list_error is not None:
            raise self._list_error
        return list(self.notes)

    def create(self, payload):
        note = _Note(payload["body"])
        self.notes.append(note)
        self.created.append(payload["body"])
        return note


class _Client:
    def __init__(self, notes: _Notes):
        self.notes = notes
        self.projects = self

    def get(self, _project_id):
        return self

    @property
    def mergerequests(self):
        return self

    def __getattr__(self, name):  # pragma: no cover - only `name`/`sha` land here
        return ""


class _MergeRequests:
    def __init__(self, notes):
        self._notes = notes

    def get(self, _iid):
        return _MergeRequest(self._notes)


class _MergeRequest:
    def __init__(self, notes):
        self.notes = notes
        self.sha = "abc123"

    def changes(self):
        return {"changes": []}


class _Project:
    def __init__(self, notes):
        self.name = "team/service"
        self.mergerequests = _MergeRequests(notes)


class _Projects:
    def __init__(self, notes):
        self._notes = notes

    def get(self, _project_id):
        return _Project(self._notes)


class _GitLab:
    def __init__(self, notes):
        self.projects = _Projects(notes)


def _forge(existing=(), list_error=None):
    notes = _Notes(existing, list_error=list_error)
    forge = GitLabForge(client=_GitLab(notes))
    reference = forge.fetch_merge_request(7, 12)
    return forge, reference, notes


REVIEW_BODY = f"{REVIEW_COMMENT_MARKER}\n# 🤖 AI Review Report\nAll good."
UPDATED_BODY = f"{REVIEW_COMMENT_MARKER}\n# 🤖 AI Review Report\nNow blocked."


class TestFirstPublish(unittest.TestCase):
    def test_a_note_is_created_when_none_exists(self):
        forge, reference, notes = _forge()

        forge.publish_comment(reference, REVIEW_BODY)

        self.assertEqual(notes.created, [REVIEW_BODY])


class TestSecondPublish(unittest.TestCase):
    def test_the_existing_note_is_edited(self):
        existing = _Note(REVIEW_BODY)
        forge, reference, _ = _forge(existing=[existing])

        forge.publish_comment(reference, UPDATED_BODY)

        self.assertEqual(existing.body, UPDATED_BODY)
        self.assertEqual(existing.saved, 1)

    def test_no_second_note_is_created(self):
        forge, reference, notes = _forge(existing=[_Note(REVIEW_BODY)])

        forge.publish_comment(reference, UPDATED_BODY)

        self.assertEqual(notes.created, [])

    def test_repeated_runs_leave_one_comment(self):
        forge, reference, notes = _forge()

        for _ in range(5):
            forge.publish_comment(reference, REVIEW_BODY)

        self.assertEqual(len(notes.notes), 1)


class TestOtherPeoplesComments(unittest.TestCase):
    """The marker identifies this agent's comment, not any comment."""

    def test_a_note_without_the_marker_is_left_alone(self):
        human = _Note("Looks good to me, merging on Friday.")
        forge, reference, notes = _forge(existing=[human])

        forge.publish_comment(reference, REVIEW_BODY)

        self.assertEqual(human.body, "Looks good to me, merging on Friday.")
        self.assertEqual(human.saved, 0)
        self.assertEqual(notes.created, [REVIEW_BODY])

    def test_a_human_reply_between_runs_survives(self):
        agent = _Note(REVIEW_BODY)
        human = _Note("I disagree about the second finding.")
        forge, reference, _ = _forge(existing=[agent, human])

        forge.publish_comment(reference, UPDATED_BODY)

        self.assertEqual(human.body, "I disagree about the second finding.")
        self.assertEqual(agent.body, UPDATED_BODY)

    def test_another_tool_marker_is_not_matched(self):
        other = _Note("<!-- some-other-bot:report -->\nHello.")
        forge, reference, notes = _forge(existing=[other])

        forge.publish_comment(reference, REVIEW_BODY)

        self.assertEqual(other.saved, 0)
        self.assertEqual(len(notes.created), 1)


class TestFallbacks(unittest.TestCase):
    """Losing idempotency is cosmetic. Losing the review is not."""

    def test_an_uneditable_note_falls_back_to_creating(self):
        stubborn = _Note(REVIEW_BODY, save_error=PermissionError("403"))
        forge, reference, notes = _forge(existing=[stubborn])

        forge.publish_comment(reference, UPDATED_BODY)

        self.assertEqual(notes.created, [UPDATED_BODY])

    def test_an_unlistable_thread_falls_back_to_creating(self):
        forge, reference, notes = _forge(list_error=RuntimeError("rate limited"))

        forge.publish_comment(reference, REVIEW_BODY)

        self.assertEqual(notes.created, [REVIEW_BODY])

    def test_a_body_without_a_marker_is_simply_created(self):
        """A caller that renders its own body still gets a comment."""
        forge, reference, notes = _forge(existing=[_Note(REVIEW_BODY)])

        forge.publish_comment(reference, "an unmarked body")

        self.assertEqual(notes.created, ["an unmarked body"])


if __name__ == "__main__":
    unittest.main()
