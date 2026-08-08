"""Unit tests for the merge-request comment renderer.

The "Pipeline BLOCKED" header was unreachable, because the flag that selected it
was a string compared against an enum (finding F-01). Rendering is separated
from orchestration here so that both branches can be asserted directly.
"""

import unittest

from code_reviewer.application.report import REVIEW_COMMENT_MARKER, render_review_comment
from code_reviewer.domain.gate import GateEvaluation, ReviewGateResult
from code_reviewer.domain.outcome import ReviewOutcome


def _evaluation(result, blocking=(), reasons=()):
    return GateEvaluation(
        result=result,
        exit_code=1 if result is ReviewGateResult.FAIL else 0,
        reasons=list(reasons),
        scores={"quality": 80},
        blocking_issues=list(blocking),
    )


class TestRenderReviewComment(unittest.TestCase):
    def test_passing_review_announces_a_pass(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.PASS))

        comment = render_review_comment("1.0", outcome, ["## Review for `a.py`\nfine"])

        self.assertIn("Pipeline PASSED", comment)
        self.assertNotIn("Pipeline BLOCKED", comment)

    def test_blocking_review_announces_the_block_and_lists_the_issues(self):
        outcome = ReviewOutcome()
        outcome.record("src/db.py", _evaluation(ReviewGateResult.FAIL, blocking=["SAST Scan Failed"]))

        comment = render_review_comment("1.0", outcome, ["## Review for `src/db.py`\nbad"])

        self.assertIn("Pipeline BLOCKED", comment)
        self.assertIn("src/db.py: SAST Scan Failed", comment)

    def test_warnings_are_surfaced_without_claiming_a_block(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.WARN, reasons=["Breaking Changes Detected"]))

        comment = render_review_comment("1.0", outcome, ["## Review for `a.py`\nhmm"])

        self.assertIn("Breaking Changes Detected", comment)
        self.assertNotIn("Pipeline BLOCKED", comment)

    def test_policy_version_and_file_count_are_reported(self):
        outcome = ReviewOutcome()
        outcome.record("a.py", _evaluation(ReviewGateResult.PASS))
        outcome.record_unevaluated("docs.md")

        comment = render_review_comment("2.3", outcome, ["## Review for `a.py`\nfine"])

        self.assertIn("Policy v2.3", comment)
        self.assertIn("2", comment)  # files considered

    def test_sections_are_included_verbatim(self):
        outcome = ReviewOutcome()

        comment = render_review_comment("1.0", outcome, ["SECTION-ONE", "SECTION-TWO"])

        self.assertIn("SECTION-ONE", comment)
        self.assertIn("SECTION-TWO", comment)


if __name__ == "__main__":
    unittest.main()


class TestTheCommentCarriesAMarker(unittest.TestCase):
    """One merge request, one review comment, however often the pipeline runs.

    The marker is how the forge finds the comment it wrote last time. It lives
    in the body rather than in stored state, because the body is the one thing
    guaranteed to travel with the comment — a note id kept in a file, a label
    or a pipeline variable can drift out of sync with the thread it describes
    (finding G-12, decision D-1).
    """

    def _render(self, **kwargs):
        outcome = ReviewOutcome()
        return render_review_comment("1.0", outcome, kwargs.get("sections", ["## a\n"]))

    def test_the_body_starts_with_the_marker(self):
        self.assertTrue(self._render().startswith(REVIEW_COMMENT_MARKER))

    def test_the_marker_is_an_html_comment(self):
        """Invisible in the rendered view; a reader never sees plumbing."""
        self.assertTrue(REVIEW_COMMENT_MARKER.startswith("<!--"))
        self.assertTrue(REVIEW_COMMENT_MARKER.rstrip().endswith("-->"))

    def test_the_marker_names_the_tool(self):
        """Two tools posting to one merge request must not collide."""
        self.assertIn("code-reviewer", REVIEW_COMMENT_MARKER)

    def test_the_marker_is_the_same_across_renders(self):
        """It identifies the agent's comment, not a particular run."""
        first = self._render(sections=["## a\n"])
        second = self._render(sections=["## completely different\n"])

        self.assertEqual(first.split("\n")[0], second.split("\n")[0])

    def test_the_marker_appears_once(self):
        self.assertEqual(self._render().count(REVIEW_COMMENT_MARKER), 1)


class TestTheCommentFitsThePlatformLimit(unittest.TestCase):
    """A review too large to post is the worst failure mode available.

    The review ran, the verdict is correct, and the API call that publishes it
    is rejected — so the merge request shows nothing at all (finding G-19).
    """

    @staticmethod
    def _rendered(section_count: int, limit: int):
        outcome = ReviewOutcome()
        sections = [f"## Review for `file_{i}.py`\n" + ("x" * 500) for i in range(section_count)]
        return render_review_comment("1.0", outcome, sections, max_chars=limit)

    def test_a_short_body_is_returned_unchanged(self):
        body = self._rendered(1, limit=100_000)

        self.assertNotIn("truncated", body)

    def test_an_oversized_body_is_cut_to_the_limit(self):
        body = self._rendered(50, limit=2_000)

        self.assertLessEqual(len(body), 2_000)

    def test_the_verdict_survives_truncation(self):
        """The decision is at the top; that is the part that must never go."""
        body = self._rendered(50, limit=2_000)

        self.assertIn("AI Review Report", body)
        self.assertIn("Pipeline PASSED", body)

    def test_the_marker_survives_truncation(self):
        """Losing it would make the next run post a second comment."""
        body = self._rendered(50, limit=2_000)

        self.assertTrue(body.startswith(REVIEW_COMMENT_MARKER))

    def test_the_notice_says_the_report_was_truncated(self):
        body = self._rendered(50, limit=2_000)

        self.assertIn("truncated", body.lower())

    def test_the_notice_says_how_much_was_dropped(self):
        body = self._rendered(50, limit=2_000)

        self.assertRegex(body, r"[\d,]+ characters")

    def test_the_output_ends_in_prose_rather_than_mid_table(self):
        """The cut can land anywhere; the notice is appended after it."""
        body = self._rendered(50, limit=2_000)

        self.assertTrue(body.rstrip().endswith("_"), body[-120:])

    def test_a_body_exactly_at_the_limit_is_untouched(self):
        outcome = ReviewOutcome()
        short = render_review_comment("1.0", outcome, ["## a\n"])

        self.assertEqual(render_review_comment("1.0", outcome, ["## a\n"], max_chars=len(short)), short)

    def test_the_limit_is_read_from_the_environment(self):
        from code_reviewer.application.report import max_comment_chars_from_env

        self.assertEqual(max_comment_chars_from_env({"REVIEW_MAX_COMMENT_CHARS": "1234"}), 1234)

    def test_a_nonsense_limit_falls_back_to_the_default(self):
        from code_reviewer.application.report import (
            DEFAULT_MAX_COMMENT_CHARS,
            max_comment_chars_from_env,
        )

        for value in ("lots", "0", "-1", ""):
            with self.subTest(value=value):
                self.assertEqual(
                    max_comment_chars_from_env({"REVIEW_MAX_COMMENT_CHARS": value}),
                    DEFAULT_MAX_COMMENT_CHARS,
                )

    def test_the_default_sits_under_the_platform_ceiling(self):
        from code_reviewer.application.report import DEFAULT_MAX_COMMENT_CHARS

        self.assertLess(DEFAULT_MAX_COMMENT_CHARS, 1_000_000)
