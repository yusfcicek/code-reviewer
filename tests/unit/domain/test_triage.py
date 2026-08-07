"""Unit tests for review triage.

Triage exists to avoid paying for a model call on changes that do not warrant
one. Matching security patterns against the *whole diff* — including unchanged
context and removed lines — escalated files to CRITICAL because of code the
change did not touch, which is the opposite of what triage is for (F-09).
"""

import unittest

from code_reviewer.infrastructure.config.loader import ReviewPolicy
from code_reviewer.domain.triage import ReviewDecision, ReviewTriage


class TestSkipRules(unittest.TestCase):
    def setUp(self):
        self.triage = ReviewTriage(ReviewPolicy())

    def test_markdown_is_skipped(self):
        result = self.triage.decide("+ new paragraph\n", "docs/guide.md")

        self.assertIs(result.decision, ReviewDecision.SKIP)

    def test_source_file_is_not_skipped(self):
        result = self.triage.decide("+ value = compute()\n", "src/app.py")

        self.assertIsNot(result.decision, ReviewDecision.SKIP)


class TestSecurityEscalation(unittest.TestCase):
    def setUp(self):
        self.triage = ReviewTriage(ReviewPolicy())

    def test_added_secret_escalates_to_critical(self):
        diff = "@@ -1,3 +1,4 @@\n context line\n+password = \"hunter22\"\n context line\n"

        result = self.triage.decide(diff, "src/app.py")

        self.assertIs(result.decision, ReviewDecision.CRITICAL)

    def test_secret_in_unchanged_context_does_not_escalate(self):
        """Regression for F-09."""
        diff = (
            "@@ -1,4 +1,4 @@\n"
            " password = \"hunter22\"\n"
            "-timeout = 10\n"
            "+timeout = 30\n"
            " done = True\n"
        )

        result = self.triage.decide(diff, "src/app.py")

        self.assertIsNot(result.decision, ReviewDecision.CRITICAL)

    def test_removing_a_dangerous_call_does_not_escalate(self):
        """Deleting `eval(...)` improves the file; it should not be blocked."""
        diff = "@@ -1,3 +1,2 @@\n context\n-result = eval(payload)\n context\n"

        result = self.triage.decide(diff, "src/app.py")

        self.assertIsNot(result.decision, ReviewDecision.CRITICAL)

    def test_adding_a_dangerous_call_escalates(self):
        diff = "@@ -1,2 +1,3 @@\n context\n+result = eval(payload)\n context\n"

        result = self.triage.decide(diff, "src/app.py")

        self.assertIs(result.decision, ReviewDecision.CRITICAL)
        self.assertTrue(result.should_notify)


class TestApiChangeEscalation(unittest.TestCase):
    def setUp(self):
        self.triage = ReviewTriage(ReviewPolicy())

    def test_removed_public_function_escalates(self):
        diff = "@@ -1,4 +1,2 @@\n-def public_api(value):\n-    return value\n"

        result = self.triage.decide(diff, "src/app.py")

        self.assertIs(result.decision, ReviewDecision.CRITICAL)

    def test_added_function_does_not_escalate_as_an_api_removal(self):
        diff = "+def brand_new(value):\n+    return value\n"

        result = self.triage.decide(diff, "src/app.py")

        self.assertIsNot(result.decision, ReviewDecision.CRITICAL)


class TestAutoApproval(unittest.TestCase):
    def setUp(self):
        self.triage = ReviewTriage(ReviewPolicy())

    def test_comment_only_change_is_auto_approved(self):
        diff = "@@ -1,1 +1,2 @@\n+# explain the retry budget\n"

        result = self.triage.decide(diff, "src/app.py")

        self.assertIs(result.decision, ReviewDecision.AUTO_APPROVE)

    def test_formatting_only_change_is_auto_approved(self):
        diff = "-value=compute( x )\n+value = compute(x)\n"

        result = self.triage.decide(diff, "src/app.py")

        self.assertIs(result.decision, ReviewDecision.AUTO_APPROVE)


class TestSizeBasedDecisions(unittest.TestCase):
    def setUp(self):
        self.triage = ReviewTriage(ReviewPolicy())

    def test_moderate_change_gets_a_quick_scan(self):
        diff = "\n".join(f"+    step_{i} = run({i})" for i in range(20))

        result = self.triage.decide(diff, "src/app.py")

        self.assertIs(result.decision, ReviewDecision.QUICK_SCAN)

    def test_large_change_gets_a_full_review(self):
        diff = "\n".join(f"+    step_{i} = run({i})" for i in range(80))

        result = self.triage.decide(diff, "src/app.py")

        self.assertIs(result.decision, ReviewDecision.FULL_REVIEW)

    def test_test_files_get_a_quick_scan(self):
        diff = "\n".join(f"+    assert run({i}) == {i}" for i in range(20))

        result = self.triage.decide(diff, "tests/test_app.py")

        self.assertIs(result.decision, ReviewDecision.QUICK_SCAN)


class TestBatchSummary(unittest.TestCase):
    def test_summary_counts_each_decision(self):
        triage = ReviewTriage(ReviewPolicy())
        results = triage.batch_decide([
            {"new_path": "docs/a.md", "diff": "+text"},
            {"new_path": "src/app.py", "diff": "+password = \"hunter22\""},
        ])

        summary = triage.get_review_summary(results)

        self.assertIn("**SKIP** (trivial): 1", summary)
        self.assertIn("**CRITICAL** (blocking): 1", summary)


if __name__ == "__main__":
    unittest.main()
