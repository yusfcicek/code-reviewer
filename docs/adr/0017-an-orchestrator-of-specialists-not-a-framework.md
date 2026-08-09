# 0017 — An orchestrator of specialists, not a framework

Status: Accepted
Date: 2026-08-09
Level: [15](../roadmap/level-15/spec.md)

## Context

There was one agent, with one prompt asking it to do six unrelated jobs at
once: classify the semantic change, scan for vulnerabilities, judge the
architecture, find performance problems, trace dependencies and write a report.
Every level that added a concern lengthened that prompt. Nothing could say
which of its numbered steps a given response had actually followed, budget
could not be spent where it mattered, one malformed response cost the whole
file's narration, and a security pass that noticed a dependency problem had
nowhere to send it.

The failure mode of a multi-agent system is that nobody can say what it will
do. Every decision below is aimed at that.

## Decision

### The orchestrator is a `Reviewer`

`ReviewOrchestrator` implements the port `ReviewService` already depends on.
The workflow's question is "review this file"; how many models answer it is an
implementation detail of the answer. Making the workflow aware of a committee
would push orchestration into the layer that decides verdicts, which is the
layer that has to stay boring.

Swapping one agent for four is a change to the composition root, and
`--single-agent` swaps it back.

### Everything the orchestrator decides is a pure function

Routing, the budget split, the composition order and the handoff rule all live
in `domain/orchestration.py` over enums and lists. They are answered by reading
a page, not by running a model:

- **Routing** is derived from the findings the analyzers have already
  produced, plus whether the path is a manifest. Asking a model which
  specialists to invoke would spend a call to make a decision two conditionals
  make correctly, and would make the plan unreproducible.
- **The budget split** is weighted, sums exactly to the total, and gives nobody
  zero. Security's weight is the largest, which is what makes "spend more on
  security than on style" something the system holds rather than something it
  hopes.
- **Composition** is a fixed order — architecture, security, performance,
  dependency — so two runs over the same inputs produce the same document.

### Handoff depth is one, enforced structurally

A specialist may request one other, with a written reason. The second round is
run at a depth where the domain refuses every request, so the bound is not a
counter anybody can raise or forget to decrement. Whatever four agents ask for,
the number of invocations for one file cannot exceed twice the number of
specialisms.

A handoff to a specialism already run, or to something that is not a
specialism, is refused **and recorded** — refusals are visible, in the way a
refused file read has been since Level 8.

### Tools are narrowed, not requested

Each specialism is offered its own catalogue. An agent told in English not to
use a tool is an agent that sometimes uses it; one that was never offered the
tool cannot. The trust boundary is the opposite: inherited whole by every
specialism, because it is not something one of four agents may forget.

### No framework, and no concurrency yet

LangGraph, CrewAI, AutoGen and Semantic Kernel are all named by the sources
this roadmap comes from. Level 7 removed a framework from the critical path
because its removal of `AgentExecutor` had already pinned this project to a
January 2024 dependency tree, and the loop that replaced it is 200 lines this
repository owns. Orchestration here is built against this project's own ports;
a framework, if wanted, becomes an adapter behind them.

Specialists run in sequence. Concurrency is Level 17's subject and needs Level
16's tracing to be debuggable at all — introducing it here would make every bug
in this level a race, and the first thing anyone would do when one appeared is
turn the committee off.

## Consequences

**A file costs more model calls.** One to four in the ordinary case, five with
a handoff. `--single-agent` exists because a team that wants one call per file
must be able to have it, and because the fallback is what makes the two
comparable.

**`Reviewer.review_diff` now takes a `ReviewBrief`.** It had grown one
parameter per level — the diff, the file, the siblings, the retrieved code, the
project's memory, and now the findings an orchestrator routes on. Seven
parameters is past the threshold this project's own quality analyzer enforces,
and a value object also makes the port stable: the next thing a reviewer needs
is a field, not a signature change rippling through every implementation and
every fake.

**One specialist failing costs one section.** It is recorded, stated in the
composed report, and the rest still run. A review with three sections and one
stated failure is worth far more than no review — which is the same argument
[ADR 0006](0006-a-failing-file-is-reported-not-fatal.md) makes one level up.

**The verdict is untouched.** The analyzers still run unconditionally before
any agent, and the gate still decides from their findings
([ADR 0004](0004-findings-drive-the-gate.md)). Four narrators instead of one
changes what the report says, not what the pipeline does.

**Every agent is accounted for.** Runs, failures and tool calls per specialism
reach the metrics export, and the report carries a per-file footer naming who
ran, on what budget, with what outcome, and which handoffs were refused. "Which
agent said this" is the question multi-agent review exists to make answerable,
and a system that cannot answer it has taken the cost without the benefit.
