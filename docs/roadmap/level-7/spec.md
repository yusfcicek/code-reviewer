# Level 7 — Dependency and Tool-Protocol Upgrade

## Problem statement

The agent's tool machinery works against exactly one kind of endpoint, and the
dependency stack that carries it is two years old.

- **The model is never offered any tools.** `ReviewAgent` builds an
  `AgentExecutor` around a Hermes XML output parser and never calls
  `bind_tools`. Against an endpoint that carries tool calls in the structured
  `tool_calls` field — OpenAI, Groq, most hosted APIs — the model receives no
  tool schema at all. It cannot call a tool, so it does the next best thing:
  it writes a review that *describes* running one. "SAST Scan Result: FAIL"
  produced by looking at the diff is indistinguishable, in the report, from
  the same line produced by a scan (G-02).
- **A two-argument tool call loses an argument.** The parser's regex matches a
  single `<parameter=...>` block (`review_agent.py:112-116`). `grep_search`
  and `find_references` both take two parameters, so the second is silently
  dropped and the tool runs against a default the model did not ask for
  (G-02).
- **The dependency stack is pinned to January 2024.** `langchain==0.1.0`,
  `langchain-community==0.0.10`, `langchain-openai==0.0.2`,
  `openai==1.12.0`. `langchain-community` is declared but imported nowhere in
  `code_reviewer/`; it exists only to satisfy one test import, and it drags in
  `aiohttp`, `SQLAlchemy` and `dataclasses-json` (G-01).
- **Nothing measures that.** CI runs lint, format, types and tests. No
  dependency audit, so the state above is not a known quantity — it is an
  unknown one (G-15).
- **The loop's bounds are source constants.** `MAX_TOOL_ITERATIONS = 10` and
  `MAX_OUTPUT_CHARS = 2000` cannot be changed by an operator, and the right
  value for the second depends on the served model's context window, which is
  deployment knowledge (G-14).

The four are one level because they are one problem: the upgrade in G-01 is
blocked by `AgentExecutor`, which LangChain 1.0 removed and whose replacement
`create_agent` exposes no output-parser hook. This is exactly what
[F-45](../findings.md) recorded as deferred. Owning the loop is what unblocks
it.

Gaps addressed: **G-01, G-02, G-14, G-15**. Closes deferred finding **F-45**.

## Goals

1. A tool call reaches its tool on both kinds of endpoint, with every argument
   intact.
2. The project owns its tool loop, so a framework release cannot remove it.
3. The dependency surface is current, minimal, and measured on every push.
4. The loop's bounds are operator-settable, with defaults that state their
   reasoning.

## Non-goals

- **Changing what the agent decides.** The gate verdict comes from static
  analysis and this level does not touch an analyzer. A review run before and
  after must reach the same verdict on the same input.
- **Agent frameworks.** LangGraph, `create_agent` and their relatives are not
  adopted. The loop is ~120 lines; the dependency is not worth it.
- **Streaming, parallel tool calls, or multi-tool turns.** One tool per turn,
  as today. A model that requests several gets the first honoured.

## Behavioural contracts

### C-1 — Tool calls are understood in both protocols (G-02)
A single parser reads a model response and returns either a tool invocation or
a final answer. The structured `tool_calls` field takes priority; when it is
absent the response text is searched for Hermes XML. A response carrying both
is treated as a native call, because that is the one the server negotiated.

### C-2 — Every parameter of a tool call survives (G-02)
A Hermes call with N `<parameter=...>` blocks produces a tool invocation with N
arguments. The one-parameter case is a special case of this, not the only case.

### C-3 — Tools are bound according to a declared protocol (G-02)
`REVIEW_TOOL_PROTOCOL` selects how tools are offered:

| Value | Behaviour |
|---|---|
| `auto` (default) | Bind natively; fall back to prompt-based Hermes if the model or server refuses |
| `native` | Bind natively; raise if unsupported |
| `hermes` | Never bind; the catalogue in the prompt is the only offer |
| `none` | No tools; the model narrates from the diff alone |

`auto` is safe precisely because C-1 holds: whichever way the call arrives, the
parser reads it.

### C-4 — The loop is bounded and says when it stopped early (G-14)
Iterations are capped (`REVIEW_MAX_ITERATIONS`, default 10). A tool observation
longer than `REVIEW_MAX_OBSERVATION_CHARS` (default 8000) is truncated with a
marker naming how much was dropped. A wall-clock budget exists
(`REVIEW_MAX_SECONDS`) but is **off by default**: an analysis cut off part-way
produces an incomplete report that does not say it is incomplete, and a quiet
wrong answer is worse than a slow one. The iteration cap and the provider's
HTTP timeout keep the worst case finite regardless.

### C-5 — A tool failure is reported to the model, not raised (G-02)
An unknown tool name or a tool that raises produces an observation describing
the problem and, for an unknown name, listing the available tools. One bad call
must not cost the file its review.

### C-6 — The dependency surface is current and measured (G-01, G-15)
`langchain-community` is gone. LangChain, `langchain-openai` and `openai` are on
their current majors. CI runs a dependency audit that distinguishes a real
advisory from a network failure: a finding fails immediately, a transport error
retries with backoff. The audit's suppression list is empty; adding to it
requires a written reason in `SECURITY.md`.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A native `tool_calls` response invokes the tool with its arguments | Unit test on the parser and the loop |
| AC-2 | A Hermes XML response invokes the tool with its arguments | Unit test |
| AC-3 | A two-parameter Hermes call arrives with both parameters | Unit test (this fails today) |
| AC-4 | A response with no tool call ends the loop and returns its text | Unit test |
| AC-5 | An unknown tool name yields an observation naming the known tools | Unit test |
| AC-6 | A tool that raises yields an observation, and the loop continues | Unit test |
| AC-7 | `REVIEW_TOOL_PROTOCOL=native` raises when binding is unsupported; `auto` falls back | Unit test |
| AC-8 | An observation over the limit is truncated with a marker | Unit test |
| AC-9 | The end-to-end agent path works in both dialects against a scripted model | Integration test |
| AC-10 | `langchain-community` appears nowhere in `pyproject.toml` or the test suite | Grep, plus the dependency test |
| AC-11 | `pip-audit` runs in CI and reports no advisory, with an empty ignore list | `scripts/audit-deps.sh` in the pipeline |
| AC-12 | The four existing checks stay green and coverage holds at its floor | `ruff`, `mypy`, `pytest --cov` |

## Decisions taken

**D-1 — The loop lives in this repository.** LangChain 1.0 removed
`AgentExecutor` and offered `create_agent`, which assumes native tool calling
and provides no hook for parsing a tool call out of message text. Adopting it
would mean dropping the on-prem vLLM/Hermes path — the deployment the Hermes
parser was written for in the first place. The loop is small: call the model,
run a tool, feed the observation back, repeat under a cap. Owning it makes both
protocols first-class and decouples the agent from framework churn. This
supersedes ADR [0007](../../adr/0007-langchain-pinned.md).

**D-2 — Native binding is preferred, Hermes is the fallback.** When a server
supports the tool API, using it is strictly better: the schema is enforced by
the server, arguments arrive typed, and no prompt real estate is spent on a
catalogue. Hermes exists for servers that do not, and `auto` picks between them
by trying. The parser reading both is what makes trying safe.

**D-3 — No default wall-clock budget.** A time limit that fires produces a
report missing the analysis it did not reach, with nothing in the output saying
so. The failure is silent and the direction of the error is towards *approval*.
An operator who needs a ceiling can set one; the default is a bounded number of
iterations rather than a bounded number of seconds.

**D-4 — The old parser and executor are deleted, not deprecated.** Keeping
`HermesToolOutputParser` and `AgentExecutor` alongside the new loop would leave
two code paths where only one is exercised. The integration test is rewritten
against the new loop first; the old path is removed once it passes.

**D-5 — The audit script distinguishes advisories from network failures.**
`pip-audit` exits `1` for both. A blocking CI step that cannot tell them apart
is marked `allow_failure: true` by the first team it inconveniences, and at that
point the audit means nothing. Retrying a transport error is not leniency; it
is the difference between a signal and a coin flip.

**D-6 — The scripted model in tests is written here, not imported.**
`FakeListChatModel` lives in `langchain-community`, which this level removes,
and it cannot produce a response carrying a structured `tool_calls` field
anyway. A stub that replays a scripted list of responses is a dozen lines and
can express both protocols.
