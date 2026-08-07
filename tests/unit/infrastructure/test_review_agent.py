"""Unit tests for ReviewAgent.

LangChain is a real dependency of this project and is installed by ``uv sync``,
so it is imported normally here. An earlier version of this module replaced
several ``langchain`` modules in ``sys.modules`` at import time; because
``sys.modules`` is process-global, those stubs leaked into every test collected
afterwards and made results order-dependent (finding F-37).
"""

import unittest
from unittest.mock import MagicMock, patch

from code_reviewer.application.ports import LLMProvider, MemoryStrategy
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent


class TestReviewAgent(unittest.TestCase):
    def setUp(self):
        self.mock_provider = MagicMock(spec=LLMProvider)
        self.mock_memory = MagicMock(spec=MemoryStrategy)
        self.mock_llm = MagicMock()
        self.mock_llm.get_num_tokens_from_messages.return_value = 1000
        self.mock_provider.get_chat_model.return_value = self.mock_llm

        # Real tools shell out to grep/find; the prompt tests cover the
        # catalogue separately, so the loop tests run with none registered.
        with patch("code_reviewer.infrastructure.llm.review_agent.get_tools") as mock_get_tools:
            mock_get_tools.return_value = []
            self.agent = ReviewAgent(self.mock_provider, self.mock_memory)

    def test_review_diff_basic(self):
        self.mock_memory.load_context.return_value = "Existing Context"
        self.agent.agent_executor = MagicMock()
        self.agent.agent_executor.invoke.return_value = {"output": "Agent Review Output"}

        diff = "+ change"
        filename = "test.py"
        output = self.agent.review_diff(filename, diff)

        self.mock_memory.load_context.assert_called()
        self.agent.agent_executor.invoke.assert_called_once()

        inputs = self.agent.agent_executor.invoke.call_args[0][0]
        self.assertIn(f"Review the changes in `{filename}`", inputs["input"])
        self.assertIn("DIFF:\n+ change", inputs["input"])

        self.assertEqual(output, "Agent Review Output")

    def test_review_diff_with_context_files(self):
        self.mock_memory.load_context.return_value = ""
        self.agent.agent_executor = MagicMock()
        self.agent.agent_executor.invoke.return_value = {"output": "Done"}

        other_files = ["test.py", "other_file.py", "README.md"]
        self.agent.review_diff("test.py", "+ diff", other_files=other_files)

        prompt = self.agent.agent_executor.invoke.call_args[0][0]["input"]

        self.assertIn("CONTEXT: The following files are ALSO modified in this MR:", prompt)
        self.assertIn("- other_file.py", prompt)
        self.assertIn("- README.md", prompt)
        # The file under review must not be listed as its own context.
        self.assertNotIn("- test.py", prompt)

    def test_memory_logging(self):
        self.mock_memory.load_context.return_value = ""
        self.agent.agent_executor = MagicMock()
        self.agent.agent_executor.invoke.return_value = {
            "output": "Review...\nADD_MEMORY: [RISK] Risk found\n...More review"
        }

        self.agent.review_diff("test.py", "+ diff")

        self.mock_memory.log_insight.assert_any_call("[RISK] Risk found")

    def test_auto_dependency_imports(self):
        with patch("code_reviewer.infrastructure.tools.definitions.DependencyAnalysisTools") as mock_tools:
            mock_tools.get_file_imports.return_value = ["import os", "import sys"]
            mock_tools.find_references.return_value = "No references"

            self.agent.agent_executor = MagicMock()
            self.agent.agent_executor.invoke.return_value = {"output": "Done"}

            self.agent.review_diff("test.py", "diff")

            self.mock_memory.log_insight.assert_any_call(
                "ADD_MEMORY: [DEPENDENCY] test.py DEPENDS ON:\n['import os', 'import sys']"
            )

    def test_context_is_loaded_once_per_review(self):
        """Regression for F-19: load_context() was called twice, the first
        result overwritten unused before it could reach the prompt."""
        self.mock_memory.load_context.return_value = ""
        self.agent.agent_executor = MagicMock()
        self.agent.agent_executor.invoke.return_value = {"output": "Done"}

        self.agent.review_diff("test.py", "+ diff")

        self.assertEqual(self.mock_memory.load_context.call_count, 1)


if __name__ == "__main__":
    unittest.main()
