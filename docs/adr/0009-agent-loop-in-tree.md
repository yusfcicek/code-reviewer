# 9. The agent's tool loop lives in this repository

- **Status**: Accepted
- **Level**: [7](../roadmap/level-7/spec.md)
- **Supersedes**: [0007](0007-langchain-pinned.md)

## Context

The agent runs against two kinds of endpoint, and they carry a tool call
differently. An on-prem vLLM served with a Hermes template puts XML in the
message text. OpenAI, Groq and every other hosted API put a structured
`tool_calls` field on the message.

`AgentExecutor` drove the first of those and nothing else, because the agent
never called `bind_tools`. Against a hosted endpoint the model was handed no
tool schema at all — and rather than saying so, it produced a review
*describing* scans it had not run (G-02).

Fixing that under `AgentExecutor` was not possible for long: LangChain 1.0
removed it. Its replacement, `create_agent`, assumes native tool calling and
exposes no hook for parsing a call out of message text, so adopting it would
have meant dropping the Hermes path — the deployment the parser was written for
in the first place. That is what [ADR 0007](0007-langchain-pinned.md) recorded
as the blocker, and what held the project on a January-2024 dependency stack
carrying 59 known advisories.

## Decision

The loop is ours. `infrastructure/llm/narration_loop.py` calls the model, runs
the tool it asked for, feeds the result back and repeats under a cap.
`infrastructure/llm/tool_calls.py` reads a response as either protocol,
preferring the structured field when both are present.

`REVIEW_TOOL_PROTOCOL` decides how tools are offered — `auto`, `native`,
`hermes` or `none` — and `auto` is only safe because the parser reads both
dialects: binding can be attempted and fallen back from without silently losing
the tools.

This is affordable because of [ADR 0004](0004-findings-drive-the-gate.md): the
model is a *narrator* here, and the verdict comes from static analysis. A
component that cannot change the decision does not need a graph execution
engine behind it.

## Consequences

- The upgrade to LangChain 1.x needed no source change and closed all 59
  advisories. The dependency this project cannot leave is `langchain-core`'s
  message and tool types, which is a much smaller surface than an agent
  framework.
- Both protocols are first-class and both are tested end to end. A regression
  in either shows up as a failing test rather than as a plausible-looking
  review of scans that never ran.
- ~250 lines of loop and parser are this project's to maintain. That is the
  price, and it is paid in a place where the behaviour is small enough to
  state as contracts.
- An unrecognised `REVIEW_TOOL_PROTOCOL` raises at construction rather than
  defaulting. A typo that silently produced a tool-less review would be the
  original defect arriving through a different door.
