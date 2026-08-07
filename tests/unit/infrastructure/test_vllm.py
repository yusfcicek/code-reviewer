"""Unit tests for the vLLM provider.

The chat model was constructed with no request timeout and no retry policy. A
hung endpoint hung the pipeline until CI's own timeout killed it, with no
output and no indication of why (finding F-59).
"""

import unittest
from unittest.mock import patch

from code_reviewer.infrastructure.llm.vllm import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    LLMFactory,
    VLLMProvider,
)

BASE_ENV = {
    "VLLM_MODEL": "mistral-7b",
    "VLLM_API_URL": "http://vllm:8000/v1",
    "VLLM_API_KEY": "key",
}


def _chat_model_kwargs(**env):
    with patch.dict("os.environ", {**BASE_ENV, **env}, clear=True):
        with patch("code_reviewer.infrastructure.llm.vllm.ChatOpenAI") as chat_openai:
            VLLMProvider().get_chat_model()
    return chat_openai.call_args.kwargs


class TestConfiguration(unittest.TestCase):
    def test_model_url_and_key_come_from_the_environment(self):
        kwargs = _chat_model_kwargs()

        self.assertEqual(kwargs["model"], "mistral-7b")
        self.assertEqual(kwargs["openai_api_base"], "http://vllm:8000/v1")

    def test_explicit_arguments_win_over_the_environment(self):
        with patch.dict("os.environ", BASE_ENV, clear=True):
            provider = VLLMProvider(model_name="other-model")

        self.assertEqual(provider.model_name, "other-model")


class TestTimeout(unittest.TestCase):
    def test_a_default_timeout_is_applied(self):
        kwargs = _chat_model_kwargs()

        self.assertEqual(kwargs["request_timeout"], DEFAULT_TIMEOUT_SECONDS)

    def test_the_timeout_is_configurable(self):
        kwargs = _chat_model_kwargs(LLM_TIMEOUT_SECONDS="30")

        self.assertEqual(kwargs["request_timeout"], 30.0)

    def test_a_non_numeric_timeout_falls_back_to_the_default(self):
        kwargs = _chat_model_kwargs(LLM_TIMEOUT_SECONDS="soon")

        self.assertEqual(kwargs["request_timeout"], DEFAULT_TIMEOUT_SECONDS)

    def test_a_negative_timeout_falls_back_to_the_default(self):
        kwargs = _chat_model_kwargs(LLM_TIMEOUT_SECONDS="-5")

        self.assertEqual(kwargs["request_timeout"], DEFAULT_TIMEOUT_SECONDS)


class TestRetries(unittest.TestCase):
    def test_a_default_retry_budget_is_applied(self):
        kwargs = _chat_model_kwargs()

        self.assertEqual(kwargs["max_retries"], DEFAULT_MAX_RETRIES)

    def test_the_retry_budget_is_configurable(self):
        kwargs = _chat_model_kwargs(LLM_MAX_RETRIES="5")

        self.assertEqual(kwargs["max_retries"], 5)

    def test_retries_can_be_switched_off(self):
        kwargs = _chat_model_kwargs(LLM_MAX_RETRIES="0")

        self.assertEqual(kwargs["max_retries"], 0)

    def test_a_non_numeric_retry_budget_falls_back(self):
        kwargs = _chat_model_kwargs(LLM_MAX_RETRIES="many")

        self.assertEqual(kwargs["max_retries"], DEFAULT_MAX_RETRIES)


class TestTemperature(unittest.TestCase):
    def test_temperature_is_configurable(self):
        kwargs = _chat_model_kwargs(LLM_TEMPERATURE="0.1")

        self.assertEqual(kwargs["temperature"], 0.1)

    def test_a_default_temperature_is_applied(self):
        kwargs = _chat_model_kwargs()

        self.assertIsInstance(kwargs["temperature"], float)


class TestFactory(unittest.TestCase):
    def test_vllm_is_the_known_provider(self):
        with patch.dict("os.environ", BASE_ENV, clear=True):
            self.assertIsInstance(LLMFactory.create_provider("vllm"), VLLMProvider)

    def test_the_provider_name_is_case_insensitive(self):
        with patch.dict("os.environ", BASE_ENV, clear=True):
            self.assertIsInstance(LLMFactory.create_provider("VLLM"), VLLMProvider)

    def test_an_unknown_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            LLMFactory.create_provider("telepathy")


if __name__ == "__main__":
    unittest.main()
