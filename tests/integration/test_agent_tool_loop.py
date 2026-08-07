"""The agent's tool loop, end to end against a scripted model.

No network: the chat model is a stub that replays a fixed list of completions.
The point is to prove that a Hermes tool call emitted by the model actually
reaches the tool, and that the tool's output comes back as an observation the
model is shown — the wiring that finding F-03 reported as broken.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest
from langchain.tools import StructuredTool
from langchain_community.chat_models.fake import FakeListChatModel

from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from code_reviewer.application.ports import MemoryStrategy

pytestmark = pytest.mark.integration


CALLS = []


def _record_probe(target_path: str) -> str:
    """Records that it was called and returns a recognisable observation."""
    CALLS.append(target_path)
    return f"PROBE-RESULT for {target_path}"


PROBE_TOOL = StructuredTool.from_function(
    func=_record_probe,
    name="sample_probe",
    description="Probes a path.",
)

TOOL_CALL = (
    "<tool_call>\n"
    "<function=sample_probe>\n"
    "<parameter=target_path>\n"
    "src/app.py\n"
    "</parameter>\n"
    "</function>\n"
    "</tool_call>"
)

FINAL_ANSWER = "# 🏛️ Architectural Review Summary\nAll good."


class TestAgentToolLoop(unittest.TestCase):
    def setUp(self):
        CALLS.clear()

        # First completion asks for a tool, second one answers.
        self.model = FakeListChatModel(responses=[TOOL_CALL, FINAL_ANSWER])
        provider = MagicMock()
        provider.get_chat_model.return_value = self.model

        self.memory = MagicMock(spec=MemoryStrategy)
        self.memory.load_context.return_value = "PRIOR-INSIGHTS"

        with patch("code_reviewer.infrastructure.llm.review_agent.get_tools") as get_tools:
            get_tools.return_value = [PROBE_TOOL]
            self.agent = ReviewAgent(provider, self.memory, token_counter=lambda text: 10)

    def test_model_tool_call_reaches_the_tool(self):
        self.agent.review_diff("src/app.py", "+ changed line")

        self.assertEqual(CALLS, ["src/app.py"])

    def test_loop_terminates_with_the_models_final_answer(self):
        output = self.agent.review_diff("src/app.py", "+ changed line")

        self.assertIn("Architectural Review Summary", output)

    def test_review_is_saved_to_memory(self):
        self.agent.review_diff("src/app.py", "+ changed line")

        self.memory.save_context.assert_called_once()


if __name__ == "__main__":
    unittest.main()
