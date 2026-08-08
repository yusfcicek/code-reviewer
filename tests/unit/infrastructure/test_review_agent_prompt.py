"""Unit tests for the agent's prompt assembly.

These cover two defects that produce no error and no log line, only a model
that is missing information it was supposed to receive:

- the runnable supplied ``memory_context`` to a template that never declared
  it, so every collected insight was dropped (F-02);
- tools were never described to the model (F-03).

The scratchpad has no tests here any more: the loop appends the model's own
turn and the tool observation to the conversation directly, so there is no
separate rendering step to get wrong (G-02).
"""

import unittest
from unittest.mock import MagicMock, patch

from langchain_core.tools import StructuredTool

from code_reviewer.application.ports import LLMProvider, MemoryStrategy
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent, render_tool_catalogue


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
        messages = self.agent.prompt.format_messages(input="review this", memory_context="SENTINEL-MEMORY-42")

        rendered = "\n".join(str(m.content) for m in messages)
        self.assertIn("SENTINEL-MEMORY-42", rendered)

    def test_rendered_prompt_lists_the_registered_tools(self):
        messages = self.agent.prompt.format_messages(input="review this", memory_context="")

        rendered = "\n".join(str(m.content) for m in messages)
        self.assertIn("sample_probe", rendered)
        self.assertIn("Probes a path and returns what it found.", rendered)

    def test_review_diff_passes_the_context_it_loaded(self):
        self.memory.load_context.return_value = "LOADED-CONTEXT"
        self.agent.loop = MagicMock()
        self.agent.loop.run.return_value = "done"

        self.agent.review_diff("app.py", "+ line")

        messages = self.agent.loop.run.call_args[0][0]
        rendered = "\n".join(str(m.content) for m in messages)
        self.assertIn("LOADED-CONTEXT", rendered)


if __name__ == "__main__":
    unittest.main()
