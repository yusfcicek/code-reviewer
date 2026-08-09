# Level 16 — Tracing & agent observability

## Problem statement

Level 15 turned one agent into as many as five per file, each with its own
tools, its own budget and its own failure mode. Level 13 added a retrieval
pipeline in front of them and Level 14 a memory beside them. The system now has
depth, and nothing can see into it.

What exists is structured logging and an OpenMetrics export. Both are flat.

- **Nothing says which agent did what.** The log records "Tool call 3:
  grep_search" and, four lines later, "Reviewing file". Which specialist made
  that call, on whose budget, in service of which file, is not recorded
  anywhere — and after Level 15 that is the first question anybody asks (C-12).
- **Nothing says where the time went.** `code_review_duration_ms` is a total.
  A review that took ninety seconds could have spent them on four model calls,
  on one retrieval that scanned the wrong tree, or on a tool loop that ran to
  its iteration limit. The metric cannot tell them apart, so nobody can make
  the review faster except by guessing.
- **A log line and a metric cannot be joined.** There is no identifier common
  to both, and none shared between two records of the same run. Two reviews
  interleaved in one log stream — which is what a runner with two jobs
  produces — are indistinguishable.
- **A failure has no context.** "Specialist failed: TimeoutError" is true and
  useless. What it had already read, how far into its budget it was, and what
  the orchestrator did next are all knowable and none of them are recorded.
- **Level 17 cannot start.** Concurrency was deferred out of Level 15 on the
  explicit grounds that tracing has to come first, because a race in a
  committee of five is not debuggable from a flat log.

Capabilities addressed: **C-12**.

## Goals

1. One review produces one trace: a tree of spans covering the run, each file,
   each agent, each tool call, each retrieval and each memory access.
2. Every span carries what it was, how long it took, whether it succeeded, and
   a few identifying attributes.
3. Every log record carries the trace and span it belongs to, so a log line and
   a trace can be joined.
4. The trace is readable by a person in the CI log, and exportable as JSON for
   anything else.
5. Tracing is free when off and cheap when on, and it can never fail a review.

## Non-goals

- **An OpenTelemetry dependency.** OTel is the obvious answer and this level
  does not take it. The SDK plus an exporter is a large dependency tree in a
  process whose entire job is to be trustworthy, and this project has spent a
  level already on what a framework in the critical path costs (Level 7). A
  `TraceExporter` port is declared and a JSON exporter ships behind it; an OTLP
  adapter is a sibling module and nothing else changes.
- **Distributed context propagation.** One review is one process. There is no
  second service to propagate to, and W3C `traceparent` headers with nobody to
  send them to are ceremony.
- **Sampling.** A review is not a request stream. Every run is traced or none
  is, and the switch is a flag.
- **Timing the analyzers' internals.** The static analysis suite is one span.
  Instrumenting five analyzers' recursion would produce a trace nobody reads
  to answer a question nobody has.
- **Attributes that carry the diff.** See C-6.

## Behavioural contracts

### C-1 — A trace is a tree of spans (C-12)
A span has an identifier, a parent, a kind, a name, a start, an end, a status
and attributes. Spans with a common trace identifier form one tree, rooted at
the span with no parent.

### C-2 — The tree survives bad input (C-12)
A span whose parent is not in the trace is attached to the root, and the fact
is recorded rather than hidden. A parent chain that loops is broken and
recorded. Neither raises, and neither can make tree-building fail to terminate:
a tracer that hangs on its own output is worse than no tracer.

### C-3 — Self time is duration minus children (C-12)
The number that answers "where did the time go" is not a span's duration —
that includes everything below it — but its own share. Computed, floored at
zero, and reported per kind so "40 % of this review was tool calls" is a
sentence the system can produce.

### C-4 — Every log record carries its trace and span (C-12)
The logging configuration adds the current trace and span identifiers to every
record, in both the human and the JSON format. That is the join between a log
line and a trace, and it is what makes two interleaved reviews separable.

### C-5 — A span records failure without swallowing it (C-12)
An exception inside a span marks it `ERROR`, records the exception type, and
propagates. Tracing observes; it does not handle.

### C-6 — Attributes are identifiers, not content (C-12)
A span may carry a path, a rule id, an agent name, a tool name, a count, a
budget. It may not carry a diff, a file's contents, a model's prose or a
finding's evidence. The same rule Level 14 applied to the memory file, for the
same two reasons: a trace is written to a CI artefact anyone with pipeline
access can read, and a diff may contain a secret.

### C-7 — Tracing cannot fail a review (C-12)
An exporter that cannot write, a clock that goes backwards, a span closed
twice: each is logged and the review proceeds. This is retrieval's rule and
memory's rule, for the third time and for the same reason — an observability
feature that can break the thing it observes is a liability.

### C-8 — Off by default in cost, on by default in value
The tracer is always recording in memory, because a trace nobody asked for is
the one they want after a failure, and the in-memory cost is a list of small
frozen objects. Writing it out is what the flag controls: `--trace-path` names
a file, and the report carries a bounded rendering either way.

### C-9 — The rendering is bounded and deterministic
The trace in the merge-request comment is capped by depth and by node count,
with the omission stated. Two runs over identical inputs produce identical
trees apart from their timings.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | Spans with a common trace id build one tree, rooted correctly | Unit test |
| AC-2 | An orphan span attaches to the root and is recorded as orphaned | Unit test |
| AC-3 | A cyclic parent chain is broken, recorded, and terminates | Unit + property test |
| AC-4 | Self time equals duration minus children, floored at zero | Unit + property test |
| AC-5 | Totals per kind sum to no more than the root's duration | Property test |
| AC-6 | A span that ends before it starts is refused | Unit test |
| AC-7 | An exception inside a span marks it ERROR and propagates | Unit test |
| AC-8 | Trace and span ids appear in both log formats | Unit test |
| AC-9 | Nested spans nest, and siblings do not | Unit test on the tracer |
| AC-10 | A span closed twice is logged and ignored | Unit test |
| AC-11 | The review path produces spans for run, file, analysis, retrieval, memory | Unit test on the service |
| AC-12 | The orchestrator produces one span per agent, with its budget | Unit test |
| AC-13 | Tool calls produce one span each, named by tool | Unit test on the loop |
| AC-14 | No attribute anywhere carries diff or file content | Unit test over the whole path |
| AC-15 | The rendered tree is bounded and states what it omitted | Unit test |
| AC-16 | The JSON export round-trips and names every span | Unit test |
| AC-17 | An exporter that raises does not fail the review | Unit test |
| AC-18 | `--trace-path` writes the file; without it nothing is written | Unit test on the CLI |
| AC-19 | The six checks stay green, coverage holds, the eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — The trace model is in the domain; the clock is not.** What a span is,
how a tree is built from a flat list, what self time means and how a cycle is
broken are all arithmetic over values. The clock, the identifiers and the
recording are an adapter's business.

**D-2 — No OpenTelemetry.** Stated as a decision rather than an omission,
because it is the thing every reader will ask about. The port exists precisely
so the answer can change without the review path changing.

**D-3 — The tracer is passed explicitly, except into the tools.** The workflow,
the orchestrator and the agents receive a tracer through their constructors,
which is how everything else in this project is wired. The tool layer already
holds its workspace and its retriever in module globals for the same
reason — a LangChain tool is a plain function with nowhere for a dependency to
live — and the tracer joins them there rather than inventing a second pattern.

**D-4 — Recording is always on; exporting is a flag.** A trace nobody asked for
is the one they want after a failure. The in-memory cost is a bounded list of
frozen dataclasses; the cost that is worth a flag is writing a file.

**D-5 — Attributes are a closed vocabulary.** Not "avoid putting secrets in
attributes" as advice, but a test that walks a real review's spans and asserts
no attribute value contains the diff. Advice does not survive a level.

**D-6 — Identifiers are counters, not UUIDs.** A trace of forty spans in a
single process needs identifiers that are unique within the trace and readable
in a log line. `1.4.2` beats a hex string nobody can compare by eye, and it
also makes the tree's shape visible in a flat log.
