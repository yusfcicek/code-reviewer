"""Unit tests for the agent's prompt assembly and scratchpad dialect.

These cover two defects that produce no error and no log line, only a model
that is missing information it was supposed to receive:

- the runnable supplied ``memory_context`` to a template that never declared
  it, so every collected insight was dropped (F-02);
- tools were never described to the model, and the scratchpad was formatted as
  OpenAI function messages while the output parser reads Hermes XML (F-03).
"""

import unittest
from unittest.mock import MagicMock, patch

from langchain.tools import StructuredTool
from langchain_core.agents import AgentAction

from code_reviewer.infrastructure.llm.review_agent import (
    ReviewAgent,
    format_to_hermes_messages,
    render_tool_catalogue,
)
from code_reviewer.application.ports import LLMProvider, MemoryStrategy


def _sample_tool_input(target_path: str) -> str:
    """Reads a thing from a place."""
    return target_path


SAMPLE_TOOL = StructuredTool.from_function(
    func=_sample_tool_input,
    name="sample_probe",
    description="Probes a path and returns what it found.",
)


class TestToolCatalogue(unittest.TestCase):
    def test_catalogue_names_each_tool_and_its_description(self):
        rendered = render_tool_catalogue([SAMPLE_TOOL])

        self.assertIn("sample_probe", rendered)
        self.assertIn("Probes a path and returns what it found.", rendered)

    def test_catalogue_describes_parameters(self):
        rendered = render_tool_catalogue([SAMPLE_TOOL])

        self.assertIn("target_path", rendered)

    def test_catalogue_uses_the_dialect_the_parser_reads(self):
        rendered = render_tool_catalogue([SAMPLE_TOOL])

        self.assertIn("<tools>", rendered)
        self.assertIn("</tools>", rendered)
        self.assertIn("<tool_call>", rendered)  # the call format is shown

    def test_empty_catalogue_is_explicit(self):
        self.assertIn("no tools", render_tool_catalogue([]).lower())


class TestHermesScratchpad(unittest.TestCase):
    def test_step_is_rendered_as_call_then_response(self):
        action = AgentAction(
            tool="sample_probe",
            tool_input={"target_path": "src/app.py"},
            log="<tool_call>...</tool_call>",
        )

        messages = format_to_hermes_messages([(action, "found 3 matches")])

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].content, "<tool_call>...</tool_call>")
        self.assertIn("found 3 matches", messages[1].content)
        self.assertIn("<tool_response>", messages[1].content)

    def test_no_steps_produces_no_messages(self):
        self.assertEqual(format_to_hermes_messages([]), [])


class TestPromptAssembly(unittest.TestCase):
    def setUp(self):
        provider = MagicMock(spec=LLMProvider)
        provider.get_chat_model.return_value = MagicMock()
        self.memory = MagicMock(spec=MemoryStrategy)

        with patch("code_reviewer.infrastructure.llm.review_agent.get_tools") as get_tools:
            get_tools.return_value = [SAMPLE_TOOL]
            self.agent = ReviewAgent(provider, self.memory)

    def test_template_declares_memory_context(self):
        self.assertIn("memory_context", self.agent.prompt.input_variables)

    def test_rendered_prompt_contains_the_memory_context(self):
        messages = self.agent.prompt.format_messages(
            input="review this",
            memory_context="SENTINEL-MEMORY-42",
            agent_scratchpad=[],
        )

        rendered = "\n".join(str(m.content) for m in messages)
        self.assertIn("SENTINEL-MEMORY-42", rendered)

    def test_rendered_prompt_lists_the_registered_tools(self):
        messages = self.agent.prompt.format_messages(
            input="review this",
            memory_context="",
            agent_scratchpad=[],
        )

        rendered = "\n".join(str(m.content) for m in messages)
        self.assertIn("sample_probe", rendered)
        self.assertIn("Probes a path and returns what it found.", rendered)

    def test_review_diff_passes_the_context_it_loaded(self):
        self.memory.load_context.return_value = "LOADED-CONTEXT"
        self.agent.agent_executor = MagicMock()
        self.agent.agent_executor.invoke.return_value = {"output": "done"}

        self.agent.review_diff("app.py", "+ line")

        payload = self.agent.agent_executor.invoke.call_args[0][0]
        self.assertEqual(payload["memory_context"], "LOADED-CONTEXT")


if __name__ == "__main__":
    unittest.main()
