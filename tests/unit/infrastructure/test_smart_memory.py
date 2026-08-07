"""Unit tests for SmartMemoryStrategy."""

import unittest
from unittest.mock import MagicMock

from code_reviewer.application.ports import LLMProvider
from code_reviewer.infrastructure.memory.smart_memory import InsightPriority, SmartMemoryStrategy


class MockLLMProvider(LLMProvider):
    def __init__(self):
        self.model = MagicMock()

    def get_chat_model(self):
        return self.model


class TestSmartMemoryStrategy(unittest.TestCase):
    def setUp(self):
        self.provider = MockLLMProvider()
        # A small budget so summarisation can be triggered deterministically.
        self.strategy = SmartMemoryStrategy(self.provider, max_tokens=100)

    def test_initialization(self):
        self.assertEqual(self.strategy.max_tokens, 100)
        self.assertEqual(self.strategy.total_tokens_used, 0)
        self.assertEqual(len(self.strategy.critical_insights), 0)

    def test_log_insight_priority(self):
        self.strategy.log_insight("[SECURITY] SQL Injection found")
        self.assertEqual(len(self.strategy.critical_insights), 1)
        self.assertEqual(self.strategy.critical_insights[0].priority, InsightPriority.CRITICAL)

        self.strategy.log_insight("[RISK] Architecture violation")
        self.assertEqual(len(self.strategy.high_insights), 1)
        self.assertEqual(self.strategy.high_insights[0].priority, InsightPriority.HIGH)

        self.strategy.log_insight("[QUALITY] Code smell")
        self.assertEqual(len(self.strategy.normal_insights), 1)
        self.assertEqual(self.strategy.normal_insights[0].priority, InsightPriority.NORMAL)

        self.strategy.log_insight("[TODO] Add comments")
        self.assertEqual(len(self.strategy.low_insights), 1)
        self.assertEqual(self.strategy.low_insights[0].priority, InsightPriority.LOW)

    def test_add_affected_code(self):
        self.strategy.add_affected_code("src/api.py", "process_data", "Data structure change")

        self.assertEqual(len(self.strategy.affected_codes), 1)
        entry = self.strategy.affected_codes[0]
        self.assertEqual(entry.file_path, "src/api.py")
        self.assertEqual(entry.symbol_name, "process_data")

        self.assertEqual(len(self.strategy.high_insights), 1)
        self.assertIn("[AFFECTED_CODE]", self.strategy.high_insights[0].content)

    def test_load_context_content(self):
        self.strategy.log_insight("[SECURITY] Critical Issue")
        context = self.strategy.load_context()
        self.assertIn("CRITICAL", context)
        self.assertIn("Critical Issue", context)

    def test_summarization_compresses_low_priority_first(self):
        """Crossing the threshold must shrink the low-priority bucket and move
        its content into the summary buffer.

        The previous version of this test ended in ``if …: pass else: pass``:
        it asserted nothing and passed regardless of whether summarisation
        happened at all (finding F-36).
        """
        for i in range(10):
            self.strategy.log_insight(f"[TODO] Low priority insight {i} " + "A" * 50)

        self.assertGreater(self.strategy.total_tokens_used, 80)  # > 80 % of 100
        self.assertEqual(self.strategy.summary_buffer, "")

        summarized = self.strategy.summarize_if_needed()

        self.assertTrue(summarized)
        self.assertLess(len(self.strategy.low_insights), 10)
        self.assertNotEqual(self.strategy.summary_buffer, "")
        self.assertEqual(self.strategy.summarization_count, 1)

    def test_summarization_never_discards_critical_insights(self):
        for i in range(10):
            self.strategy.log_insight(f"[SECURITY] Vulnerability {i} " + "A" * 50)

        self.strategy.summarize_if_needed()

        self.assertEqual(len(self.strategy.critical_insights), 10)

    def test_below_threshold_does_not_summarize(self):
        self.strategy.log_insight("[TODO] Small note")

        self.assertFalse(self.strategy.summarize_if_needed())
        self.assertEqual(self.strategy.summary_buffer, "")

    def test_duplicates(self):
        self.strategy.log_insight("[SECURITY] Issue 1")
        self.strategy.log_insight("[SECURITY] Issue 1")
        self.strategy.log_insight("[SECURITY] Issue 1")

        self.assertEqual(len(self.strategy.critical_insights), 1)

    def test_does_not_mutate_the_chat_model(self):
        """Regression for F-11.

        The strategy used to inject ``get_num_tokens_from_messages`` onto the
        shared chat model with ``object.__setattr__``. ReviewAgent calls that
        method for its own token budgeting and silently received a chars/4
        estimate instead of the model's tokenizer.
        """
        model = MagicMock()
        provider = MagicMock(spec=LLMProvider)
        provider.get_chat_model.return_value = model

        before = set(model.__dict__)
        SmartMemoryStrategy(provider, max_tokens=100)

        self.assertEqual(set(model.__dict__), before)

    def test_token_counter_is_injectable(self):
        """Token estimation is a collaborator, not a patch on the model."""
        strategy = SmartMemoryStrategy(self.provider, max_tokens=100, token_counter=lambda text: len(text))

        strategy.log_insight("[TODO] abc")

        # 1 token per character rather than the chars/4 default.
        self.assertEqual(strategy.low_insights[0].tokens, len("[TODO] abc"))


if __name__ == "__main__":
    unittest.main()
