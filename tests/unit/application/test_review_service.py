"""Unit tests for the review workflow.

This is the point of Level 2. The workflow used to live inside a 150-line
function that reached into `project.mergerequests.get(...)` directly, so
exercising it required a live GitLab and it had no tests at all — the one place
where triage, the agent, the gate and metrics meet (findings F-25, F-27).

Everything here runs against in-memory fakes.
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
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.gate import ReviewGateResult
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import SuppressionResult
from code_reviewer.domain.triage import ReviewTriage

CLEAN_REVIEW = """
## 🔒 Security Analysis
- **SAST Scan Result**: PASS - Low
## 🔗 Impact Analysis
- **Risk Assessment**: Low - contained change
## 📊 Code Quality
- **SOLID Compliance**: 90/100
"""

BLOCKING_REVIEW = """
## 🔒 Security Analysis
- **SAST Scan Result**: FAIL - Critical
## 🔗 Impact Analysis
- **Risk Assessment**: Critical - credentials committed
## 📊 Code Quality
- **SOLID Compliance**: 90/100
"""


class FakeForge(CodeForge):
    """An in-memory merge request."""

    def __init__(self, changes, contents=None):
        self._changes = changes
        self._contents = contents or {}
        self.published = []
        self.fetched_files = []

    def fetch_merge_request(self, project_id, merge_request_iid):
        return MergeRequestRef(
            project_id=str(project_id),
            merge_request_id=str(merge_request_iid),
            project_name="fake/project",
            head_sha="deadbeef",
        )

    def fetch_changes(self, reference):
        return list(self._changes)

    def fetch_file(self, reference, path):
        self.fetched_files.append(path)
        return self._contents.get(path)

    def publish_comment(self, reference, body):
        self.published.append(body)


class ScriptedReviewer(Reviewer):
    """Returns a canned report and records what it was asked about."""

    def __init__(self, report=CLEAN_REVIEW, per_file=None):
        self.report = report
        self.per_file = per_file or {}
        self.reviewed = []

    def review_diff(self, brief):
        self.reviewed.append(brief.file_path)
        return self.per_file.get(brief.file_path, self.report)


class RecordingAnalysis(StaticAnalysis):
    """Returns canned findings and records which files it was asked about."""

    def __init__(self, findings=None):
        self._findings = findings or []
        self.analysed = []

    def analyze(self, file_path, content, diff=""):
        self.analysed.append(file_path)
        return SuppressionResult(findings=list(self._findings))


def _finding(severity=Severity.CRITICAL, path="src/app.py"):
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path=path,
        line_number=4,
        title="Command Injection",
        description="eval() executes arbitrary code",
        remediation="Use ast.literal_eval()",
        cwe_id="CWE-95",
    )


def _service(forge, reviewer, policy=None, analysis=None):
    policy = policy or ReviewPolicy()
    return ReviewService(
        forge=forge,
        reviewer=reviewer,
        triage=ReviewTriage(policy),
        policy=policy,
        analysis=analysis,
    )


def _significant_diff(marker="value"):
    return "\n".join(f"+    {marker}_{i} = compute({i})" for i in range(80))


class TestTriageRouting(unittest.TestCase):
    def test_skipped_files_never_reach_the_reviewer(self):
        forge = FakeForge([FileChange("docs/guide.md", "+ a new paragraph")])
        reviewer = ScriptedReviewer()

        _service(forge, reviewer).review(1, 2)

        self.assertEqual(reviewer.reviewed, [])

    def test_auto_approved_files_never_reach_the_reviewer(self):
        forge = FakeForge([FileChange("src/app.py", "+# just a comment\n")])
        reviewer = ScriptedReviewer()

        _service(forge, reviewer).review(1, 2)

        self.assertEqual(reviewer.reviewed, [])

    def test_auto_approved_files_still_appear_in_the_comment(self):
        forge = FakeForge([FileChange("src/app.py", "+# just a comment\n")])

        _service(forge, ScriptedReviewer()).review(1, 2)

        self.assertIn("Auto-Approved", forge.published[0])

    def test_significant_changes_reach_the_reviewer(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])
        reviewer = ScriptedReviewer()

        _service(forge, reviewer).review(1, 2)

        self.assertEqual(reviewer.reviewed, ["src/app.py"])

    def test_deleted_files_are_ignored(self):
        forge = FakeForge([FileChange("src/gone.py", _significant_diff(), is_deleted=True)])
        reviewer = ScriptedReviewer()

        _service(forge, reviewer).review(1, 2)

        self.assertEqual(reviewer.reviewed, [])


class TestGateOutcome(unittest.TestCase):
    def test_clean_review_exits_zero(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])

        result = _service(forge, ScriptedReviewer(CLEAN_REVIEW)).review(1, 2)

        self.assertEqual(result.exit_code, 0)
        self.assertIs(result.outcome.result, ReviewGateResult.PASS)

    def test_failing_review_blocks_and_exits_non_zero(self):
        """Regression for F-01, now asserted through the whole workflow."""
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])

        result = _service(forge, ScriptedReviewer(BLOCKING_REVIEW)).review(1, 2)

        self.assertEqual(result.exit_code, 1)
        self.assertTrue(result.outcome.is_blocking)

    def test_blocking_review_says_so_in_the_comment(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])

        _service(forge, ScriptedReviewer(BLOCKING_REVIEW)).review(1, 2)

        self.assertIn("Pipeline BLOCKED", forge.published[0])

    def test_one_failing_file_among_several_blocks_the_review(self):
        forge = FakeForge(
            [
                FileChange("src/ok.py", _significant_diff("ok")),
                FileChange("src/bad.py", _significant_diff("bad")),
            ]
        )
        reviewer = ScriptedReviewer(CLEAN_REVIEW, per_file={"src/bad.py": BLOCKING_REVIEW})

        result = _service(forge, reviewer).review(1, 2)

        self.assertTrue(result.outcome.is_blocking)
        self.assertTrue(any("src/bad.py" in issue for issue in result.outcome.blocking_issues))

    def test_policy_can_report_without_failing_the_pipeline(self):
        policy = ReviewPolicy()
        policy.gate.fail_pipeline_on_critical = False
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])

        result = _service(forge, ScriptedReviewer(BLOCKING_REVIEW), policy).review(1, 2)

        self.assertTrue(result.outcome.is_blocking)
        self.assertEqual(result.exit_code, 0)


class TestPublishing(unittest.TestCase):
    def test_an_empty_change_set_posts_nothing(self):
        forge = FakeForge([])

        result = _service(forge, ScriptedReviewer()).review(1, 2)

        self.assertEqual(forge.published, [])
        self.assertEqual(result.exit_code, 0)

    def test_a_change_set_of_only_skipped_files_posts_nothing(self):
        forge = FakeForge([FileChange("docs/guide.md", "+ text")])

        _service(forge, ScriptedReviewer()).review(1, 2)

        self.assertEqual(forge.published, [])

    def test_exactly_one_comment_is_posted(self):
        forge = FakeForge(
            [
                FileChange("src/a.py", _significant_diff("a")),
                FileChange("src/b.py", _significant_diff("b")),
            ]
        )

        _service(forge, ScriptedReviewer()).review(1, 2)

        self.assertEqual(len(forge.published), 1)

    def test_the_comment_carries_the_policy_version(self):
        policy = ReviewPolicy()
        policy.version = "4.2"
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])

        _service(forge, ScriptedReviewer(), policy).review(1, 2)

        self.assertIn("Policy v4.2", forge.published[0])


class TestContext(unittest.TestCase):
    def test_full_file_content_is_fetched_for_reviewed_files(self):
        forge = FakeForge(
            [FileChange("src/app.py", _significant_diff())],
            contents={"src/app.py": "value = 1\n"},
        )

        _service(forge, ScriptedReviewer()).review(1, 2)

        self.assertIn("src/app.py", forge.fetched_files)

    def test_a_file_that_cannot_be_read_does_not_abort_the_review(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())], contents={})
        reviewer = ScriptedReviewer()

        result = _service(forge, reviewer).review(1, 2)

        self.assertEqual(reviewer.reviewed, ["src/app.py"])
        self.assertEqual(result.exit_code, 0)


class TestMetrics(unittest.TestCase):
    def test_one_metric_is_recorded_per_considered_file(self):
        forge = FakeForge(
            [
                FileChange("src/a.py", _significant_diff("a")),
                FileChange("src/b.py", "+# comment\n"),
                FileChange("docs/c.md", "+ text"),
            ]
        )

        result = _service(forge, ScriptedReviewer()).review(1, 2)

        # The skipped markdown file is not measured; the other two are.
        self.assertEqual(len(result.metrics), 2)

    def test_metrics_carry_the_triage_decision(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])

        result = _service(forge, ScriptedReviewer()).review(1, 2)

        self.assertIn("full", result.metrics[0].triage_decisions)

    def test_metrics_carry_the_gate_result(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])

        result = _service(forge, ScriptedReviewer(BLOCKING_REVIEW)).review(1, 2)

        self.assertEqual(result.metrics[0].gate_result, "fail")


class TestStaticAnalysisIntegration(unittest.TestCase):
    """Regression for F-32.

    The analyzers were reachable only as agent tools, so whether a file got a
    security scan depended on the model deciding to ask for one.
    """

    def test_every_reviewed_file_is_analysed(self):
        forge = FakeForge(
            [
                FileChange("src/a.py", _significant_diff("a")),
                FileChange("src/b.py", _significant_diff("b")),
            ]
        )
        analysis = RecordingAnalysis()

        _service(forge, ScriptedReviewer(), analysis=analysis).review(1, 2)

        self.assertEqual(analysis.analysed, ["src/a.py", "src/b.py"])

    def test_skipped_files_are_not_analysed(self):
        forge = FakeForge([FileChange("docs/guide.md", "+ text")])
        analysis = RecordingAnalysis()

        _service(forge, ScriptedReviewer(), analysis=analysis).review(1, 2)

        self.assertEqual(analysis.analysed, [])

    def test_auto_approved_files_are_not_analysed(self):
        forge = FakeForge([FileChange("src/app.py", "+# a comment\n")])
        analysis = RecordingAnalysis()

        _service(forge, ScriptedReviewer(), analysis=analysis).review(1, 2)

        self.assertEqual(analysis.analysed, [])

    def test_a_critical_finding_blocks_despite_a_clean_review(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])
        analysis = RecordingAnalysis([_finding(Severity.CRITICAL)])

        result = _service(forge, ScriptedReviewer(CLEAN_REVIEW), analysis=analysis).review(1, 2)

        self.assertTrue(result.outcome.is_blocking)
        self.assertEqual(result.exit_code, 1)

    def test_the_blocking_finding_appears_in_the_comment(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])
        analysis = RecordingAnalysis([_finding(Severity.CRITICAL)])

        _service(forge, ScriptedReviewer(CLEAN_REVIEW), analysis=analysis).review(1, 2)

        self.assertIn("src/app.py:4", forge.published[0])
        self.assertIn("Command Injection", forge.published[0])

    def test_findings_are_summarised_in_the_comment(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])
        analysis = RecordingAnalysis([_finding(Severity.MEDIUM)])

        _service(forge, ScriptedReviewer(), analysis=analysis).review(1, 2)

        self.assertIn("Static analysis", forge.published[0])

    def test_findings_reach_the_result(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])
        analysis = RecordingAnalysis([_finding(Severity.MEDIUM)])

        result = _service(forge, ScriptedReviewer(), analysis=analysis).review(1, 2)

        self.assertEqual(len(result.findings), 1)

    def test_metrics_break_findings_down_by_severity(self):
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])
        analysis = RecordingAnalysis([_finding(Severity.MEDIUM), _finding(Severity.LOW)])

        result = _service(forge, ScriptedReviewer(), analysis=analysis).review(1, 2)

        self.assertEqual(result.metrics[0].findings_by_severity, {"medium": 1, "low": 1})

    def test_without_an_analyser_the_prose_still_decides(self):
        """A caller with no analysis configured is no worse off than before."""
        forge = FakeForge([FileChange("src/app.py", _significant_diff())])

        result = _service(forge, ScriptedReviewer(BLOCKING_REVIEW)).review(1, 2)

        self.assertTrue(result.outcome.is_blocking)


class ExplodingReviewer(Reviewer):
    """Fails on the named files and behaves on the rest."""

    def __init__(self, failing_paths, report=CLEAN_REVIEW):
        self.failing_paths = set(failing_paths)
        self.report = report
        self.reviewed = []

    def review_diff(self, brief):
        if brief.file_path in self.failing_paths:
            raise RuntimeError("model endpoint timed out")
        self.reviewed.append(brief.file_path)
        return self.report


class ExplodingAnalysis(StaticAnalysis):
    def analyze(self, file_path, content, diff=""):
        raise RuntimeError("analyzer crashed")


class TestFailureIsolation(unittest.TestCase):
    """Regression for F-58.

    An exception on one file propagated out of the workflow, so the composition
    root exited 1 and every completed review was discarded — nothing was posted.
    One flaky model call cost the whole run.
    """

    def _three_files(self):
        return FakeForge(
            [
                FileChange("src/a.py", _significant_diff("a")),
                FileChange("src/b.py", _significant_diff("b")),
                FileChange("src/c.py", _significant_diff("c")),
            ]
        )

    def test_the_other_files_are_still_reviewed(self):
        forge = self._three_files()
        reviewer = ExplodingReviewer(["src/b.py"])

        _service(forge, reviewer).review(1, 2)

        self.assertEqual(reviewer.reviewed, ["src/a.py", "src/c.py"])

    def test_a_comment_is_still_posted(self):
        forge = self._three_files()

        _service(forge, ExplodingReviewer(["src/b.py"])).review(1, 2)

        self.assertEqual(len(forge.published), 1)

    def test_the_failed_file_is_named_in_the_comment(self):
        forge = self._three_files()

        _service(forge, ExplodingReviewer(["src/b.py"])).review(1, 2)

        self.assertIn("Could not review", forge.published[0])
        self.assertIn("src/b.py", forge.published[0])

    def test_the_failure_is_recorded_on_the_outcome(self):
        forge = self._three_files()

        result = _service(forge, ExplodingReviewer(["src/b.py"])).review(1, 2)

        self.assertTrue(result.outcome.has_failures)
        self.assertEqual(result.outcome.failed_files[0][0], "src/b.py")

    def test_a_failed_file_is_at_least_a_warning(self):
        """The review has less evidence than it appears to."""
        forge = self._three_files()

        result = _service(forge, ExplodingReviewer(["src/b.py"])).review(1, 2)

        self.assertEqual(result.outcome.result, ReviewGateResult.WARN)

    def test_by_default_a_failure_does_not_fail_the_pipeline(self):
        forge = self._three_files()

        result = _service(forge, ExplodingReviewer(["src/b.py"])).review(1, 2)

        self.assertEqual(result.exit_code, 0)

    def test_policy_can_make_a_failure_fail_the_pipeline(self):
        policy = ReviewPolicy()
        policy.gate.fail_on_review_error = True
        forge = self._three_files()

        result = _service(forge, ExplodingReviewer(["src/b.py"]), policy).review(1, 2)

        self.assertEqual(result.exit_code, 1)

    def test_the_failed_file_counts_as_considered(self):
        forge = self._three_files()

        result = _service(forge, ExplodingReviewer(["src/b.py"])).review(1, 2)

        self.assertEqual(result.outcome.files_considered, 3)

    def test_a_crashing_analyzer_does_not_cost_the_model_review(self):
        forge = FakeForge([FileChange("src/a.py", _significant_diff())])
        reviewer = ScriptedReviewer()

        result = _service(forge, reviewer, analysis=ExplodingAnalysis()).review(1, 2)

        self.assertEqual(reviewer.reviewed, ["src/a.py"])
        self.assertFalse(result.outcome.has_failures)

    def test_every_file_failing_still_posts_a_comment(self):
        forge = self._three_files()

        result = _service(forge, ExplodingReviewer(["src/a.py", "src/b.py", "src/c.py"])).review(1, 2)

        self.assertEqual(len(forge.published), 1)
        self.assertEqual(len(result.outcome.failed_files), 3)


if __name__ == "__main__":
    unittest.main()
