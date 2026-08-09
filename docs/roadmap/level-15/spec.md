# Level 15 — Multi-agent orchestration

## Problem statement

There is one agent. It has one prompt, one budget and one voice, and that
prompt asks it to do six unrelated jobs at once: classify the semantic change,
scan for vulnerabilities, judge the architecture, look for performance
problems, trace dependencies, and write a report.

- **The prompt is a list of instructions the model attends to unevenly.** Every
  level that added a concern lengthened it. It now opens with a trust boundary,
  continues with an operational strategy in six numbered steps, and ends with
  an output format — and there is no way to know which of those a given
  response actually followed (C-09).
- **Budget cannot be spent where it matters.** A security-sensitive file and a
  formatting change get the same token allowance and the same number of tool
  calls, because there is one loop with one limit.
- **A failure costs everything.** One malformed response, one tool loop that
  runs out of iterations, and the whole file's narration is lost. There is no
  partial result, because there are no parts.
- **Nothing specialises.** The security instructions and the performance
  instructions sit in the same system message and offer the same tools; a
  security pass cannot be given the SAST tool and denied the ripple tracer, so
  nothing about the agent's *attention* can be directed.
- **There is no handoff.** When the security pass notices that a vulnerable
  call comes from a dependency, it has nowhere to send that; it either does the
  dependency work itself inside the same budget or drops it (C-10).

Capabilities addressed: **C-09, C-10**.

## Goals

1. Specialists exist: a security reviewer, a performance reviewer, an
   architecture reviewer, a dependency reviewer — each with its own prompt, its
   own tools and its own budget.
2. An orchestrator decides which specialists a file warrants, splits the budget
   between them, runs them, and composes one report.
3. A specialist can hand work to another, once, under a protocol that cannot
   loop.
4. One specialist failing costs that specialist's section and nothing else.
5. Every decision the orchestrator makes is attributable: which agents ran,
   why, what each cost, and what each produced.

## Non-goals

- **A framework.** LangGraph, CrewAI, AutoGen and Semantic Kernel are named by
  the sources. Level 7 removed a framework from the critical path because its
  removal of `AgentExecutor` had already pinned this project to a January 2024
  dependency tree, and the loop that replaced it is 200 lines this repository
  owns. Orchestration here is built against this project's own ports; if a
  framework is later wanted, it becomes an adapter behind them.
- **Concurrency.** Specialists run in sequence. Running them in parallel is
  Level 17's subject and needs the tracing from Level 16 to be debuggable at
  all; introducing it here would make every failure in this level a race.
- **Agents that write code, negotiate, or vote.** A specialist reviews and
  reports. There is no consensus round, no critic, no arbitration — those are
  answers to a disagreement problem this system does not have, because the
  gate decides from findings and not from prose (ADR 0004).
- **Unbounded handoff.** See C-6.
- **Replacing the analyzers.** The static analysis suite still runs
  unconditionally, before any agent, and the gate still reads its findings. The
  specialists narrate; they do not vote on the verdict.

## Behavioural contracts

### C-1 — A specialism has a scope, tools and a budget (C-09)
Four specialisms: `SECURITY`, `PERFORMANCE`, `ARCHITECTURE`, `DEPENDENCY`. Each
declares which tools it may call and how much of the file's budget it is worth.
The declaration is data, not prose in a prompt.

### C-2 — The orchestrator decides who reviews what (C-09)
Which specialists run on a file is derived from the triage decision and from
what static analysis already found: a file with security findings gets the
security specialist, a manifest gets the dependency specialist, and every
reviewed file gets the architecture specialist, which is the generalist and the
one that owns the summary.

The routing is a pure function of a decision and a list of findings. It needs
no model to test.

### C-3 — Budget is split, and the split is stated (C-09)
The file's token budget is divided between the assigned specialists by weight.
The split sums to the budget, no assigned specialist gets zero, and the numbers
appear in the report's footer, because "why did this review stop early" is a
question a budget has to be able to answer.

### C-4 — One specialist failing costs one section (C-09)
An exception, a timeout, an exhausted loop: the orchestrator records that
specialist as failed, says so in the composed report, and runs the rest. A
review with three sections and one stated failure is worth much more than no
review.

### C-5 — The composition is deterministic (C-09)
Sections appear in a fixed order — architecture first, then security,
performance, dependency — regardless of which finished first or in what order
they were assigned. Two runs over the same inputs produce the same document.

### C-6 — A handoff happens once, and cannot loop (C-10)
A specialist may request one other specialism, with a stated reason. The
orchestrator honours a request only when the target has not already run for
this file and the handoff depth is zero. That makes the protocol terminating by
construction rather than by a counter someone has to remember to increment.

A handoff to a specialism that is not recognised, or to one already run, is
recorded and refused — refusals are visible, in the way a refused file read is.

### C-7 — Every agent's cost and outcome is recorded (C-09)
Per specialism: whether it ran, whether it succeeded, how many tokens it was
allowed, how many tool calls it made, and how long it took. Exported as metrics
and summarised in the report.

### C-8 — The orchestrator is a `Reviewer` (C-09)
It implements the port `ReviewService` already depends on, so the workflow does
not learn that there is more than one agent. Swapping a single agent for a
committee is a change to the composition root and nothing else.

### C-9 — Single-agent review remains available
`--single-agent` runs exactly the Level 14 reviewer. Orchestration multiplies
the number of model calls per file; a team that wants one call per file must be
able to have it, and the fallback is also what makes the two comparable.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A file with security findings is assigned the security specialist | Unit test |
| AC-2 | A manifest is assigned the dependency specialist | Unit test |
| AC-3 | Every reviewed file is assigned the architecture specialist | Unit test |
| AC-4 | A file with no findings is assigned the architecture specialist alone | Unit test |
| AC-5 | The budget split sums to the total and gives nobody zero | Unit + property test |
| AC-6 | Sections appear in the fixed order whatever the assignment order | Unit test |
| AC-7 | A failing specialist is reported as failed and the others still run | Unit test |
| AC-8 | Every specialist failing yields a report that says so, not an exception | Unit test |
| AC-9 | A handoff to an unrun specialism runs it once | Unit test |
| AC-10 | A handoff to a specialism already run is refused and recorded | Unit test |
| AC-11 | A handoff from a handed-off agent is refused (depth 1) | Unit test |
| AC-12 | A handoff to an unknown specialism is refused and recorded | Unit test |
| AC-13 | Handoffs cannot produce an unbounded run | Property test |
| AC-14 | Each specialist is offered only its own tools | Unit test |
| AC-15 | Per-agent cost reaches the metrics export | Unit test |
| AC-16 | The orchestrator satisfies `Reviewer` and drops into `ReviewService` unchanged | Unit test |
| AC-17 | `--single-agent` reproduces the Level 14 behaviour | Unit test on the CLI |
| AC-18 | The six checks stay green, coverage holds, the eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — The orchestrator is a `Reviewer`, not a new port.** The workflow's
question is "review this file"; how many models answer it is an implementation
detail of the answer. Making `ReviewService` aware of a committee would push
orchestration into the layer that decides verdicts, which is the layer that
must stay boring.

**D-2 — Routing is derived from findings, not from the model.** The analyzers
have already run by the time the orchestrator is called, and what they found is
the best available evidence about what a file needs. Asking a model which
specialists to invoke would spend a model call to make a decision two `if`
statements can make correctly, and would make the plan unreproducible.

**D-3 — Handoff depth is one, enforced structurally.** Not "a maximum depth of
three, decremented per call" — a depth that is a number is a depth somebody
eventually raises. A handed-off agent's requests are refused because the
orchestrator only offers the handoff protocol on the first round, so no counter
can be wrong.

**D-4 — Specialists run in sequence.** Concurrency belongs to Level 17, after
Level 16 makes a trace of the whole thing readable. Introducing it here would
mean every bug in this level is a race, and the first thing anyone would do
when one appeared is turn it off.

**D-5 — Budget is split by weight, not shared.** A shared pool means the first
specialist to run can consume it. Weighted division is what makes "security
gets more than style" a statement the system can hold rather than a hope.

**D-6 — The architecture specialist owns the summary.** Some agent has to write
the sentence a reader sees first, and the generalist is the one with the whole
file in view. Composing a summary from four specialists' prose with a fifth
model call would add a call, a failure mode and a place for a hallucination to
enter with no source.
