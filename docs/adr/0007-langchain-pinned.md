# 7. LangChain is held at 0.1.x

- **Status**: Superseded by [0009](0009-agent-loop-in-tree.md)
- **Level**: [5](../roadmap/level-5/spec.md)

## Context

`langchain==0.1.0`, `langchain-community==0.0.10` and `langchain-openai==0.0.2`
are early-2024 releases. Old pins are a finding in their own right (F-45).

LangChain 0.2 relocated `AgentExecutor` and reworked the prompt and scratchpad
APIs. `infrastructure/llm/review_agent.py` is written directly against those:
the Hermes tool catalogue rendered into the system prompt, the scratchpad
formatter that speaks the same dialect as the output parser, and the executor
that drives them.

## Decision

The pins stay, and each carries a comment saying why. The upgrade is recorded in
the roadmap as deferred work with its own scope, not left as an unexplained old
pin.

An upgrade needs its own spec, its own contracts and a run against a live model:
the tool loop's integration test uses a scripted model, which will keep passing
while the real dialect breaks.

## Consequences

- The project runs on a two-year-old framework release, with the security
  implications that carries for anything LangChain reaches. It reaches the model
  endpoint and nothing else.
- "It is old" is a finding; "it is old and here is exactly what blocks it" is a
  decision someone can act on.
- The status is *revisit*: this ADR is expected to be superseded.

## Superseded

Level 7 removed the blocker by moving the tool loop into this repository
(ADR [0009](0009-agent-loop-in-tree.md)), and the upgrade to LangChain 1.x
followed with no source change. The pins are gone; the record stays,
because "why was this old" is a question the answer outlives.
