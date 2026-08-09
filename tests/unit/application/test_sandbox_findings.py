"""A refused file access is a finding, not a footnote.

The paths the agent asks for come from the diff. So when the agent is refused
`/etc/passwd`, that is not a fact about the model having a bad day — it is
evidence that the merge request under review contains an injection, and it is
the loudest such evidence available.

Routing it through `Finding` rather than through the review prose is what puts
it in front of the gate. Prose warns; findings block (ADR 0004). An injection
attempt should be able to fail a pipeline.
"""

import unittest

from code_reviewer.application.ports import (
    AccessAuditor,
    AccessViolation,
    CodeForge,
    FileChange,
    MergeRequestRef,
    Reviewer,
    StaticAnalysis,
)
from code_reviewer.application.review_service import ReviewService
from code_reviewer.domain.finding import FindingCategory
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import SuppressionResult
from code_reviewer.domain.triage import ReviewTriage

DIFF = "\n".join(f"+ line {n}" for n in range(60))


class _Forge(CodeForge):
    def fetch_merge_request(self, project_id, merge_request_iid):
        return MergeRequestRef(project_id=str(project_id), merge_request_id=str(merge_request_iid))

    def fetch_changes(self, reference):
        return [
            FileChange(path="src/a.py", diff=DIFF),
            FileChange(path="src/b.py", diff=DIFF),
        ]

    def fetch_file(self, reference, path):
        return "value = 1\n"

    def publish_comment(self, reference, body):
        self.published = body


class _Reviewer(Reviewer):
    """A reviewer that can be told to trip the sandbox while it works."""

    def __init__(self, auditor=None, trip_on=()):
        self.auditor = auditor
        self.trip_on = set(trip_on)

    def review_diff(
        self,
        filename,
        diff_content,
        full_file_content=None,
        other_files=None,
        related=None,
        recollections=None,
    ):
        if filename in self.trip_on and self.auditor is not None:
            self.auditor.record(filename)
        return "# Review\nLooks fine."


class _NoFindings(StaticAnalysis):
    def analyze(self, file_path, content, diff=""):
        return SuppressionResult()


class _Auditor(AccessAuditor):
    """Accumulates refusals the way a Workspace does — never clearing them."""

    def __init__(self):
        self._violations: list[AccessViolation] = []

    def record(self, triggered_by: str) -> None:
        self._violations.append(
            AccessViolation(path="/etc/passwd", reason=f"outside the workspace (during {triggered_by})")
        )

    def access_violations(self):
        return list(self._violations)


def _service(reviewer, auditor=None, policy=None):
    policy = policy or ReviewPolicy()
    return ReviewService(
        forge=_Forge(),
        reviewer=reviewer,
        triage=ReviewTriage(policy),
        policy=policy,
        analysis=_NoFindings(),
        access_auditor=auditor,
    )


class TestViolationsBecomeFindings(unittest.TestCase):
    def setUp(self):
        self.auditor = _Auditor()
        self.reviewer = _Reviewer(self.auditor, trip_on=["src/a.py"])
        self.result = _service(self.reviewer, self.auditor).review(1, 2)

    def test_a_refusal_produces_a_finding(self):
        self.assertEqual(len(self.result.findings), 1)

    def test_the_finding_is_a_critical_security_finding(self):
        finding = self.result.findings[0]

        self.assertEqual(finding.category, FindingCategory.SECURITY)
        self.assertEqual(finding.severity, Severity.CRITICAL)

    def test_the_finding_names_the_path_that_was_refused(self):
        self.assertIn("/etc/passwd", self.result.findings[0].description)

    def test_the_rule_id_is_namespaced(self):
        """A bare id gives a suppression glob nothing to match (G-08)."""
        finding = self.result.findings[0]

        self.assertEqual(finding.rule_id, "SANDBOX.VIOLATION")
        self.assertEqual(finding.namespace, "SANDBOX")

    def test_the_finding_is_attributed_to_the_file_under_review(self):
        """It is evidence about that file's diff, which is where it came from."""
        self.assertEqual(self.result.findings[0].file_path, "src/a.py")

    def test_a_violation_is_not_re_attributed_to_the_next_file(self):
        """The auditor accumulates; only what is new belongs to this file."""
        attributed = [f.file_path for f in self.result.findings]

        self.assertEqual(attributed, ["src/a.py"])

    def test_the_finding_blocks_the_pipeline(self):
        self.assertTrue(self.result.outcome.is_blocking)
        self.assertEqual(self.result.exit_code, 1)

    def test_the_report_names_the_refusal(self):
        self.assertIn("/etc/passwd", self.result.comment)


class TestWithoutViolations(unittest.TestCase):
    def test_a_clean_review_produces_no_sandbox_finding(self):
        auditor = _Auditor()

        result = _service(_Reviewer(auditor), auditor).review(1, 2)

        self.assertEqual(result.findings, [])
        self.assertFalse(result.outcome.is_blocking)

    def test_no_auditor_leaves_the_workflow_unchanged(self):
        """The auditor is optional: a caller without a sandbox still reviews."""
        result = _service(_Reviewer(), auditor=None).review(1, 2)

        self.assertEqual(result.findings, [])
        self.assertFalse(result.outcome.is_blocking)


class TestEveryFileIsAccountedFor(unittest.TestCase):
    def test_a_violation_during_the_second_file_lands_on_the_second_file(self):
        auditor = _Auditor()
        reviewer = _Reviewer(auditor, trip_on=["src/b.py"])

        result = _service(reviewer, auditor).review(1, 2)

        self.assertEqual([f.file_path for f in result.findings], ["src/b.py"])

    def test_violations_during_both_files_produce_one_finding_each(self):
        auditor = _Auditor()
        reviewer = _Reviewer(auditor, trip_on=["src/a.py", "src/b.py"])

        result = _service(reviewer, auditor).review(1, 2)

        self.assertEqual([f.file_path for f in result.findings], ["src/a.py", "src/b.py"])


if __name__ == "__main__":
    unittest.main()
