"""A chat model that replays a script.

``FakeListChatModel`` used to fill this role, but it lives in
``langchain-community`` — a distribution nothing else in this project imports
and which Level 7 removed (finding G-01). It could not express the case this
level exists for either: a response carrying a structured ``tool_calls`` field,
which is how every hosted endpoint delivers a tool call.

So the stub is written here. It is a dozen lines of behaviour and it can speak
both protocols, which is the whole point.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage


def hermes_call(tool: str, **arguments: str) -> str:
    """Renders a Hermes XML tool call the way a vLLM-served model emits one."""
    parameters = "\n".join(f"<parameter={name}>\n{value}\n</parameter>" for name, value in arguments.items())
    return f"<tool_call>\n<function={tool}>\n{parameters}\n</function>\n</tool_call>"


class ScriptedChatModel:
    """Replays a fixed list of responses, recording what it was asked.

    Args:
        responses: Each entry is either a string — returned as an
            ``AIMessage`` — or an ``AIMessage`` the caller built, which is how
            a native ``tool_calls`` response is expressed.
        binding_error: Raised by :meth:`bind_tools` when set, so a test can
            model a server that does not support the tool API.
    """

    def __init__(
        self,
        responses: Sequence[str | AIMessage],
        binding_error: Exception | None = None,
    ):
        self.responses = list(responses)
        self.binding_error = binding_error

        #: Conversations passed to `invoke`, in order.
        self.calls: list[list[BaseMessage]] = []
        #: Tools passed to `bind_tools`, or None if it was never called.
        self.bound_tools: list[Any] | None = None

    def bind_tools(self, tools: Sequence[Any]) -> "ScriptedChatModel":
        if self.binding_error is not None:
            raise self.binding_error
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages: Sequence[BaseMessage], **_: Any) -> AIMessage:
        self.calls.append(list(messages))

        if not self.responses:
            raise AssertionError(
                f"The model was invoked {len(self.calls)} time(s) but the script "
                "ran out of responses. Either the loop is not terminating or the "
                "script is short."
            )

        response = self.responses.pop(0)
        return AIMessage(content=response) if isinstance(response, str) else response

    def get_num_tokens_from_messages(self, messages: Sequence[Any]) -> int:
        """A crude count, so the agent's budget arithmetic has something real."""
        return sum(len(str(getattr(m, "content", m))) for m in messages) // 4
