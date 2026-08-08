""" "We could not look" must never be reported as "there was nothing to see".

A file has three states, and two of them look identical from the outside
(finding G-09):

======================  ==========================================  =========
State                   Meaning                                     Effect
======================  ==========================================  =========
findings                analysis ran and found things               blocks
no findings             analysis ran and found nothing              passes
**analysis error**      analysis could not run                      **blocks**
======================  ==========================================  =========

Before this level the third produced an empty list and passed. That is the
same defect as F-01 and F-32 in this repository's own inventory: a failure
path that silently produces the permissive answer.

A *narration* failure is deliberately not in that table. Static analysis still
ran, the verdict is already known, and only the prose is missing. A model that
has run out of credit must not be able to stop a clean merge request — that is
how teams end up disabling the gate entirely.
"""

import unittest

from code_reviewer.application.ports import (
    CodeForge,
    FileChange,
    MergeRequestRef,
    Reviewer,
    StaticAnalysis,
)
from code_reviewer.application.review_service import ReviewService
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.suppression import SuppressionResult
from code_reviewer.domain.triage import ReviewTriage

DIFF = "\n".join(f"+ line {n}" for n in range(60))


class _Forge(CodeForge):
    def __init__(self, paths=("src/a.py",)):
        self.paths = paths
        self.published = None

    def fetch_merge_request(self, project_id, merge_request_iid):
        return MergeRequestRef(project_id=str(project_id), merge_request_id=str(merge_request_iid))

    def fetch_changes(self, reference):
        return [FileChange(path=path, diff=DIFF) for path in self.paths]

    def fetch_file(self, reference, path):
        return "value = 1\n"

    def publish_comment(self, reference, body):
        self.published = body


class _Reviewer(Reviewer):
    def __init__(self, error=None):
        self.error = error

    def review_diff(self, filename, diff_content, full_file_content=None, other_files=None):
        if self.error is not None:
            raise self.error
        return "# Review\nLooks fine."


class _BrokenAnalysis(StaticAnalysis):
    """The suite itself fails — nothing was inspected."""

    def analyze(self, file_path, content, diff=""):
        raise RuntimeError("the AST parser gave up")


class _CleanAnalysis(StaticAnalysis):
    """The suite ran and found nothing. Not the same thing at all."""

    def analyze(self, file_path, content, diff=""):
        return SuppressionResult()


def _run(analysis, reviewer=None, policy=None, forge=None):
    policy = policy or ReviewPolicy()
    return ReviewService(
        forge=forge or _Forge(),
        reviewer=reviewer or _Reviewer(),
        triage=ReviewTriage(policy),
        policy=policy,
        analysis=analysis,
    ).review(1, 2)


class TestAnalysisRanAndFoundNothing(unittest.TestCase):
    """The baseline the failing case has to be distinguishable from."""

    def setUp(self):
        self.result = _run(_CleanAnalysis())

    def test_the_outcome_is_not_blocking(self):
        self.assertFalse(self.result.outcome.is_blocking)

    def test_the_exit_code_is_zero(self):
        self.assertEqual(self.result.exit_code, 0)

    def test_no_file_is_recorded_as_unanalysed(self):
        self.assertEqual(self.result.outcome.unanalysed_files, [])


class TestAnalysisCouldNotRun(unittest.TestCase):
    def setUp(self):
        self.result = _run(_BrokenAnalysis())

    def test_the_file_is_recorded_as_unanalysed(self):
        self.assertEqual([path for path, _ in self.result.outcome.unanalysed_files], ["src/a.py"])

    def test_the_error_is_recorded_alongside_it(self):
        self.assertIn("AST parser gave up", self.result.outcome.unanalysed_files[0][1])

    def test_the_outcome_is_blocking_under_the_default_policy(self):
        self.assertTrue(self.result.outcome.is_blocking)

    def test_the_exit_code_is_non_zero(self):
        self.assertEqual(self.result.exit_code, 1)

    def test_the_blocking_reason_names_the_file_and_the_error(self):
        reasons = "\n".join(self.result.outcome.blocking_issues)

        self.assertIn("src/a.py", reasons)
        self.assertIn("AST parser gave up", reasons)

    def test_the_reason_says_the_analysis_did_not_run(self):
        """Distinguishable from "the analyzer found a problem" at a glance."""
        reasons = "\n".join(self.result.outcome.blocking_issues).lower()

        self.assertIn("could not", reasons)

    def test_the_published_comment_says_the_analysis_did_not_run(self):
        """The reader's first question about a file with no findings."""
        self.assertIn("Not analysed", self.result.comment)
        self.assertIn("src/a.py", self.result.comment)
        self.assertIn("AST parser gave up", self.result.comment)

    def test_the_comment_warns_that_absent_findings_are_not_a_clean_bill(self):
        self.assertIn("nothing was examined", self.result.comment)


class TestOptingOut(unittest.TestCase):
    def setUp(self):
        policy = ReviewPolicy()
        policy.gate.fail_pipeline_on_analysis_error = False
        self.result = _run(_BrokenAnalysis(), policy=policy)

    def test_the_file_is_still_recorded_as_unanalysed(self):
        """Turning off the block does not turn off the knowledge."""
        self.assertEqual(len(self.result.outcome.unanalysed_files), 1)

    def test_the_pipeline_is_not_failed(self):
        self.assertEqual(self.result.exit_code, 0)

    def test_it_is_still_a_warning(self):
        self.assertTrue(any("src/a.py" in warning for warning in self.result.outcome.warnings))


class TestNarrationFailureStillOnlyWarns(unittest.TestCase):
    """Regression guard for the asymmetry, which is the point of the level.

    Static analysis ran; only the prose is missing. Blocking here would let a
    model that has run out of credit stop a clean merge request.
    """

    def setUp(self):
        self.result = _run(_CleanAnalysis(), reviewer=_Reviewer(error=RuntimeError("quota")))

    def test_the_file_is_recorded_as_failed(self):
        self.assertEqual([path for path, _ in self.result.outcome.failed_files], ["src/a.py"])

    def test_it_is_not_recorded_as_unanalysed(self):
        self.assertEqual(self.result.outcome.unanalysed_files, [])

    def test_the_pipeline_is_not_failed(self):
        self.assertEqual(self.result.exit_code, 0)

    def test_it_appears_as_a_warning(self):
        self.assertTrue(self.result.outcome.warnings)


class TestOneFileDoesNotCondemnTheOthers(unittest.TestCase):
    def test_a_second_file_is_still_reviewed(self):
        forge = _Forge(paths=("src/a.py", "src/b.py"))

        result = _run(_BrokenAnalysis(), forge=forge)

        self.assertEqual(len(result.outcome.unanalysed_files), 2)
        self.assertIn("src/b.py", result.comment)


if __name__ == "__main__":
    unittest.main()


class TestPublishingIsOptional(unittest.TestCase):
    """`--dry-run` runs the whole workflow and posts nothing.

    Asserted here against the real `ReviewService`, not a mock of it: a test
    that stubs the object it is checking the signature of cannot catch a
    signature that does not exist (finding G-13).
    """

    def test_the_comment_is_published_by_default(self):
        forge = _Forge()
        policy = ReviewPolicy()
        ReviewService(
            forge=forge,
            reviewer=_Reviewer(),
            triage=ReviewTriage(policy),
            policy=policy,
            analysis=_CleanAnalysis(),
        ).review(1, 2)

        self.assertIsNotNone(forge.published)

    def test_publish_false_posts_nothing(self):
        forge = _Forge()
        policy = ReviewPolicy()
        ReviewService(
            forge=forge,
            reviewer=_Reviewer(),
            triage=ReviewTriage(policy),
            policy=policy,
            analysis=_CleanAnalysis(),
        ).review(1, 2, publish=False)

        self.assertIsNone(forge.published)

    def test_the_report_is_still_produced(self):
        """Not posting is not the same as not reviewing."""
        forge = _Forge()
        policy = ReviewPolicy()
        result = ReviewService(
            forge=forge,
            reviewer=_Reviewer(),
            triage=ReviewTriage(policy),
            policy=policy,
            analysis=_CleanAnalysis(),
        ).review(1, 2, publish=False)

        self.assertIn("AI Review Report", result.comment)

    def test_the_verdict_is_unaffected(self):
        forge = _Forge()
        policy = ReviewPolicy()
        result = ReviewService(
            forge=forge,
            reviewer=_Reviewer(),
            triage=ReviewTriage(policy),
            policy=policy,
            analysis=_BrokenAnalysis(),
        ).review(1, 2, publish=False)

        self.assertEqual(result.exit_code, 1)
