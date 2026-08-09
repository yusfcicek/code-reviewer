"""Unit tests for the GitLab adapter.

The adapter is the only place that knows GitLab's payload shape. These tests
drive it against a stub client, so they assert the translation into domain-
neutral value objects without a network.
"""

import unittest
from unittest.mock import MagicMock, patch

from code_reviewer.application.ports import CodeForge, FileChange
from code_reviewer.infrastructure.forge.gitlab_forge import GitLabForge

CHANGES_PAYLOAD = {
    "changes": [
        {
            "new_path": "src/app.py",
            "old_path": "src/app.py",
            "diff": "+ line",
            "deleted_file": False,
            "new_file": False,
        },
        {
            "new_path": "src/gone.py",
            "old_path": "src/gone.py",
            "diff": "- line",
            "deleted_file": True,
            "new_file": False,
        },
        {
            "new_path": "src/new.py",
            "old_path": "src/new.py",
            "diff": "+ line",
            "deleted_file": False,
            "new_file": True,
        },
    ]
}


def _client(file_content="value = 1\n", raises=False):
    client = MagicMock()
    project = client.projects.get.return_value
    project.name = "team/service"

    merge_request = project.mergerequests.get.return_value
    merge_request.sha = "abc123"
    merge_request.changes.return_value = CHANGES_PAYLOAD

    blob = project.files.get.return_value
    if raises:
        project.files.get.side_effect = RuntimeError("binary file")
    else:
        blob.decode.return_value = file_content.encode("utf-8")

    return client


class TestFetchMergeRequest(unittest.TestCase):
    def test_it_satisfies_the_port(self):
        self.assertIsInstance(GitLabForge(client=_client()), CodeForge)

    def test_reference_carries_project_name_and_head_sha(self):
        forge = GitLabForge(client=_client())

        reference = forge.fetch_merge_request(7, 12)

        self.assertEqual(reference.project_id, "7")
        self.assertEqual(reference.merge_request_id, "12")
        self.assertEqual(reference.project_name, "team/service")
        self.assertEqual(reference.head_sha, "abc123")


class TestFetchChanges(unittest.TestCase):
    def setUp(self):
        self.forge = GitLabForge(client=_client())
        self.reference = self.forge.fetch_merge_request(7, 12)

    def test_every_change_becomes_a_file_change(self):
        changes = self.forge.fetch_changes(self.reference)

        self.assertEqual(len(changes), 3)
        self.assertTrue(all(isinstance(change, FileChange) for change in changes))

    def test_deletion_flag_is_translated(self):
        changes = {change.path: change for change in self.forge.fetch_changes(self.reference)}

        self.assertTrue(changes["src/gone.py"].is_deleted)
        self.assertFalse(changes["src/app.py"].is_deleted)

    def test_new_file_flag_is_translated(self):
        changes = {change.path: change for change in self.forge.fetch_changes(self.reference)}

        self.assertTrue(changes["src/new.py"].is_new)

    def test_missing_diff_becomes_an_empty_string(self):
        client = _client()
        client.projects.get.return_value.mergerequests.get.return_value.changes.return_value = {
            "changes": [{"new_path": "a.py", "deleted_file": False}]
        }
        forge = GitLabForge(client=client)
        reference = forge.fetch_merge_request(1, 1)

        self.assertEqual(forge.fetch_changes(reference)[0].diff, "")

    def test_an_empty_merge_request_yields_no_changes(self):
        client = _client()
        client.projects.get.return_value.mergerequests.get.return_value.changes.return_value = {}
        forge = GitLabForge(client=client)
        reference = forge.fetch_merge_request(1, 1)

        self.assertEqual(forge.fetch_changes(reference), [])


class TestFetchFile(unittest.TestCase):
    def test_content_is_decoded(self):
        forge = GitLabForge(client=_client("print('hi')\n"))
        reference = forge.fetch_merge_request(7, 12)

        self.assertEqual(forge.fetch_file(reference, "src/app.py"), "print('hi')\n")

    def test_content_is_read_at_the_reviewed_commit(self):
        client = _client()
        forge = GitLabForge(client=client)
        reference = forge.fetch_merge_request(7, 12)

        forge.fetch_file(reference, "src/app.py")

        client.projects.get.return_value.files.get.assert_called_with(file_path="src/app.py", ref="abc123")

    def test_an_unreadable_file_reads_as_none_rather_than_raising(self):
        forge = GitLabForge(client=_client(raises=True))
        reference = forge.fetch_merge_request(7, 12)

        self.assertIsNone(forge.fetch_file(reference, "assets/logo.png"))


class TestPublishComment(unittest.TestCase):
    def test_comment_is_posted_as_a_note(self):
        client = _client()
        forge = GitLabForge(client=client)
        reference = forge.fetch_merge_request(7, 12)

        forge.publish_comment(reference, "the review body")

        client.projects.get.return_value.mergerequests.get.return_value.notes.create.assert_called_once_with(
            {"body": "the review body"}
        )


if __name__ == "__main__":
    unittest.main()


class TestPublishingASuggestion(unittest.TestCase):
    """Level 22 — a note anchored on the line it edits.

    GitLab applies a `suggestion` block only from a note attached to the diff,
    which needs the three commits it compares. Posting one is still posting a
    comment: nothing here writes to the repository.
    """

    def _forge(self):
        client = MagicMock()
        merge_request = client.projects.get.return_value.mergerequests.get.return_value
        merge_request.diff_refs = {
            "base_sha": "aaa",
            "start_sha": "bbb",
            "head_sha": "ccc",
        }
        merge_request.sha = "ccc"
        forge = GitLabForge(client=client)
        return forge, merge_request

    def test_the_reference_carries_the_commits_a_note_anchors_on(self):
        forge, _ = self._forge()

        reference = forge.fetch_merge_request(1, 2)

        self.assertEqual((reference.base_sha, reference.start_sha), ("aaa", "bbb"))
        self.assertEqual(reference.head_sha, "ccc")

    def test_a_merge_request_without_diff_refs_yields_empty_ones(self):
        """Older instances and unusual states do not report them, and the
        review is unchanged: it costs the suggestions and nothing else."""
        forge, merge_request = self._forge()
        merge_request.diff_refs = None

        reference = forge.fetch_merge_request(1, 2)

        self.assertEqual(reference.base_sha, "")

    def test_the_note_is_created_as_a_discussion_on_the_line(self):
        from code_reviewer.application.ports import DiffPosition

        forge, merge_request = self._forge()
        reference = forge.fetch_merge_request(1, 2)
        position = DiffPosition(path="src/app.py", line=11, base_sha="aaa", start_sha="bbb", head_sha="ccc")

        forge.publish_suggestion(reference, position, "```suggestion:-0+0\nx = 1\n```")

        payload = merge_request.discussions.create.call_args[0][0]
        self.assertIn("suggestion", payload["body"])
        self.assertEqual(payload["position"]["new_path"], "src/app.py")
        self.assertEqual(payload["position"]["new_line"], 11)
        self.assertEqual(payload["position"]["position_type"], "text")

    def test_the_body_is_redacted_like_every_other_published_text(self):
        from code_reviewer.application.ports import DiffPosition

        with patch.dict("os.environ", {"GITLAB_TOKEN": "glpat-averyrealisticlookingtoken"}):
            forge, merge_request = self._forge()
            reference = forge.fetch_merge_request(1, 2)
            position = DiffPosition(path="a.py", line=1, base_sha="aaa", start_sha="bbb", head_sha="ccc")

            forge.publish_suggestion(reference, position, "token glpat-averyrealisticlookingtoken")

        body = merge_request.discussions.create.call_args[0][0]["body"]
        self.assertNotIn("glpat-averyrealisticlookingtoken", body)
