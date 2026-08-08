"""Reading a tool call out of a model response.

The agent runs against two kinds of endpoint and they carry a tool call
differently:

======================================  ==========================================
Endpoint                                How a tool call arrives
======================================  ==========================================
On-prem vLLM with a Hermes template     XML inside the message text
OpenAI, Groq, most hosted APIs          a structured ``tool_calls`` field
======================================  ==========================================

Supporting only one of them is worse than it looks. The agent previously read
Hermes XML and never bound tools natively, so against a hosted endpoint the
model was offered no tools at all — and rather than saying so, it produced a
review *describing* scans it had not run (finding G-02). A parser that reads
both is what lets the binding strategy be `auto`, because whichever way the
call comes back, it is understood.

The structured field wins when both are present: a server that negotiated the
tool API is the authority on what was called.
"""

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

#: ``<tool_call><function=NAME> … </function></tool_call>``, non-greedy so the
#: first complete call wins when a model emits several.
_CALL = re.compile(
    r"<tool_call>\s*<function=(?P<name>[^>]+?)>(?P<body>.*?)</function>\s*</tool_call>",
    re.DOTALL,
)

#: ``finditer``, not ``search``: every parameter block counts. Matching one was
#: the defect — a two-argument call silently lost its second argument.
_PARAMETER = re.compile(r"<parameter=(?P<key>[^>]+?)>(?P<value>.*?)</parameter>", re.DOTALL)

#: Empty mapping shared by argument-less invocations. A module-level immutable
#: default costs nothing and cannot be mutated by a caller.
_NO_ARGUMENTS: Any = MappingProxyType({})


@dataclass(frozen=True)
class ToolInvocation:
    """A tool the model asked for, with the arguments it passed."""

    name: str
    arguments: dict = field(default_factory=dict)

    #: Present only on a native call. The tool's result must be returned as a
    #: ``ToolMessage`` carrying this id, or the server rejects the conversation
    #: as having an unanswered call.
    call_id: str | None = None


@dataclass(frozen=True)
class FinalAnswer:
    """The model stopped calling tools and produced its review."""

    text: str


def response_text(response: Any) -> str:
    """The textual content of a model response, whatever shape it arrived in.

    Providers return ``content`` as a string, or as a list of typed blocks.
    Both have to reduce to something the Hermes matcher can search and the
    caller can publish.
    """
    content = getattr(response, "content", response)

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [block.get("text", "") if isinstance(block, dict) else str(block) for block in content]
        return "".join(parts)
    return str(content)


class ToolCallParser:
    """Turns a model response into either a tool invocation or a final answer."""

    def parse(self, response: Any) -> ToolInvocation | FinalAnswer:
        native = self._native(response)
        if native is not None:
            return native

        return self._hermes(response_text(response))

    # -- native -------------------------------------------------------------

    @staticmethod
    def _native(response: Any) -> ToolInvocation | None:
        """Reads the structured field, or returns ``None`` if there is none."""
        calls = getattr(response, "tool_calls", None)
        if not calls:
            return None

        call = calls[0]
        return ToolInvocation(
            name=call["name"],
            arguments=dict(call.get("args") or {}),
            call_id=call.get("id"),
        )

    # -- hermes -------------------------------------------------------------

    @staticmethod
    def _hermes(text: str) -> ToolInvocation | FinalAnswer:
        """Reads XML out of the message text, or treats the text as the answer.

        A malformed call — an unclosed tag, a truncated response — is a final
        answer rather than an error. The model is the one that produced it, and
        raising here would cost the file its review over the model's typo.
        """
        text = text.strip()

        match = _CALL.search(text)
        if match is None:
            return FinalAnswer(text)

        arguments = {
            parameter.group("key").strip(): parameter.group("value").strip()
            for parameter in _PARAMETER.finditer(match.group("body"))
        }

        return ToolInvocation(
            name=match.group("name").strip(),
            arguments=arguments or dict(_NO_ARGUMENTS),
        )
