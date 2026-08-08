"""Masking secrets on the way out.

The agent reads files and quotes them, and its output goes to two places that
are hard to take back: the CI log and a merge-request comment. Deleting the
comment does not help — by then the text is in the notification emails and the
webhook history (finding G-04).

Two layers, and the order matters (decision D-1). Values from the process
environment go first, because that layer has no false negatives: if this
process holds the token, any appearance of it is caught however the model
mangled the surrounding text. Shape matching is the fallback for secrets this
process does not hold, and it is the layer that will miss things.
"""

import unittest
from unittest.mock import patch

from code_reviewer.infrastructure.security.redaction import MASK, SecretRedactor


class TestEnvironmentValues(unittest.TestCase):
    """The layer that cannot produce a false negative."""

    def test_a_known_secret_value_is_masked(self):
        redactor = SecretRedactor(values=["glpat-verysecretvalue"])

        result = redactor.redact("The token is glpat-verysecretvalue, apparently.")

        self.assertNotIn("glpat-verysecretvalue", result)
        self.assertIn(MASK, result)

    def test_it_is_masked_wherever_it_appears(self):
        """Shape does not matter here — the value is the value."""
        redactor = SecretRedactor(values=["s3cr3t-token-value"])

        result = redactor.redact("json:{'k':'s3cr3t-token-value'} yaml: s3cr3t-token-value")

        self.assertNotIn("s3cr3t-token-value", result)
        self.assertEqual(result.count(MASK), 2)

    def test_a_short_value_is_left_alone(self):
        """Masking every 'test' in a review would shred it (decision D-2)."""
        redactor = SecretRedactor(values=["abc"])

        self.assertIn("abc", redactor.redact("The abc module is fine."))

    def test_an_empty_value_is_ignored(self):
        redactor = SecretRedactor(values=["", None])  # type: ignore[list-item]

        self.assertEqual(redactor.redact("unchanged text"), "unchanged text")

    def test_a_longer_value_is_masked_before_a_shorter_one_it_contains(self):
        """Otherwise the prefix is masked and the rest of the secret survives."""
        redactor = SecretRedactor(values=["prefix-secret", "prefix-secret-longer"])

        result = redactor.redact("value: prefix-secret-longer")

        self.assertNotIn("longer", result)

    def test_values_are_read_from_the_environment(self):
        with patch.dict("os.environ", {"GITLAB_TOKEN": "glpat-fromtheenvironment"}, clear=False):
            redactor = SecretRedactor.from_environment()

        self.assertNotIn("glpat-fromtheenvironment", redactor.redact("t=glpat-fromtheenvironment"))


class TestSecretShapes(unittest.TestCase):
    """The fallback for secrets this process does not hold."""

    def setUp(self):
        self.redactor = SecretRedactor()

    def test_a_private_key_block_is_masked_whole(self):
        text = (
            "Found this:\n-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA1234\nabcd\n-----END RSA PRIVATE KEY-----\ndone."
        )

        result = self.redactor.redact(text)

        self.assertNotIn("MIIEpAIBAAKCAQEA1234", result)
        self.assertIn("done.", result)

    def test_cloud_and_platform_tokens_are_masked(self):
        cases = {
            "aws access key": "AKIAIOSFODNN7EXAMPLE",
            "aws session key": "ASIAIOSFODNN7EXAMPLE",
            "gitlab pat": "glpat-abcdefghijklmnopqrstu",
            "github pat": "ghp_abcdefghijklmnopqrstuvwxyz0123",
            "openai key": "sk-abcdefghijklmnopqrstuvwxyz0123",
            "slack token": "xoxb-1234567890-abcdefghij",
        }

        for name, secret in cases.items():
            with self.subTest(kind=name):
                self.assertNotIn(secret, self.redactor.redact(f"key = {secret}"))

    def test_a_bearer_credential_is_masked_but_the_header_survives(self):
        result = self.redactor.redact("Authorization: Bearer abcdefghijklmnop123456")

        self.assertIn("Authorization", result)
        self.assertIn("Bearer", result)
        self.assertNotIn("abcdefghijklmnop123456", result)

    def test_an_assignment_masks_the_value_not_the_name(self):
        result = self.redactor.redact('api_key = "s3cr3tvalue123"')

        self.assertIn("api_key", result)
        self.assertNotIn("s3cr3tvalue123", result)

    def test_an_uppercase_environment_assignment_is_masked(self):
        result = self.redactor.redact("DATABASE_PASSWORD=hunter2hunter2")

        self.assertIn("DATABASE_PASSWORD", result)
        self.assertNotIn("hunter2hunter2", result)

    def test_a_placeholder_assignment_is_left_alone(self):
        """`password = "x"` in an example is not a secret."""
        self.assertIn('"x"', self.redactor.redact('password = "x"'))


class TestOrdinaryProseSurvives(unittest.TestCase):
    """A redactor that mangles reviews gets turned off, and then it protects nothing."""

    def test_a_normal_review_is_unchanged(self):
        text = (
            "# Architectural Review Summary\n"
            "The change adds a retry to `fetch_user`. Risk Assessment: Low.\n"
            "Consider extracting the token-refresh branch into its own function.\n"
        )

        self.assertEqual(SecretRedactor().redact(text), text)

    def test_the_word_secret_alone_is_not_masked(self):
        text = "This module handles secret rotation."

        self.assertEqual(SecretRedactor().redact(text), text)

    def test_code_without_credentials_is_unchanged(self):
        text = "def handle(request):\n    return request.user.id\n"

        self.assertEqual(SecretRedactor().redact(text), text)


class TestReporting(unittest.TestCase):
    def test_the_number_of_masked_spans_is_reported(self):
        redactor = SecretRedactor(values=["glpat-onesecretvalue"])

        report = redactor.redact_with_report("a glpat-onesecretvalue b glpat-onesecretvalue")

        self.assertEqual(report.count, 2)

    def test_a_clean_text_reports_nothing_masked(self):
        self.assertEqual(SecretRedactor().redact_with_report("all fine").count, 0)

    def test_empty_input_is_handled(self):
        report = SecretRedactor().redact_with_report("")

        self.assertEqual(report.text, "")
        self.assertEqual(report.count, 0)


if __name__ == "__main__":
    unittest.main()
