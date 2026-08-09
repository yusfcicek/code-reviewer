"""Step 6 — what it takes to start serving."""

import os
import unittest
from unittest.mock import MagicMock, patch

import pytest

from code_reviewer.application.jobs import DEFAULT_QUEUE_DEPTH
from code_reviewer.errors import ConfigurationError
from code_reviewer.infrastructure.http.app import ReviewApi
from code_reviewer.infrastructure.http.worker import ReviewWorker
from code_reviewer.serve import EXIT_CONFIGURATION, build_application, build_parser, main


def _args(*argv):
    return build_parser().parse_args(list(argv))


class TestConfiguration(unittest.TestCase):
    def test_the_service_refuses_to_start_without_a_token(self):
        """Serving unauthenticated because a variable was unset is the failure
        that gets found by somebody else."""
        with patch.dict(os.environ, {"REVIEW_API_TOKEN": ""}, clear=False):
            with self.assertRaises(ConfigurationError) as error:
                build_application(_args(), review_service=MagicMock())

        self.assertIn("REVIEW_API_TOKEN", str(error.exception))

    def test_main_exits_two_without_a_token(self):
        with patch.dict(os.environ, {"REVIEW_API_TOKEN": ""}, clear=False):
            self.assertEqual(main([]), EXIT_CONFIGURATION)

    def test_a_missing_webhook_secret_warns_but_starts(self):
        """A deployment may want the API without the webhook. The endpoint
        itself then refuses everything, which is the safe reading."""
        with patch.dict(os.environ, {"REVIEW_API_TOKEN": "t", "GITLAB_WEBHOOK_SECRET": ""}, clear=False):
            with self.assertLogs("code_reviewer.serve", level="WARNING") as captured:
                application, _, _ = build_application(_args(), review_service=MagicMock())

        self.assertIsInstance(application, ReviewApi)
        self.assertTrue(any("GITLAB_WEBHOOK_SECRET" in line for line in captured.output))


class TestWhatIsBuilt(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {"REVIEW_API_TOKEN": "token", "GITLAB_WEBHOOK_SECRET": "hook"},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_an_application_a_worker_and_a_queue(self):
        application, worker, jobs = build_application(_args(), review_service=MagicMock())

        self.assertIsInstance(application, ReviewApi)
        self.assertIsInstance(worker, ReviewWorker)
        self.assertEqual(jobs.max_queue_depth, DEFAULT_QUEUE_DEPTH)

    def test_the_queue_depth_is_configurable(self):
        _, _, jobs = build_application(_args("--queue-depth", "3"), review_service=MagicMock())

        self.assertEqual(jobs.max_queue_depth, 3)

    def test_building_starts_nothing(self):
        """A builder that starts a thread cannot be called by a test."""
        _, worker, _ = build_application(_args(), review_service=MagicMock())

        self.assertIsNone(worker._thread)

    def test_the_defaults_are_a_loopback_address(self):
        """Not 0.0.0.0: a service that binds every interface by default is one
        that gets exposed by accident. A container publishes it deliberately."""
        self.assertEqual(_args().host, "127.0.0.1")
        self.assertEqual(_args().port, 8080)


class TestArguments(unittest.TestCase):
    def test_host_and_port_are_configurable(self):
        args = _args("--host", "0.0.0.0", "--port", "9000")  # noqa: S104 - the point of the test

        self.assertEqual(args.host, "0.0.0.0")  # noqa: S104
        self.assertEqual(args.port, 9000)

    def test_a_queue_depth_below_one_is_refused(self):
        with pytest.raises(SystemExit):
            _args("--queue-depth", "0")

    def test_the_environment_supplies_defaults(self):
        with patch.dict(os.environ, {"REVIEW_PORT": "9999", "REVIEW_QUEUE_DEPTH": "5"}, clear=False):
            args = build_parser().parse_args([])

        self.assertEqual(args.port, 9999)
        self.assertEqual(args.queue_depth, 5)


if __name__ == "__main__":
    unittest.main()
