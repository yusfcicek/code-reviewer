"""Unit tests for ReviewAgent.

LangChain is a real dependency of this project and is installed by ``uv sync``,
so it is imported normally here. An earlier version of this module replaced
several ``langchain`` modules in ``sys.modules`` at import time; because
``sys.modules`` is process-global, those stubs leaked into every test collected
afterwards and made results order-dependent (finding F-37).
"""

import unittest
from unittest.mock import MagicMock, patch

from langchain_core.tools import StructuredTool

from code_reviewer.application.ports import LLMProvider, MemoryStrategy
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from tests.fakes import BoundScriptedModel, ScriptedChatModel


def _probe(target_path: str) -> str:
    """Reads a thing from a place."""
    return target_path


SAMPLE_TOOL = StructuredTool.from_function(func=_probe, name="sample_probe", description="Probes a path.")


def _agent(provider, memory, tools=(), **kwargs) -> ReviewAgent:
    """Builds an agent with a known tool set.

    The real tools shell out to ``grep`` and ``find``; the catalogue is covered
    by the prompt tests, so these run with whatever is passed.
    """
    with patch("code_reviewer.infrastructure.llm.review_agent.get_tools") as get_tools:
        get_tools.return_value = list(tools)
        return ReviewAgent(provider, memory, **kwargs)


class TestReviewAgent(unittest.TestCase):
    def setUp(self):
        self.mock_provider = MagicMock(spec=LLMProvider)
        self.mock_memory = MagicMock(spec=MemoryStrategy)
        self.mock_llm = MagicMock()
        self.mock_llm.get_num_tokens_from_messages.return_value = 1000
        self.mock_provider.get_chat_model.return_value = self.mock_llm

        self.agent = _agent(self.mock_provider, self.mock_memory)
        self.agent.loop = MagicMock()
        self.agent.loop.run.return_value = "Agent Review Output"

    def _prompt_text(self) -> str:
        """The messages the loop was handed, flattened."""
        messages = self.agent.loop.run.call_args[0][0]
        return "\n".join(str(message.content) for message in messages)

    def test_review_diff_basic(self):
        self.mock_memory.load_context.return_value = "Existing Context"

        output = self.agent.review_diff("test.py", "+ change")

        self.mock_memory.load_context.assert_called()
        self.agent.loop.run.assert_called_once()

        prompt = self._prompt_text()
        self.assertIn("Review the changes in `test.py`", prompt)
        self.assertIn("DIFF:\n+ change", prompt)

        self.assertEqual(output, "Agent Review Output")

    def test_review_diff_with_context_files(self):
        self.mock_memory.load_context.return_value = ""

        self.agent.review_diff("test.py", "+ diff", other_files=["test.py", "other_file.py", "README.md"])

        prompt = self._prompt_text()
        self.assertIn("CONTEXT: The following files are ALSO modified in this MR:", prompt)
        self.assertIn("- other_file.py", prompt)
        self.assertIn("- README.md", prompt)
        # The file under review must not be listed as its own context.
        self.assertNotIn("- test.py", prompt)

    def test_memory_logging(self):
        self.mock_memory.load_context.return_value = ""
        self.agent.loop.run.return_value = "Review...\nADD_MEMORY: [RISK] Risk found\n...More review"

        self.agent.review_diff("test.py", "+ diff")

        self.mock_memory.log_insight.assert_any_call("[RISK] Risk found")

    def test_auto_dependency_imports(self):
        with patch("code_reviewer.infrastructure.tools.definitions.DependencyAnalysisTools") as tools:
            tools.get_file_imports.return_value = ["import os", "import sys"]
            tools.find_references.return_value = "No references"

            self.agent.review_diff("test.py", "diff")

            self.mock_memory.log_insight.assert_any_call(
                "ADD_MEMORY: [DEPENDENCY] test.py DEPENDS ON:\n['import os', 'import sys']"
            )

    def test_context_is_loaded_once_per_review(self):
        """Regression for F-19: load_context() was called twice, the first
        result overwritten unused before it could reach the prompt."""
        self.mock_memory.load_context.return_value = ""

        self.agent.review_diff("test.py", "+ diff")

        self.assertEqual(self.mock_memory.load_context.call_count, 1)

    def test_the_review_is_saved_to_memory(self):
        self.mock_memory.load_context.return_value = ""

        self.agent.review_diff("test.py", "+ diff")

        self.mock_memory.save_context.assert_called_once()


class TestToolProtocol(unittest.TestCase):
    """How tools are offered to the model.

    Binding natively is the only way a hosted endpoint can call a tool at all.
    Not binding is the only way an on-prem vLLM without ``--enable-auto-tool-
    choice`` will accept the request. `auto` tries the first and falls back to
    the second, which is safe because the parser reads both dialects.
    """

    def setUp(self):
        self.memory = MagicMock(spec=MemoryStrategy)

    def _provider(self, model):
        provider = MagicMock(spec=LLMProvider)
        provider.get_chat_model.return_value = model
        return provider

    def test_auto_binds_the_tools(self):
        model = ScriptedChatModel([])

        _agent(self._provider(model), self.memory, [SAMPLE_TOOL], tool_protocol="auto")

        self.assertEqual(model.bound_tools, [SAMPLE_TOOL])

    def test_the_bound_model_is_the_one_the_loop_runs(self):
        """Binding and then calling the unbound model offers the model nothing.

        LangChain's `bind_tools` returns a runnable binding rather than the
        model, so keeping the original is a silent way back to the defect this
        level exists to remove.
        """
        model = ScriptedChatModel([])

        agent = _agent(self._provider(model), self.memory, [SAMPLE_TOOL], tool_protocol="auto")

        self.assertIsInstance(agent.model, BoundScriptedModel)
        self.assertIs(agent.loop.model, agent.model)

    def test_auto_falls_back_when_the_server_refuses_to_bind(self):
        model = ScriptedChatModel([], binding_error=NotImplementedError("no tool API"))

        agent = _agent(self._provider(model), self.memory, [SAMPLE_TOOL], tool_protocol="auto")

        self.assertIsNone(model.bound_tools)
        self.assertIs(agent.model, model)

    def test_native_raises_when_the_server_refuses_to_bind(self):
        """`native` is the mode for someone who wants to know, not to guess."""
        model = ScriptedChatModel([], binding_error=NotImplementedError("no tool API"))

        with self.assertRaises(NotImplementedError):
            _agent(self._provider(model), self.memory, [SAMPLE_TOOL], tool_protocol="native")

    def test_hermes_never_binds(self):
        model = ScriptedChatModel([])

        _agent(self._provider(model), self.memory, [SAMPLE_TOOL], tool_protocol="hermes")

        self.assertIsNone(model.bound_tools)

    def test_hermes_still_offers_the_tools_in_the_prompt(self):
        model = ScriptedChatModel([])

        agent = _agent(self._provider(model), self.memory, [SAMPLE_TOOL], tool_protocol="hermes")

        self.assertEqual([tool.name for tool in agent.tools], ["sample_probe"])

    def test_none_registers_no_tools_at_all(self):
        model = ScriptedChatModel([])

        agent = _agent(self._provider(model), self.memory, [SAMPLE_TOOL], tool_protocol="none")

        self.assertIsNone(model.bound_tools)
        self.assertEqual(agent.tools, [])

    def test_the_protocol_is_read_from_the_environment(self):
        model = ScriptedChatModel([])

        with patch.dict("os.environ", {"REVIEW_TOOL_PROTOCOL": "hermes"}):
            _agent(self._provider(model), self.memory, [SAMPLE_TOOL])

        self.assertIsNone(model.bound_tools)

    def test_an_unknown_protocol_is_rejected_at_construction(self):
        """A typo must not silently downgrade to no tools."""
        model = ScriptedChatModel([])

        with self.assertRaises(ValueError):
            _agent(self._provider(model), self.memory, [SAMPLE_TOOL], tool_protocol="hemres")


if __name__ == "__main__":
    unittest.main()
