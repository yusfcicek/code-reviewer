"""The loop that drives the model and its tools.

Bounds are passed to the constructor rather than read from the environment
here, so these tests describe behaviour rather than configuration and never
mutate the process they run in.
"""

import unittest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from code_reviewer.infrastructure.llm.narration_loop import NarrationLoop
from tests.fakes import ScriptedChatModel, hermes_call


def _tool(name: str, func) -> StructuredTool:
    return StructuredTool.from_function(func=func, name=name, description=f"The {name} tool.")


def probe(target_path: str) -> str:
    return f"PROBE-RESULT for {target_path}"


def two_argument(pattern: str, path: str) -> str:
    return f"SEARCHED {pattern!r} under {path!r}"


def explodes() -> str:
    raise RuntimeError("the tool broke")


PROBE = _tool("probe", probe)
SEARCH = _tool("search", two_argument)
BROKEN = _tool("broken", explodes)

START = [SystemMessage(content="You review code."), HumanMessage(content="Review src/app.py")]


class TestTermination(unittest.TestCase):
    def test_a_response_without_a_tool_call_ends_the_loop(self):
        model = ScriptedChatModel(["# Review\nAll good."])

        result = NarrationLoop(model, [PROBE]).run(START)

        self.assertEqual(result, "# Review\nAll good.")
        self.assertEqual(len(model.calls), 1)

    def test_a_tool_call_is_followed_by_another_turn(self):
        model = ScriptedChatModel([hermes_call("probe", target_path="src/app.py"), "Done."])

        result = NarrationLoop(model, [PROBE]).run(START)

        self.assertEqual(result, "Done.")
        self.assertEqual(len(model.calls), 2)

    def test_the_starting_messages_are_not_mutated(self):
        """The caller's list is reused across files; the loop must not grow it."""
        model = ScriptedChatModel([hermes_call("probe", target_path="p"), "Done."])
        messages = list(START)

        NarrationLoop(model, [PROBE]).run(messages)

        self.assertEqual(len(messages), len(START))


class TestToolExecution(unittest.TestCase):
    def test_the_tool_runs_and_its_output_is_shown_to_the_model(self):
        model = ScriptedChatModel([hermes_call("probe", target_path="src/app.py"), "Done."])

        NarrationLoop(model, [PROBE]).run(START)

        second_turn = model.calls[1]
        self.assertIn("PROBE-RESULT for src/app.py", str(second_turn[-1].content))

    def test_a_two_argument_call_reaches_the_tool_with_both(self):
        model = ScriptedChatModel([hermes_call("search", pattern="handle", path="src/"), "Done."])

        NarrationLoop(model, [SEARCH]).run(START)

        self.assertIn("SEARCHED 'handle' under 'src/'", str(model.calls[1][-1].content))

    def test_a_native_call_result_returns_as_a_tool_message_with_its_id(self):
        """Without the id the server rejects the conversation as unanswered."""
        response = AIMessage(
            content="",
            tool_calls=[{"name": "probe", "args": {"target_path": "src/app.py"}, "id": "call_9"}],
        )
        model = ScriptedChatModel([response, "Done."])

        NarrationLoop(model, [PROBE]).run(START)

        observation = model.calls[1][-1]
        self.assertIsInstance(observation, ToolMessage)
        self.assertEqual(observation.tool_call_id, "call_9")

    def test_a_hermes_call_result_returns_as_a_plain_message(self):
        """There is no call id in the Hermes dialect to match against."""
        model = ScriptedChatModel([hermes_call("probe", target_path="p"), "Done."])

        NarrationLoop(model, [PROBE]).run(START)

        self.assertNotIsInstance(model.calls[1][-1], ToolMessage)

    def test_the_models_own_turn_is_kept_in_the_transcript(self):
        """The model must see the call it made, or the observation is orphaned."""
        model = ScriptedChatModel([hermes_call("probe", target_path="p"), "Done."])

        NarrationLoop(model, [PROBE]).run(START)

        self.assertIsInstance(model.calls[1][-2], AIMessage)


class TestFailuresReachTheModel(unittest.TestCase):
    """A bad call is a fact the model can act on, not an exception."""

    def test_an_unknown_tool_yields_an_observation_naming_what_exists(self):
        model = ScriptedChatModel([hermes_call("nonexistent", a="1"), "Done."])

        result = NarrationLoop(model, [PROBE, SEARCH]).run(START)

        observation = str(model.calls[1][-1].content)
        self.assertIn("nonexistent", observation)
        self.assertIn("probe", observation)
        self.assertIn("search", observation)
        self.assertEqual(result, "Done.")

    def test_a_raising_tool_yields_an_observation_and_the_loop_continues(self):
        model = ScriptedChatModel([hermes_call("broken"), "Done."])

        result = NarrationLoop(model, [BROKEN]).run(START)

        self.assertIn("the tool broke", str(model.calls[1][-1].content))
        self.assertEqual(result, "Done.")

    def test_a_call_with_the_wrong_arguments_yields_an_observation(self):
        model = ScriptedChatModel([hermes_call("probe", wrong_name="x"), "Done."])

        result = NarrationLoop(model, [PROBE]).run(START)

        self.assertEqual(result, "Done.")


class TestBounds(unittest.TestCase):
    def test_the_iteration_cap_stops_a_model_that_never_finishes(self):
        calls = [hermes_call("probe", target_path="p")] * 10
        model = ScriptedChatModel(calls)

        result = NarrationLoop(model, [PROBE], max_iterations=3).run(START)

        self.assertEqual(len(model.calls), 3)
        self.assertIn("probe", result)

    def test_a_long_observation_is_truncated_with_a_marker(self):
        model = ScriptedChatModel([hermes_call("probe", target_path="x" * 500), "Done."])

        NarrationLoop(model, [PROBE], max_observation_chars=50).run(START)

        observation = str(model.calls[1][-1].content)
        self.assertLess(len(observation), 200)
        self.assertIn("truncated", observation)

    def test_the_truncation_marker_says_how_much_was_dropped(self):
        model = ScriptedChatModel([hermes_call("probe", target_path="x" * 500), "Done."])

        NarrationLoop(model, [PROBE], max_observation_chars=50).run(START)

        self.assertRegex(str(model.calls[1][-1].content), r"\d+ characters")

    def test_there_is_no_time_budget_by_default(self):
        """A cut-off analysis produces an incomplete report that does not say so."""
        self.assertIsNone(NarrationLoop(ScriptedChatModel([]), []).max_seconds)

    def test_a_time_budget_stops_the_loop_after_the_round_that_exhausts_it(self):
        # Ticks: the deadline is set at 0.0, the first round starts at 1.0
        # (inside the budget), the second would start at 100.0 (past it).
        ticks = iter([0.0, 1.0, 100.0])
        model = ScriptedChatModel([hermes_call("probe", target_path="p"), "unreached"])

        result = NarrationLoop(model, [PROBE], max_seconds=10.0, clock=lambda: next(ticks)).run(START)

        self.assertEqual(len(model.calls), 1)
        self.assertIn("probe", result)

    def test_the_budget_is_checked_before_the_model_is_called(self):
        """An already-exhausted budget must not buy one more request."""
        ticks = iter([0.0, 100.0])
        model = ScriptedChatModel(["unreached"])

        NarrationLoop(model, [PROBE], max_seconds=10.0, clock=lambda: next(ticks)).run(START)

        self.assertEqual(model.calls, [])


class TestEnvironmentDefaults(unittest.TestCase):
    """Bounds come from the environment, because the right value is deployment
    knowledge — it depends on the served model's context window."""

    def test_iterations_are_read_from_the_environment(self):
        from code_reviewer.infrastructure.llm.narration_loop import max_iterations_from_env

        self.assertEqual(max_iterations_from_env({"REVIEW_MAX_ITERATIONS": "4"}), 4)

    def test_an_unparseable_iteration_count_falls_back_to_the_default(self):
        from code_reviewer.infrastructure.llm.narration_loop import (
            DEFAULT_MAX_ITERATIONS,
            max_iterations_from_env,
        )

        self.assertEqual(max_iterations_from_env({"REVIEW_MAX_ITERATIONS": "soon"}), DEFAULT_MAX_ITERATIONS)

    def test_an_unset_time_budget_is_no_budget(self):
        from code_reviewer.infrastructure.llm.narration_loop import max_seconds_from_env

        self.assertIsNone(max_seconds_from_env({}))

    def test_a_zero_or_negative_time_budget_is_no_budget(self):
        from code_reviewer.infrastructure.llm.narration_loop import max_seconds_from_env

        self.assertIsNone(max_seconds_from_env({"REVIEW_MAX_SECONDS": "0"}))
        self.assertIsNone(max_seconds_from_env({"REVIEW_MAX_SECONDS": "-5"}))

    def test_an_unparseable_time_budget_disables_it_rather_than_raising(self):
        """A review tool must not fail a pipeline over a typo in an env var."""
        from code_reviewer.infrastructure.llm.narration_loop import max_seconds_from_env

        self.assertIsNone(max_seconds_from_env({"REVIEW_MAX_SECONDS": "later"}))

    def test_a_positive_time_budget_is_honoured(self):
        from code_reviewer.infrastructure.llm.narration_loop import max_seconds_from_env

        self.assertEqual(max_seconds_from_env({"REVIEW_MAX_SECONDS": "30"}), 30.0)


if __name__ == "__main__":
    unittest.main()
