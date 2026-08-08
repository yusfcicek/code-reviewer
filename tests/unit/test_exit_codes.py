"""What the process exits with, and why the difference matters.

"The gate blocked the merge request" and "the agent fell over" both exited `1`,
so no pipeline could tell them apart — and that is exactly the distinction
someone needs before they are willing to set `allow_failure: false`
(finding G-13).

| Code | Meaning |
|---|---|
| 0 | the review ran; the gate did not block |
| 1 | the review ran; the gate blocked |
| 2 | configuration error — the run could not start correctly |
| 3 | runtime error — the run did not complete |

`1` is a *successful* run with a negative verdict. `3` is a run that did not
happen.
"""

import unittest
from unittest.mock import MagicMock, patch

from code_reviewer.__main__ import (
    EXIT_BLOCKED,
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    main,
)
from code_reviewer.errors import ConfigurationError, ForgeError, ReviewError
from code_reviewer.infrastructure.forge.gitlab_client import MissingCredentialsError


class TestTheCodesAreDistinct(unittest.TestCase):
    def test_each_outcome_has_its_own_code(self):
        codes = [EXIT_OK, EXIT_BLOCKED, EXIT_CONFIG_ERROR, EXIT_RUNTIME_ERROR]

        self.assertEqual(len(set(codes)), 4)

    def test_success_is_zero(self):
        self.assertEqual(EXIT_OK, 0)

    def test_a_blocked_gate_is_one(self):
        """Kept at 1 because that is what a pipeline already treats as failure."""
        self.assertEqual(EXIT_BLOCKED, 1)

    def test_configuration_and_runtime_errors_are_not_one(self):
        """The whole point: a crash must not look like a verdict."""
        self.assertNotEqual(EXIT_CONFIG_ERROR, EXIT_BLOCKED)
        self.assertNotEqual(EXIT_RUNTIME_ERROR, EXIT_BLOCKED)


class TestTheErrorHierarchy(unittest.TestCase):
    """The types exist so the exit point can map a category to a code.

    Without them `main()` would be inspecting exception messages, which is the
    same class of mistake as parsing a verdict out of the model's prose.
    """

    def test_every_review_error_shares_a_root(self):
        for error in (ConfigurationError, ForgeError):
            with self.subTest(error=error.__name__):
                self.assertTrue(issubclass(error, ReviewError))

    def test_missing_credentials_is_a_configuration_error(self):
        self.assertTrue(issubclass(MissingCredentialsError, ConfigurationError))

    def test_a_review_error_is_still_an_exception(self):
        self.assertTrue(issubclass(ReviewError, Exception))


class _capture_exit:
    """Records the code `main()` exits with."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _traceback):
        if exc_type is SystemExit:
            self.value = exc.code
            return True
        return False


class TestMainMapsOutcomesToCodes(unittest.TestCase):
    def _exit_code(self, run_result=None, run_error=None):
        with (
            patch("code_reviewer.__main__.configure_logging"),
            patch("code_reviewer.__main__.parse_args") as parse_args,
            patch("code_reviewer.__main__.run") as run,
        ):
            parse_args.return_value = MagicMock(project_id=1, mr_iid=2, log_level="INFO")
            if run_error is not None:
                run.side_effect = run_error
            else:
                run.return_value = run_result

            with _capture_exit() as captured:
                main()

        return captured.value

    def test_a_clean_review_exits_zero(self):
        self.assertEqual(self._exit_code(run_result=EXIT_OK), EXIT_OK)

    def test_a_blocked_review_exits_one(self):
        self.assertEqual(self._exit_code(run_result=EXIT_BLOCKED), EXIT_BLOCKED)

    def test_missing_credentials_exit_two(self):
        code = self._exit_code(run_error=MissingCredentialsError("GITLAB_TOKEN is unset"))

        self.assertEqual(code, EXIT_CONFIG_ERROR)

    def test_a_configuration_error_exits_two(self):
        code = self._exit_code(run_error=ConfigurationError("policy will not load"))

        self.assertEqual(code, EXIT_CONFIG_ERROR)

    def test_an_unloadable_policy_exits_two(self):
        from code_reviewer.infrastructure.config.loader import PolicyLoadError

        code = self._exit_code(run_error=PolicyLoadError("unknown key 'security.blck'"))

        self.assertEqual(code, EXIT_CONFIG_ERROR)

    def test_a_forge_failure_exits_three(self):
        code = self._exit_code(run_error=ForgeError("connection refused"))

        self.assertEqual(code, EXIT_RUNTIME_ERROR)

    def test_an_unexpected_exception_exits_three(self):
        """Not 1. A crash that looks like a verdict is the finding."""
        code = self._exit_code(run_error=RuntimeError("something nobody predicted"))

        self.assertEqual(code, EXIT_RUNTIME_ERROR)

    def test_a_keyboard_interrupt_is_not_reported_as_a_verdict(self):
        code = self._exit_code(run_error=KeyboardInterrupt())

        self.assertEqual(code, EXIT_RUNTIME_ERROR)


class TestMissingIdentifiers(unittest.TestCase):
    def test_a_missing_project_id_is_a_configuration_error(self):
        with (
            patch("code_reviewer.__main__.configure_logging"),
            patch("code_reviewer.__main__.parse_args") as parse_args,
        ):
            parse_args.return_value = MagicMock(project_id=None, mr_iid=2, log_level="INFO")

            with _capture_exit() as captured:
                main()

        self.assertEqual(captured.value, EXIT_CONFIG_ERROR)


if __name__ == "__main__":
    unittest.main()
