"""Reading a tool call out of a model response, in either protocol.

The agent runs against two kinds of endpoint and they carry a tool call
differently: an on-prem vLLM served with a Hermes template puts XML in the
message *text*, while OpenAI, Groq and most hosted APIs put a structured
``tool_calls`` field on the message. Supporting one leaves the tool machinery
silently idle on the other — the model narrates as though it had run the tools
(finding G-02).
"""

import unittest

from langchain_core.messages import AIMessage

from code_reviewer.infrastructure.llm.tool_calls import (
    FinalAnswer,
    ToolCallParser,
    ToolInvocation,
)


class TestNativeToolCalls(unittest.TestCase):
    """The structured field, as hosted endpoints deliver it."""

    def test_a_native_call_yields_name_and_arguments(self):
        response = AIMessage(
            content="",
            tool_calls=[{"name": "read_file", "args": {"file_path": "src/app.py"}, "id": "call_1"}],
        )

        result = ToolCallParser().parse(response)

        self.assertEqual(result, ToolInvocation("read_file", {"file_path": "src/app.py"}, "call_1"))

    def test_the_call_id_is_carried(self):
        """A native tool result must come back with its id or the server rejects it."""
        response = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "call_abc"}])

        self.assertEqual(ToolCallParser().parse(response).call_id, "call_abc")

    def test_a_native_call_without_arguments_yields_an_empty_mapping(self):
        response = AIMessage(content="", tool_calls=[{"name": "list_files", "args": {}, "id": "c"}])

        self.assertEqual(ToolCallParser().parse(response).arguments, {})

    def test_the_native_field_wins_over_text(self):
        """A server that negotiated the tool API is the authority on the call."""
        response = AIMessage(
            content=(
                "<tool_call>\n<function=from_text>\n<parameter=a>\n1\n</parameter>\n</function>\n</tool_call>"
            ),
            tool_calls=[{"name": "from_field", "args": {}, "id": "c"}],
        )

        self.assertEqual(ToolCallParser().parse(response).name, "from_field")


class TestHermesToolCalls(unittest.TestCase):
    """XML in the message text, as a vLLM Hermes template emits it."""

    def test_a_single_parameter_call_is_read(self):
        text = (
            "<tool_call>\n<function=read_file>\n"
            "<parameter=file_path>\nsrc/app.py\n</parameter>\n"
            "</function>\n</tool_call>"
        )

        result = ToolCallParser().parse(AIMessage(content=text))

        self.assertEqual(result, ToolInvocation("read_file", {"file_path": "src/app.py"}, None))

    def test_every_parameter_of_a_multi_argument_call_survives(self):
        """The regression this level exists for.

        `grep_search` and `find_references` both take two parameters. A parser
        that matches one `<parameter=>` block drops the second silently and the
        tool runs against a default the model never asked for.
        """
        text = (
            "<tool_call>\n<function=grep_search>\n"
            "<parameter=pattern>\nhandle_request\n</parameter>\n"
            "<parameter=path>\nsrc/\n</parameter>\n"
            "</function>\n</tool_call>"
        )

        result = ToolCallParser().parse(AIMessage(content=text))

        self.assertEqual(result.arguments, {"pattern": "handle_request", "path": "src/"})

    def test_surrounding_prose_does_not_hide_the_call(self):
        text = (
            "I should look at the file first.\n\n"
            "<tool_call>\n<function=read_file>\n"
            "<parameter=file_path>\nsrc/app.py\n</parameter>\n"
            "</function>\n</tool_call>\n\nThen I will judge it."
        )

        self.assertEqual(ToolCallParser().parse(AIMessage(content=text)).name, "read_file")

    def test_a_value_spanning_several_lines_is_kept_whole(self):
        text = (
            "<tool_call>\n<function=run_semantic_analysis>\n"
            "<parameter=query>\n+ added\n- removed\n</parameter>\n"
            "</function>\n</tool_call>"
        )

        result = ToolCallParser().parse(AIMessage(content=text))

        self.assertEqual(result.arguments["query"], "+ added\n- removed")

    def test_the_first_call_wins_when_the_model_emits_several(self):
        """One tool per turn: the observation for the first changes the rest."""
        text = (
            "<tool_call>\n<function=first>\n<parameter=a>\n1\n</parameter>\n"
            "</function>\n</tool_call>\n"
            "<tool_call>\n<function=second>\n<parameter=b>\n2\n</parameter>\n"
            "</function>\n</tool_call>"
        )

        self.assertEqual(ToolCallParser().parse(AIMessage(content=text)).name, "first")


class TestFinalAnswers(unittest.TestCase):
    def test_plain_text_is_a_final_answer(self):
        result = ToolCallParser().parse(AIMessage(content="# Review\nAll good."))

        self.assertEqual(result, FinalAnswer("# Review\nAll good."))

    def test_an_unclosed_call_is_a_final_answer_rather_than_a_crash(self):
        """Malformed output is the model's problem, not an exception here."""
        text = "<tool_call>\n<function=read_file>\n<parameter=file_path>\nsrc/app.py"

        result = ToolCallParser().parse(AIMessage(content=text))

        self.assertIsInstance(result, FinalAnswer)

    def test_a_call_with_no_parameters_still_invokes_the_tool(self):
        text = "<tool_call>\n<function=list_files>\n</function>\n</tool_call>"

        result = ToolCallParser().parse(AIMessage(content=text))

        self.assertEqual(result, ToolInvocation("list_files", {}, None))

    def test_empty_content_is_an_empty_final_answer(self):
        self.assertEqual(ToolCallParser().parse(AIMessage(content="")), FinalAnswer(""))

    def test_a_list_content_block_is_flattened_to_text(self):
        """Some providers return content as a list of blocks rather than a string."""
        response = AIMessage(content=[{"type": "text", "text": "All good."}])

        result = ToolCallParser().parse(response)

        self.assertIsInstance(result, FinalAnswer)
        self.assertIn("All good.", result.text)


if __name__ == "__main__":
    unittest.main()
