"""Unit tests for command-line argument handling.

``--project-id`` and ``--mr-iid`` were declared ``type=int`` with an
environment-variable default. argparse applies ``type`` to command-line strings
but not to defaults, so the same program produced ints when invoked by hand and
strings when invoked by CI (finding F-15).
"""

import unittest
from unittest.mock import patch

from code_reviewer.cli import parse_args


class TestParseArgs(unittest.TestCase):
    def _parse(self, argv, env=None):
        with patch.dict("os.environ", env or {}, clear=True):
            return parse_args(argv)

    def test_command_line_values_are_integers(self):
        args = self._parse(["--project-id", "7", "--mr-iid", "12"])

        self.assertEqual(args.project_id, 7)
        self.assertEqual(args.mr_iid, 12)

    def test_environment_values_are_integers_too(self):
        args = self._parse([], env={"CI_PROJECT_ID": "42", "CI_MERGE_REQUEST_IID": "9"})

        self.assertEqual(args.project_id, 42)
        self.assertEqual(args.mr_iid, 9)
        self.assertIsInstance(args.project_id, int)
        self.assertIsInstance(args.mr_iid, int)

    def test_command_line_overrides_the_environment(self):
        args = self._parse(["--project-id", "7"], env={"CI_PROJECT_ID": "42"})

        self.assertEqual(args.project_id, 7)

    def test_non_numeric_environment_value_is_rejected(self):
        with self.assertRaises(SystemExit):
            self._parse([], env={"CI_PROJECT_ID": "not-a-number"})

    def test_missing_identifiers_are_none(self):
        args = self._parse([])

        self.assertIsNone(args.project_id)
        self.assertIsNone(args.mr_iid)

    def test_policy_path_defaults_to_none(self):
        args = self._parse([])

        self.assertIsNone(args.policy)

    def test_policy_path_is_accepted(self):
        args = self._parse(["--policy", "custom.yaml"])

        self.assertEqual(args.policy, "custom.yaml")


if __name__ == "__main__":
    unittest.main()


class TestAuditPath(unittest.TestCase):
    """Level 20 — where the decision record goes.

    Settable through the environment because the HTTP service builds its
    review from the review parser's *defaults*: a container is configured with
    variables, not with a command line it never sees.
    """

    def _parse(self, argv, env=None):
        with patch.dict("os.environ", env or {}, clear=True):
            return parse_args(argv)

    def test_the_environment_supplies_it(self):
        args = self._parse([], env={"REVIEW_AUDIT_PATH": "/var/audit/decisions.jsonl"})

        self.assertEqual(args.audit_path, "/var/audit/decisions.jsonl")

    def test_the_command_line_wins(self):
        args = self._parse(
            ["--audit-path", "/tmp/here.jsonl"], env={"REVIEW_AUDIT_PATH": "/var/there.jsonl"}
        )

        self.assertEqual(args.audit_path, "/tmp/here.jsonl")

    def test_it_defaults_to_nothing(self):
        self.assertEqual(self._parse([]).audit_path, "")
