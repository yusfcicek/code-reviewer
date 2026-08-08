"""Unit tests for policy loading.

The bundled ``review_policy.yaml`` was never loaded: every candidate path was
relative to the current working directory, so unless a copy happened to sit
next to the process, the agent silently ran on the narrower dataclass defaults
while README claimed the shipped file was the default (finding F-04).
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from code_reviewer.infrastructure.config.loader import (
    PolicyLoadError,
    ReviewPolicyLoader,
    get_default_policy,
    load_policy,
)

#: Present in the shipped YAML but not in the dataclass defaults, so its
#: presence proves which source won.
YAML_ONLY_PATTERN = r"os\.system"


class TestPolicyDefaults(unittest.TestCase):
    def test_dataclass_defaults_do_not_contain_the_yaml_only_pattern(self):
        """Guards the discriminator the other tests rely on."""
        self.assertNotIn(YAML_ONLY_PATTERN, get_default_policy().security.banned_patterns)


class TestBundledPolicyIsTheDefault(unittest.TestCase):
    def test_load_policy_finds_the_packaged_file_from_any_directory(
        self,
    ):
        with _in_temporary_cwd() as cwd:
            self.assertEqual(list(Path(cwd).iterdir()), [])
            policy = load_policy()

        self.assertIn(YAML_ONLY_PATTERN, policy.security.banned_patterns)

    def test_packaged_policy_supplies_secret_patterns(self):
        with _in_temporary_cwd():
            policy = load_policy()

        self.assertIn("aws_access_key", policy.security.secret_patterns)

    def test_explicit_path_wins_over_the_packaged_file(self):
        with _in_temporary_cwd() as cwd:
            custom = Path(cwd) / "custom.yaml"
            custom.write_text(
                "version: '9.9'\nsecurity:\n  banned_patterns:\n    - 'CUSTOM_ONLY'\n",
                encoding="utf-8",
            )
            policy = load_policy(str(custom))

        self.assertEqual(policy.version, "9.9")
        self.assertEqual(policy.security.banned_patterns, ["CUSTOM_ONLY"])

    def test_working_directory_file_wins_over_the_packaged_file(self):
        with _in_temporary_cwd() as cwd:
            (Path(cwd) / "review_policy.yaml").write_text("version: '7.7'\n", encoding="utf-8")
            policy = load_policy()

        self.assertEqual(policy.version, "7.7")

    def test_a_missing_explicit_path_raises(self):
        """Changed in Level 9, deliberately (finding G-10).

        This used to fall through to the packaged policy. The reasoning was
        that a stale `--policy` in a pipeline definition should degrade to the
        shipped rules rather than to no rules at all — but the rules it
        degrades to are not the ones the pipeline asked for, and nothing in
        the output says which set actually ran. Naming a file is a claim that
        it exists; the honest response to a false claim is to say so.
        """
        with _in_temporary_cwd():
            with self.assertRaises(PolicyLoadError):
                load_policy("/nonexistent/policy.yaml")

    def test_unreadable_yaml_raises(self):
        """Also changed in Level 9. Same reasoning: a file that does not parse
        is a configuration nobody can read, and running something else in its
        place is a silent substitution."""
        with _in_temporary_cwd() as cwd:
            broken = Path(cwd) / "broken.yaml"
            broken.write_text("version: '1.0'\n  bad: [indent", encoding="utf-8")

            with self.assertRaises(PolicyLoadError):
                load_policy(str(broken))

    def test_loader_records_which_source_won(self):
        with _in_temporary_cwd():
            loader = ReviewPolicyLoader()
            loader.load()

        self.assertIsNotNone(loader.source)
        self.assertIn("review_policy.yaml", str(loader.source))


class TestEnvironmentOverrides(unittest.TestCase):
    def test_environment_overrides_the_file(self):
        with _in_temporary_cwd():
            with patch.dict(os.environ, {"REVIEW_POLICY_QUALITY_THRESHOLD": "95"}):
                policy = load_policy()

        self.assertEqual(policy.gate.quality_score_threshold, 95)

    def test_invalid_environment_value_is_ignored(self):
        with _in_temporary_cwd():
            with patch.dict(os.environ, {"REVIEW_POLICY_QUALITY_THRESHOLD": "high"}):
                policy = load_policy()

        self.assertEqual(policy.gate.quality_score_threshold, 60)


class _in_temporary_cwd:
    """Runs a block in an empty directory so no stray policy file is picked up."""

    def __enter__(self):
        import tempfile

        self._previous = os.getcwd()
        self._directory = tempfile.TemporaryDirectory()
        os.chdir(self._directory.name)
        return self._directory.name

    def __exit__(self, *exc_info):
        os.chdir(self._previous)
        self._directory.cleanup()
        return False


if __name__ == "__main__":
    unittest.main()
