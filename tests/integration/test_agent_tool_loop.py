"""The agent's tool loop, end to end against a scripted model.

No network: the model is a stub that replays a fixed list of responses. The
point is to prove that a tool call the model emits actually reaches the tool
and that the tool's output comes back as an observation the model is shown —
the wiring finding F-03 reported as broken.

It runs twice, once per dialect. A single-protocol test passes while the other
protocol is silently inert, which is exactly the state finding G-02 described:
against a hosted endpoint no tool was ever called, and the model wrote a review
describing scans it had not run.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from code_reviewer.application.ports import MemoryStrategy
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from tests.fakes import ScriptedChatModel, hermes_call

pytestmark = pytest.mark.integration


CALLS: list[tuple] = []


def _record_probe(target_path: str) -> str:
    """Records that it was called and returns a recognisable observation."""
    CALLS.append((target_path,))
    return f"PROBE-RESULT for {target_path}"


def _record_search(pattern: str, path: str) -> str:
    """A two-argument tool: the case the old parser could not express."""
    CALLS.append((pattern, path))
    return f"SEARCH-RESULT for {pattern} under {path}"


PROBE_TOOL = StructuredTool.from_function(
    func=_record_probe, name="sample_probe", description="Probes a path."
)
SEARCH_TOOL = StructuredTool.from_function(
    func=_record_search, name="sample_search", description="Searches a path for a pattern."
)

FINAL_ANSWER = "# 🏛️ Architectural Review Summary\nAll good."


def _build_agent(responses, protocol):
    model = ScriptedChatModel(responses)
    provider = MagicMock()
    provider.get_chat_model.return_value = model

    memory = MagicMock(spec=MemoryStrategy)
    memory.load_context.return_value = "PRIOR-INSIGHTS"

    with patch("code_reviewer.infrastructure.llm.review_agent.get_tools") as get_tools:
        get_tools.return_value = [PROBE_TOOL, SEARCH_TOOL]
        agent = ReviewAgent(provider, memory, token_counter=lambda text: 10, tool_protocol=protocol)
    return agent, model, memory


class TestHermesDialect(unittest.TestCase):
    """XML in the message text, as an on-prem vLLM emits it."""

    def setUp(self):
        CALLS.clear()
        self.agent, self.model, self.memory = _build_agent(
            [hermes_call("sample_probe", target_path="src/app.py"), FINAL_ANSWER], "hermes"
        )

    def test_the_tool_call_reaches_the_tool(self):
        self.agent.review_diff("src/app.py", "+ changed line")

        self.assertEqual(CALLS, [("src/app.py",)])

    def test_the_loop_returns_the_models_final_answer(self):
        output = self.agent.review_diff("src/app.py", "+ changed line")

        self.assertIn("Architectural Review Summary", output)

    def test_the_review_is_saved_to_memory(self):
        self.agent.review_diff("src/app.py", "+ changed line")

        self.memory.save_context.assert_called_once()

    def test_the_tools_are_offered_in_the_prompt_rather_than_bound(self):
        self.agent.review_diff("src/app.py", "+ changed line")

        self.assertIsNone(self.model.bound_tools)
        first_turn = "\n".join(str(m.content) for m in self.model.calls[0])
        self.assertIn("sample_probe", first_turn)


class TestNativeDialect(unittest.TestCase):
    """A structured `tool_calls` field, as every hosted endpoint delivers it."""

    def setUp(self):
        CALLS.clear()
        call = AIMessage(
            content="",
            tool_calls=[{"name": "sample_probe", "args": {"target_path": "src/app.py"}, "id": "call_1"}],
        )
        self.agent, self.model, self.memory = _build_agent([call, FINAL_ANSWER], "native")

    def test_the_tools_are_bound_to_the_model(self):
        self.assertEqual([tool.name for tool in self.model.bound_tools], ["sample_probe", "sample_search"])

    def test_the_tool_call_reaches_the_tool(self):
        self.agent.review_diff("src/app.py", "+ changed line")

        self.assertEqual(CALLS, [("src/app.py",)])

    def test_the_loop_returns_the_models_final_answer(self):
        output = self.agent.review_diff("src/app.py", "+ changed line")

        self.assertIn("Architectural Review Summary", output)


class TestMultiArgumentCalls(unittest.TestCase):
    """The regression this level exists for.

    The old parser matched one `<parameter=>` block. Against a two-argument
    call it did not merely drop the second argument, it swallowed the second
    block's raw XML into the first argument's value.
    """

    def setUp(self):
        CALLS.clear()

    def test_both_arguments_reach_a_hermes_tool_call(self):
        agent, _, _ = _build_agent(
            [hermes_call("sample_search", pattern="handle_request", path="src/"), FINAL_ANSWER],
            "hermes",
        )

        agent.review_diff("src/app.py", "+ changed line")

        self.assertEqual(CALLS, [("handle_request", "src/")])

    def test_both_arguments_reach_a_native_tool_call(self):
        call = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "sample_search",
                    "args": {"pattern": "handle_request", "path": "src/"},
                    "id": "call_1",
                }
            ],
        )
        agent, _, _ = _build_agent([call, FINAL_ANSWER], "native")

        agent.review_diff("src/app.py", "+ changed line")

        self.assertEqual(CALLS, [("handle_request", "src/")])


class TestWithoutTools(unittest.TestCase):
    """`none` is a legitimate choice: the verdict never depended on the model."""

    def setUp(self):
        CALLS.clear()

    def test_no_tool_is_offered_and_the_narration_still_lands(self):
        agent, model, _ = _build_agent([FINAL_ANSWER], "none")

        output = agent.review_diff("src/app.py", "+ changed line")

        self.assertEqual(CALLS, [])
        self.assertIsNone(model.bound_tools)
        self.assertIn("Architectural Review Summary", output)

    def test_the_prompt_says_there_are_no_tools(self):
        agent, model, _ = _build_agent([FINAL_ANSWER], "none")

        agent.review_diff("src/app.py", "+ changed line")

        first_turn = "\n".join(str(m.content) for m in model.calls[0]).lower()
        self.assertIn("no tools", first_turn)


if __name__ == "__main__":
    unittest.main()
