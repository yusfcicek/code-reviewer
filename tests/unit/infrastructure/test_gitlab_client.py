"""Unit tests for the GitLab client factory.

The client used to be constructed with ``ssl_verify=False`` hard-coded, which
disables certificate verification for every API call — including the one that
carries ``GITLAB_TOKEN``. The project's own SAST analyzer flags exactly this
pattern as HIGH severity, CWE-295 (finding F-20).
"""

import unittest
from unittest.mock import patch

from code_reviewer.infrastructure.forge.gitlab_client import (
    MissingCredentialsError,
    build_gitlab_client,
)


class TestBuildGitLabClient(unittest.TestCase):
    def setUp(self):
        self.env = {
            "GITLAB_URL": "https://gitlab.example.com",
            "GITLAB_TOKEN": "s3cret",
        }

    def _build(self, **overrides):
        env = {**self.env, **overrides}
        with patch.dict("os.environ", env, clear=True):
            with patch("code_reviewer.infrastructure.forge.gitlab_client.gitlab.Gitlab") as gitlab_cls:
                build_gitlab_client()
        return gitlab_cls.call_args

    def test_tls_verification_is_on_by_default(self):
        call = self._build()

        self.assertIs(call.kwargs["ssl_verify"], True)

    def test_url_and_token_are_passed_through(self):
        call = self._build()

        self.assertEqual(call.args[0], "https://gitlab.example.com")
        self.assertEqual(call.kwargs["private_token"], "s3cret")

    def test_verification_can_be_disabled_only_explicitly(self):
        call = self._build(GITLAB_SSL_VERIFY="false")

        self.assertIs(call.kwargs["ssl_verify"], False)

    def test_disabling_verification_warns(self):
        env = {**self.env, "GITLAB_SSL_VERIFY": "false"}
        with patch.dict("os.environ", env, clear=True):
            with patch("code_reviewer.infrastructure.forge.gitlab_client.gitlab.Gitlab"):
                with self.assertWarns(UserWarning):
                    build_gitlab_client()

    def test_a_custom_ca_bundle_is_used_as_the_verify_target(self):
        call = self._build(GITLAB_CA_BUNDLE="/etc/ssl/corp-ca.pem")

        self.assertEqual(call.kwargs["ssl_verify"], "/etc/ssl/corp-ca.pem")

    def test_unrecognised_verify_value_keeps_verification_on(self):
        """An unparseable setting must fail safe, not fail open."""
        call = self._build(GITLAB_SSL_VERIFY="maybe")

        self.assertIs(call.kwargs["ssl_verify"], True)

    def test_missing_token_is_an_error_not_a_warning(self):
        env = {"GITLAB_URL": "https://gitlab.example.com"}
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(MissingCredentialsError):
                build_gitlab_client()

    def test_missing_url_is_an_error(self):
        env = {"GITLAB_TOKEN": "s3cret"}
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(MissingCredentialsError):
                build_gitlab_client()


if __name__ == "__main__":
    unittest.main()
