"""Context rendering, chunking and statistics of SmartMemoryStrategy.

Separate from `test_smart_memory.py`, which covers priority handling and
summarisation, so each file stays readable.
"""

import unittest
from unittest.mock import MagicMock

from code_reviewer.application.ports import LLMProvider
from code_reviewer.domain.finding import AffectedCode
from code_reviewer.infrastructure.memory.smart_memory import SmartMemoryStrategy


def _strategy(max_tokens=100000):
    provider = MagicMock(spec=LLMProvider)
    provider.get_chat_model.return_value = MagicMock()
    return SmartMemoryStrategy(provider, max_tokens=max_tokens)


class TestLoadContext(unittest.TestCase):
    def test_empty_memory_still_renders_a_header(self):
        context = _strategy().load_context()

        self.assertIn("SMART MEMORY CONTEXT", context)

    def test_critical_insights_are_always_included(self):
        strategy = _strategy()
        strategy.log_insight("[SECURITY] hardcoded token in auth.py")

        self.assertIn("hardcoded token in auth.py", strategy.load_context())

    def test_high_priority_insights_are_included(self):
        strategy = _strategy()
        strategy.log_insight("[RISK] circular dependency introduced")

        self.assertIn("circular dependency introduced", strategy.load_context())

    def test_affected_code_is_listed_with_its_reason(self):
        strategy = _strategy()
        strategy.add_affected_code("src/api.py", "handle", "struct field renamed")

        context = strategy.load_context()

        self.assertIn("src/api.py:handle", context)
        self.assertIn("struct field renamed", context)

    def test_context_reports_token_usage(self):
        strategy = _strategy()
        strategy.log_insight("[QUALITY] long function")

        self.assertIn("Memory usage:", strategy.load_context())

    def test_summary_buffer_is_rendered_when_present(self):
        strategy = _strategy()
        strategy.summary_buffer = "PREVIOUSLY-SUMMARISED"

        self.assertIn("PREVIOUSLY-SUMMARISED", strategy.load_context())


class TestPriorityContext(unittest.TestCase):
    def test_priority_context_keeps_critical_and_affected_code_only(self):
        strategy = _strategy()
        strategy.log_insight("[SECURITY] critical thing")
        strategy.log_insight("[QUALITY] normal thing")
        strategy.add_affected_code("src/api.py", "handle", "renamed")

        context = strategy.get_priority_context()

        self.assertIn("critical thing", context)
        self.assertIn("src/api.py:handle", context)
        self.assertNotIn("normal thing", context)


class TestAffectedCode(unittest.TestCase):
    def test_duplicate_entries_are_ignored(self):
        strategy = _strategy()
        strategy.add_affected_code("src/api.py", "handle", "first reason")
        strategy.add_affected_code("src/api.py", "handle", "second reason")

        self.assertEqual(len(strategy.affected_codes), 1)

    def test_preview_is_truncated(self):
        strategy = _strategy()
        strategy.add_affected_code("src/api.py", "handle", "reason", "x" * 500)

        self.assertEqual(len(strategy.affected_codes[0].preview), AffectedCode.MAX_PREVIEW_CHARS)


class TestChunking(unittest.TestCase):
    def test_content_is_split_into_bounded_chunks(self):
        strategy = _strategy()
        content = "\n".join(f"line number {i}" for i in range(200))

        chunks = strategy.chunk_large_file(content, "big.py", chunk_size=200)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 400 for chunk in chunks))

    def test_chunks_are_cached_per_file(self):
        strategy = _strategy()
        first = strategy.chunk_large_file("a\nb\nc\n", "same.py", chunk_size=2)

        second = strategy.chunk_large_file("completely different", "same.py", chunk_size=2)

        self.assertIs(first, second)

    def test_chunks_reassemble_into_the_original(self):
        strategy = _strategy()
        content = "\n".join(f"line {i}" for i in range(50))

        chunks = strategy.chunk_large_file(content, "f.py", chunk_size=100)

        self.assertEqual("\n".join(chunks), content)


class TestStats(unittest.TestCase):
    def test_stats_report_each_bucket(self):
        strategy = _strategy()
        strategy.log_insight("[SECURITY] a")
        strategy.log_insight("[RISK] b")
        strategy.log_insight("[QUALITY] c")
        strategy.log_insight("[TODO] d")

        stats = strategy.get_stats()

        self.assertEqual(stats["critical_count"], 1)
        self.assertEqual(stats["high_count"], 1)
        self.assertEqual(stats["normal_count"], 1)
        self.assertEqual(stats["low_count"], 1)
        self.assertGreater(stats["usage_percent"], 0)

    def test_save_context_triggers_the_summarisation_check(self):
        strategy = _strategy(max_tokens=100)
        for i in range(10):
            strategy.log_insight(f"[TODO] note {i} " + "A" * 50)

        strategy.save_context("input", "output")

        self.assertEqual(strategy.summarization_count, 1)

    def test_the_strategy_exposes_no_framework_object(self):
        """The port used to require get_memory_object(), which handed callers
        a LangChain type through the abstraction meant to hide it (F-26)."""
        self.assertFalse(hasattr(_strategy(), "get_memory_object"))


if __name__ == "__main__":
    unittest.main()
