"""The loop that drives the model and its tools.

LangChain 1.0 removed ``AgentExecutor``. Its replacement, ``create_agent``,
assumes native tool calling and offers no hook for parsing a call out of
message text, so adopting it would mean dropping the on-prem vLLM/Hermes path
the parser was written for. That is what held this project on LangChain 0.1
(finding F-45).

The loop itself is small — call the model, run the tool it asked for, feed the
result back, repeat under a cap. In this architecture the model is only a
*narrator*: the gate verdict comes from deterministic static analysis, so there
is no graph engine to justify. Keeping the loop in-tree makes both protocols
first-class and decouples the agent from framework churn.
"""

import os
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from .tool_calls import FinalAnswer, ToolCallParser, ToolInvocation, response_text

#: Tool rounds allowed for one file. A model that keeps asking for tools is
#: either exploring usefully or stuck; ten rounds distinguishes them cheaply.
DEFAULT_MAX_ITERATIONS = 10

#: Longest tool result handed back. Beyond this the observation crowds out the
#: diff it is supposed to explain.
DEFAULT_MAX_OBSERVATION_CHARS = 8_000

#: The wall-clock budget is OFF by default, and that is a decision rather than
#: an omission.
#:
#: A review with tools reads files and runs scans; that can take minutes.
#: Cutting it off part-way produces an incomplete report with nothing in the
#: output saying which analysis it did not reach — a quiet wrong answer, and
#: one that errs towards approval.
#:
#: The loop is still bounded without it: the iteration cap above and the
#: provider's per-request HTTP timeout keep the worst case finite. An operator
#: who needs a hard ceiling sets ``REVIEW_MAX_SECONDS``.
DEFAULT_MAX_SECONDS: float | None = None


def max_iterations_from_env(
    environment: Mapping[str, str] | None = None,
    variable: str = "REVIEW_MAX_ITERATIONS",
) -> int:
    """Reads the iteration cap, falling back to the default on nonsense."""
    raw = (environment if environment is not None else os.environ).get(variable, "").strip()
    if not raw:
        return DEFAULT_MAX_ITERATIONS

    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ITERATIONS

    return value if value > 0 else DEFAULT_MAX_ITERATIONS


def max_seconds_from_env(
    environment: Mapping[str, str] | None = None,
    variable: str = "REVIEW_MAX_SECONDS",
) -> float | None:
    """Reads the time budget. Unset, empty, zero or unparseable means no budget.

    Disabling on a bad value rather than raising is deliberate: a review tool
    should not fail someone's pipeline over a typo in an environment variable,
    and the fallback here is the *safer* behaviour, not the more permissive one.
    """
    raw = (environment if environment is not None else os.environ).get(variable, "").strip()
    if not raw:
        return None

    try:
        value = float(raw)
    except ValueError:
        return None

    return value if value > 0 else None


class NarrationLoop:
    """Runs the model with its tools, under a bound.

    Args:
        model: Anything with ``invoke(messages)`` returning a message. The
            model is expected to have had its tools bound already, when the
            protocol calls for it.
        tools: Tools the model may call, by name.
        parser: Reads a response as a tool call or a final answer.
        max_iterations: Tool rounds allowed before the loop gives up.
        max_seconds: Wall-clock budget, or ``None`` for none.
        max_observation_chars: Truncation threshold for a tool result.
        clock: Monotonic time source, injected so a test is not at the mercy
            of real timing.
        log: Called with a printf-style message and arguments.
    """

    def __init__(
        self,
        model: Any,
        tools: Sequence[Any],
        parser: ToolCallParser | None = None,
        max_iterations: int | None = None,
        max_seconds: float | None = DEFAULT_MAX_SECONDS,
        max_observation_chars: int = DEFAULT_MAX_OBSERVATION_CHARS,
        clock: Callable[[], float] | None = None,
        log: Callable[..., None] | None = None,
    ):
        self.model = model
        self.tools = {tool.name: tool for tool in tools}
        self.parser = parser or ToolCallParser()
        self.max_iterations = max_iterations if max_iterations is not None else DEFAULT_MAX_ITERATIONS
        self.max_seconds = max_seconds
        self.max_observation_chars = max_observation_chars
        self.clock = clock or time.monotonic
        self.log = log or (lambda *args, **kwargs: None)

        #: Tool calls made during the most recent `run`. Per-agent accounting
        #: needs a number, and counting them here is the only place that knows
        #: (Level 15, contract C-7).
        self.last_tool_call_count = 0

    # -- api ----------------------------------------------------------------

    def run(self, messages: Sequence[BaseMessage]) -> str:
        """Drives the conversation and returns the model's last text.

        The caller's list is copied: the same starting messages are reused
        across files, and a loop that appended to them would carry one file's
        tool transcript into the next file's prompt.
        """
        conversation = list(messages)
        deadline = None if self.max_seconds is None else self.clock() + self.max_seconds
        last_text = ""
        self.last_tool_call_count = 0

        for iteration in range(self.max_iterations):
            if deadline is not None and self.clock() >= deadline:
                self.log("Narration stopped: time budget of %.0fs exhausted", self.max_seconds)
                break

            response = self.model.invoke(conversation)
            last_text = response_text(response)

            parsed = self.parser.parse(response)
            if isinstance(parsed, FinalAnswer):
                return parsed.text

            self.last_tool_call_count += 1
            self.log("Tool call %d: %s", iteration + 1, parsed.name)
            observation = self._execute(parsed)

            conversation.append(response)
            conversation.append(self._observation_message(parsed, observation))
        else:
            self.log("Narration stopped: iteration limit of %d reached", self.max_iterations)

        return last_text

    # -- internals ----------------------------------------------------------

    def _execute(self, invocation: ToolInvocation) -> str:
        """Runs the tool, returning its output or a description of the failure.

        Neither an unknown name nor a raising tool ends the loop. The model is
        the one that got it wrong and it can be told so; raising here would
        cost the file its entire review over one bad call.
        """
        tool = self.tools.get(invocation.name)
        if tool is None:
            known = ", ".join(sorted(self.tools)) or "(none)"
            return f"Error: unknown tool {invocation.name!r}. Available tools: {known}"

        try:
            result = tool.invoke(invocation.arguments)
        except Exception as exc:
            self.log("Tool %s failed: %s", invocation.name, exc)
            return f"Error: tool {invocation.name!r} failed: {exc}"

        return self._truncate(result if isinstance(result, str) else str(result))

    def _truncate(self, text: str) -> str:
        if len(text) <= self.max_observation_chars:
            return text

        omitted = len(text) - self.max_observation_chars
        return text[: self.max_observation_chars] + f"\n[... truncated: {omitted} characters omitted ...]"

    @staticmethod
    def _observation_message(invocation: ToolInvocation, observation: str) -> BaseMessage:
        """Wraps a tool result in the message shape its protocol requires.

        A native call must be answered by a ``ToolMessage`` carrying the call
        id; a server that sees an unanswered tool call rejects the whole
        conversation. The Hermes dialect has no such id, so the result goes
        back as ordinary text.
        """
        if invocation.call_id:
            return ToolMessage(content=observation, tool_call_id=invocation.call_id)

        return HumanMessage(content=f"<tool_response>\n{observation}\n</tool_response>")
