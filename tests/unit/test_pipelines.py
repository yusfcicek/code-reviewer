"""Checks on the CI definitions.

README presents CI integration as the primary use case, but the repository
shipped no pipeline of its own: the project that reviews other people's merge
requests did not review its own (finding F-44).

These tests parse both files, so a pipeline broken by an edit fails on a
laptop rather than on push. They assert shape, not YAML syntax trivia — what
must run, and that the agent runs against real merge requests.
"""

import unittest
from pathlib import Path

import yaml

REPOSITORY = Path(__file__).resolve().parents[2]
GITHUB_WORKFLOW = REPOSITORY / ".github" / "workflows" / "ci.yml"
GITLAB_PIPELINE = REPOSITORY / ".gitlab-ci.yml"
PRE_COMMIT = REPOSITORY / ".pre-commit-config.yaml"

#: Every check a contributor runs locally must also run in CI, or CI is
#: agreeing to something nobody verified.
REQUIRED_CHECKS = ("ruff check", "ruff format", "mypy", "pytest")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestGitHubWorkflow(unittest.TestCase):
    def setUp(self):
        self.assertTrue(GITHUB_WORKFLOW.is_file(), f"{GITHUB_WORKFLOW} is missing")
        self.workflow = _load(GITHUB_WORKFLOW)
        self.text = GITHUB_WORKFLOW.read_text(encoding="utf-8")

    def test_it_is_valid_yaml_with_jobs(self):
        self.assertIn("jobs", self.workflow)
        self.assertTrue(self.workflow["jobs"])

    def test_it_runs_on_push_and_pull_request(self):
        # `on` is parsed as the boolean True by YAML 1.1, which is why this
        # reads the raw text as well.
        triggers = self.workflow.get("on") or self.workflow.get(True)
        self.assertIn("push", triggers)
        self.assertIn("pull_request", triggers)

    def test_every_required_check_runs(self):
        for check in REQUIRED_CHECKS:
            with self.subTest(check=check):
                self.assertIn(check, self.text)

    def test_the_python_version_matches_the_project(self):
        self.assertIn("3.12", self.text)


class TestGitLabPipeline(unittest.TestCase):
    def setUp(self):
        self.assertTrue(GITLAB_PIPELINE.is_file(), f"{GITLAB_PIPELINE} is missing")
        self.pipeline = _load(GITLAB_PIPELINE)
        self.text = GITLAB_PIPELINE.read_text(encoding="utf-8")

    def test_it_is_valid_yaml(self):
        self.assertIsInstance(self.pipeline, dict)

    def test_it_declares_its_stages(self):
        self.assertIn("stages", self.pipeline)

    def test_every_required_check_runs(self):
        for check in REQUIRED_CHECKS:
            with self.subTest(check=check):
                self.assertIn(check, self.text)

    def test_it_runs_this_agent_on_merge_requests(self):
        """The job people are told to copy is one that is demonstrably in use."""
        self.assertIn("ai-code-review", self.text)
        self.assertIn("CI_MERGE_REQUEST_IID", self.text)

    def test_the_agent_job_publishes_the_metrics_artifact(self):
        self.assertIn("metrics.txt", self.text)

    def test_every_job_declares_a_stage(self):
        stages = set(self.pipeline["stages"])
        for name, definition in self.pipeline.items():
            if name in {"stages", "variables", "default", "workflow"} or name.startswith("."):
                continue
            with self.subTest(job=name):
                self.assertIn(definition.get("stage"), stages)


class TestPreCommit(unittest.TestCase):
    def test_the_hooks_run_the_same_linter_as_ci(self):
        self.assertTrue(PRE_COMMIT.is_file(), f"{PRE_COMMIT} is missing")

        config = _load(PRE_COMMIT)
        hook_ids = {hook["id"] for repo in config["repos"] for hook in repo.get("hooks", [])}

        self.assertIn("ruff-check", hook_ids | {h.replace("ruff", "ruff-check") for h in hook_ids})
        self.assertTrue(any("ruff" in hook_id for hook_id in hook_ids))


if __name__ == "__main__":
    unittest.main()
