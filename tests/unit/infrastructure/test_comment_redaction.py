"""R-03 — the last text that reached the comment unredacted.

Since Level 8 the model's output is masked on the way out, in two layers:
values this process holds first, shapes second. A failure message is not model
output and never went through it — `f"{type(error).__name__}: {error}"` from a
specialist and `str(exc)` from a file that could not be reviewed are both
rendered into the comment verbatim, and an exception from an HTTP client can
carry a URL, a header dump or a response body.

Redacted at the publishing boundary rather than at each of the places that
build text, because that is the one choke point every path goes through.
"""

import unittest
from unittest.mock import MagicMock, patch

from code_reviewer.application.ports import MergeRequestRef
from code_reviewer.infrastructure.forge.gitlab_forge import GitLabForge
from code_reviewer.infrastructure.security.redaction import MASK

SECRET = "glpat-averyrealisticlookingtoken"
REFERENCE = MergeRequestRef(project_id="1", merge_request_id="2", project_name="p", head_sha="abc")


class TestThePublishedBodyIsRedacted(unittest.TestCase):
    def _forge(self, existing=None):
        client = MagicMock()
        merge_request = client.projects.get.return_value.mergerequests.get.return_value
        merge_request.notes.list.return_value = [existing] if existing is not None else []
        forge = GitLabForge(client=client)
        forge.fetch_merge_request(1, 2)
        return forge, merge_request

    def test_a_secret_in_a_failure_message_never_reaches_the_comment(self):
        with patch.dict("os.environ", {"GITLAB_TOKEN": SECRET}, clear=False):
            forge, merge_request = self._forge()

            forge.publish_comment(REFERENCE, f"## Could not review\n> ConnectionError: {SECRET}")

        published = merge_request.notes.create.call_args[0][0]["body"]
        self.assertNotIn(SECRET, published)
        self.assertIn(MASK, published)

    def test_an_edited_comment_is_redacted_too(self):
        """The update path posts a body of its own; redacting only the create
        path would leave the more common one open."""
        existing = MagicMock()
        existing.body = "<!-- code-reviewer:ai-review-report -->\nold"
        with patch.dict("os.environ", {"GITLAB_TOKEN": SECRET}, clear=False):
            forge, _ = self._forge(existing=existing)

            forge.publish_comment(REFERENCE, f"<!-- code-reviewer:ai-review-report -->\na token: {SECRET}")

        self.assertNotIn(SECRET, existing.body)

    def test_an_ordinary_comment_is_posted_unchanged(self):
        forge, merge_request = self._forge()
        body = "## Review\nNothing secret here."

        forge.publish_comment(REFERENCE, body)

        self.assertEqual(merge_request.notes.create.call_args[0][0]["body"], body)
