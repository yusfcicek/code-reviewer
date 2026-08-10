"""Step 4 — putting a suggestion where a person can apply it.

GitLab renders a fenced ```suggestion block as an applicable change **only in a
note attached to a line of the diff**. The same block in the ordinary review
comment is a code block somebody has to retype, which is the difference between
a feature and a decoration — so suggestions go out as diff notes, and the review
comment says how many were posted.
"""

import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from code_reviewer.application.ports import DiffPosition, FileChange
from code_reviewer.application.review_service import ReviewService
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.remediation import Suggestion
from code_reviewer.domain.suppression import SuppressionResult
from code_reviewer.domain.triage import ReviewTriage

from .test_review_service import CLEAN_REVIEW, FakeForge, ScriptedReviewer

SOURCE = "import hashlib\n\n\ndef digest(value):\n    return hashlib.md5(value).hexdigest()\n"

#: A real unified diff touching line 5 — the line the finding is about. The
#: service only proposes on lines the merge request changed, because a note
#: cannot be anchored outside the diff (self-review S-02).
DIFF = (
    "@@ -1,4 +1,5 @@\n import hashlib\n \n \n def digest(value):\n"
    "+    return hashlib.md5(value).hexdigest()\n"
)


def _finding(line=5):
    from code_reviewer.domain.finding import Finding, FindingCategory
    from code_reviewer.domain.severity import Severity

    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.MEDIUM,
        file_path="src/hashing.py",
        line_number=line,
        title="Weak Crypto",
        description="MD5 is broken",
        remediation="Use SHA-256",
        rule_id="SAST.WEAK_CRYPTO",
    )


class SuggestingForge(FakeForge):
    """A forge that reports its diff refs and records the notes it was asked
    to post against a line."""

    def __init__(self, changes, contents=None):
        super().__init__(changes, contents)
        self.suggestions = []

    def fetch_merge_request(self, project_id, merge_request_iid):
        reference = super().fetch_merge_request(project_id, merge_request_iid)
        return replace(reference, base_sha="base", start_sha="start", head_sha="head")

    def publish_suggestion(self, reference, position, body):
        self.suggestions.append((position, body))


class Analysis:
    def __init__(self, findings):
        self._findings = findings

    def analyze(self, file_path, content, diff=""):
        return SuppressionResult(findings=list(self._findings))


def _service(forge, findings, suggest=True):
    policy = ReviewPolicy()
    return ReviewService(
        forge=forge,
        reviewer=ScriptedReviewer(CLEAN_REVIEW),
        triage=ReviewTriage(policy),
        policy=policy,
        analysis=Analysis(findings),
        suggest_fixes=suggest,
    )


def _forge():
    return SuggestingForge([FileChange("src/hashing.py", DIFF)], {"src/hashing.py": SOURCE})


class TestTheSuggestionIsPosted(unittest.TestCase):
    def test_a_suggestion_is_posted_against_the_line_it_edits(self):
        forge = _forge()

        _service(forge, [_finding()]).review(1, 2)

        self.assertEqual(len(forge.suggestions), 1)
        position, _ = forge.suggestions[0]
        self.assertEqual(position.path, "src/hashing.py")
        self.assertEqual(position.line, 5)

    def test_the_body_is_a_suggestion_block_the_platform_can_apply(self):
        forge = _forge()

        _service(forge, [_finding()]).review(1, 2)

        _, body = forge.suggestions[0]
        self.assertIn("```suggestion:-0+0", body)
        self.assertIn("hashlib.sha256(value)", body)
        self.assertIn("SAST.WEAK_CRYPTO", body)

    def test_the_review_comment_says_how_many_were_posted(self):
        forge = _forge()

        _service(forge, [_finding()]).review(1, 2)

        self.assertIn("1 applicable suggestion", forge.published[0])

    def test_a_review_with_no_suggestions_says_nothing_about_them(self):
        forge = _forge()

        _service(forge, []).review(1, 2)

        self.assertEqual(forge.suggestions, [])
        self.assertNotIn("suggestion", forge.published[0].lower())

    def test_the_flag_turns_the_whole_thing_off(self):
        forge = _forge()

        _service(forge, [_finding()], suggest=False).review(1, 2)

        self.assertEqual(forge.suggestions, [])
        self.assertNotIn("suggestion", forge.published[0].lower())

    def test_a_dry_run_posts_nothing(self):
        """`--dry-run` answers "what would this do" without doing any of it,
        and a suggestion is the most visible thing it could do."""
        forge = _forge()

        _service(forge, [_finding()]).review(1, 2, publish=False)

        self.assertEqual(forge.suggestions, [])
        self.assertEqual(forge.published, [])

    def test_a_forge_that_cannot_post_one_does_not_cost_the_review(self):
        """A suggestion is an improvement to a comment, never a precondition
        for publishing it."""
        forge = _forge()
        forge.publish_suggestion = MagicMock(side_effect=RuntimeError("no discussion API"))

        result = _service(forge, [_finding()]).review(1, 2)

        self.assertTrue(forge.published)
        self.assertEqual(result.exit_code, 0)


class TestTheSuggestionBody(unittest.TestCase):
    def test_it_names_the_rule_and_the_recipe(self):
        from code_reviewer.application.remediation_service import render_suggestion

        body = render_suggestion(
            Suggestion.single(
                rule_id="SAST.WEAK_CRYPTO",
                file_path="src/hashing.py",
                start_line=5,
                end_line=5,
                replacement=("    return hashlib.sha256(value).hexdigest()",),
                recipe="md5-to-sha256",
            )
        )

        self.assertIn("SAST.WEAK_CRYPTO", body)
        self.assertIn("md5-to-sha256", body)
        self.assertIn("```suggestion:-0+0", body)

    def test_a_multi_line_suggestion_declares_its_span(self):
        from code_reviewer.application.remediation_service import render_suggestion

        body = render_suggestion(
            Suggestion.single(
                rule_id="SAST.WEAK_CRYPTO",
                file_path="a.py",
                start_line=5,
                end_line=7,
                replacement=("x = 1",),
                recipe="r",
            )
        )

        self.assertIn("```suggestion:-0+2", body)


class TestTheDiffPosition(unittest.TestCase):
    def test_a_position_carries_what_the_platform_needs_to_anchor_a_note(self):
        position = DiffPosition(path="a.py", line=4, base_sha="b", start_sha="s", head_sha="h")

        self.assertEqual((position.path, position.line), ("a.py", 4))
        self.assertEqual(position.head_sha, "h")

    def test_a_position_without_the_shas_is_refused(self):
        """A note anchored on nothing is posted at the top of the file, or
        rejected, depending on the platform's mood."""
        with self.assertRaises(ValueError):
            DiffPosition(path="a.py", line=4, base_sha="", start_sha="s", head_sha="h")
