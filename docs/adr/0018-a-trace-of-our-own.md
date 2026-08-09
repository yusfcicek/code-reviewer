# 0018 — A trace of our own

Status: Accepted
Date: 2026-08-09
Level: [16](../roadmap/level-16/spec.md)

## Context

Level 15 turned one agent into as many as five per file. Level 13 put a
retrieval pipeline in front of them and Level 14 a memory beside them. What
existed to see into that was structured logging and an OpenMetrics export, and
both are flat.

The log said "Tool call 3: grep_search" without saying which specialist made
it, on whose budget, for which file. `code_review_duration_ms` said ninety
seconds without saying whether they went on four model calls, one retrieval
that scanned the wrong tree, or a loop that ran to its iteration limit. No
identifier joined a log line to a metric, or one record of a run to another —
so two reviews interleaved in one runner's output were indistinguishable.

And Level 17 was deferred out of Level 15 on the explicit grounds that a race
in a committee of five is not debuggable from a flat log.

## Decision

### No OpenTelemetry

This is the thing every reader will ask about, so it is the first decision
rather than an omission at the bottom.

OTel is the industry answer and this level does not take it. The SDK plus an
exporter is a large dependency tree in a process whose entire job is to be
trustworthy, and Level 7 already spent itself on what a framework in the
critical path costs: `AgentExecutor` disappearing in LangChain 1.0 had pinned
this repository to a January 2024 dependency tree until the loop moved in-tree.

What ships instead is 150 lines of domain and 60 of recorder. `TraceExporter`
is a port precisely so this decision can be reversed without the review path
changing: an OTLP adapter is a sibling of the JSON one.

Distributed propagation is out for a simpler reason — one review is one
process, and `traceparent` headers with nobody to send them to are ceremony.

### The model is in the domain; the clock is not

What a span is, how a tree is built from a flat list, what self time means and
how a cycle is broken are all arithmetic over values. They are tested against
literals, including every case that would otherwise be discovered in
production: an orphan, a two-span cycle, a three-span cycle, a span that is its
own parent, two roots, and a clock that moved backwards.

Nothing is lost to any of them. An orphan attaches to the root, a cycle is
broken, a second root is adopted — each recorded as an *anomaly* rather than
hidden, because dropping a span because its parent is missing loses exactly the
information somebody is looking for.

### Self time, not duration

A parent's duration includes everything below it, which is the number that
hides where the time went. Every node reports its own share — duration minus
its children's, floored at zero — and the totals are reported per kind, so
"40 % of this review was tool calls" is a sentence the system produces rather
than one somebody estimates from a log.

### Identifiers are dotted counters

`1.4.2`, not a hex string. Forty spans in one process need identity that is
unique within the trace and comparable by eye, and a dotted counter also makes
the tree's shape visible in a flat log line — which is the format anyone
actually reads under CI.

### Attributes are a closed vocabulary, enforced

A path, a rule id, an agent, a tool, a count, a budget. Never a diff, a file's
contents, a model's prose or a finding's evidence.

Enforced twice: a `Span` refuses an attribute longer than 200 characters at
construction, and a test runs a real review whose diff contains a
credential-shaped string in three places and asserts it appears in no
attribute and no span name. Advice does not survive a level; a trace is written
to an artefact anyone with pipeline access can read, and a diff may contain a
secret — the same two reasons Level 14 gave for the memory file.

### Recording is always on; writing is a flag

A trace nobody asked for is the one they want after a failure, and the
in-memory cost is a list of small frozen dataclasses. `--trace-path` controls
writing a file. The tree is summarised in the log either way.

## Consequences

**The architecture test found the first attempt.** `ReviewService` imported the
recorder from `infrastructure` directly, which is the one direction the
dependency rule forbids, and the check that parses every module's imports said
so before a human did. The interface moved to `application/tracing.py`; the
recorder stayed where it was. It is the third time in six levels that a guard
this project wrote has caught this project.

**The trace is not in the merge-request comment.** The spec said it would be,
and implementation disagreed: the trace is only complete *after* the comment
has been rendered, and building the comment twice to include a picture of
building it once is a knot with no payoff. The comment names the trace id in
its footer; the tree goes to the log and to the artefact. Recorded here rather
than quietly done, like Level 14's reversal on the memory index.

**Every log record inside a review carries `trace_id` and `span_id`**, in both
the human and the JSON format, added by a filter on the handler rather than the
logger — a logger filter does not run for records that propagate up from a
child, and every module here logs through its own child logger.

**Nothing here can fail a review.** A clock that goes backwards is clamped, a
span finished twice is logged and ignored, an exporter that cannot write is a
warning. An exception *inside* a span marks it and propagates: tracing
observes, it does not handle.

**Level 17 is now possible.** Concurrency needed a causal record before it
needed anything else, and this is it.
