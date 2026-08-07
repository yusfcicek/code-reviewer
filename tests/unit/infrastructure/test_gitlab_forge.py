"""Unit tests for the GitLab adapter.

The adapter is the only place that knows GitLab's payload shape. These tests
drive it against a stub client, so they assert the translation into domain-
neutral value objects without a network.
"""

import unittest
from unittest.mock import MagicMock

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
