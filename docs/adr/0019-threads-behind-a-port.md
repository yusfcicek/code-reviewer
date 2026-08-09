# 0019 — Threads behind a port, not `asyncio`

Status: Accepted
Date: 2026-08-09
Level: [17](../roadmap/level-17/spec.md)

## Context

Level 15 multiplied the model calls per file by four and did nothing about
their arrangement, because concurrency was explicitly deferred: a race in a
committee of five is not debuggable from a flat log. Level 16 built the causal
record that removed the objection.

Everything in a review is sequential, and almost all of it is waiting. Four
specialists that each spend two seconds blocked on an inference endpoint take
eight seconds, and the CPU is idle for all eight.

## Decision

### Threads behind a `TaskRunner` port, not `asyncio`

`asyncio` is the obvious answer and this is not it.

Going async would turn every port in this repository — `CodeForge`,
`Reviewer`, `Specialist`, `StaticAnalysis`, `CodeRetriever`, `MemoryStore` —
`async`, and every implementation and every fake with them. The two clients in
the critical path are synchronous anyway: `python-gitlab` and LangChain's
`ChatOpenAI.invoke`. What `asyncio.to_thread` would do implicitly behind that
interface change, a thread pool does explicitly behind one small port.

`TaskRunner.run_all` takes callables and returns one outcome each, **in the
order given**. `SequentialRunner` is the default and is exactly the
pre-Level-17 behaviour; `ThreadPoolRunner` changes the wall clock and nothing
else. If an async-native model client ever becomes the norm here, it arrives as
a third adapter rather than as a rewrite.

A process pool is not the answer either: the work is I/O-bound, threads release
the GIL across a socket read, and pickling is a cost this problem does not have.

### Order is by plan, not by completion

The futures list *is* the plan, and it is collected in submission order. That
is what makes the composed report, the per-agent accounting and the verdict
byte-identical under either runner — asserted as equalities rather than
described, because that is the only honest way to claim a concurrency change
changed nothing else.

Level 15's fixed composition order is what makes this cheap. This level does
not weaken it.

### Files stay sequential

`ReviewOutcome`, the metrics list, the report sections and the project memory's
observations are all appended to per file, and rendered in order. Making that
aggregate thread-safe *and* deterministic is a level's worth of work for a
smaller win than the per-file fan-out, which is where the model calls are.
Doing it badly would put the report's order at the mercy of a scheduler.

### A timed-out task is abandoned, not cancelled

Python cannot kill a thread. Past its deadline the runner stops waiting,
reports the timeout, and marks its pool **tainted** so the hung worker is handed
no more work — the pool is replaced on the next call. Calling that "cancelled"
would be a lie that costs somebody an afternoon.

The deadline belongs to the group rather than to each task, so ten hung tasks
cost one timeout rather than ten.

`SequentialRunner` cannot honour a timeout at all — interrupting a running
callable needs somewhere else to run — and says so in its own docstring, with a
test asserting the docstring still says it. A runner that quietly ignored the
argument would be worse.

### The parent span is captured at submission

A worker thread has its own stack of open spans, and it is empty: it does not
know what queued it. The submitting thread captures its current span and each
task binds to it. That single argument, passed at the right moment, is the
whole of the concurrency-correctness story for tracing.

The tracer's stack became thread-local and its shared structures got a lock.

## Consequences

**Three objects became reachable from two threads and needed locks**: the
tracer's span list and counters, `Workspace`'s read budget, and
`SmartMemoryStrategy`'s insight lists. Each has a test that runs eight threads
at it and checks the *result* — every span present and uniquely identified, the
budget spent exactly to its ceiling, no insight lost, a duplicate stored once.
"It has a lock" is not evidence that the lock is around the right thing.

The `Workspace` case is the one worth naming: the budget is checked and then
spent, and without the lock two reads that each fit under the ceiling can both
pass the check and then both spend. That is how a read budget is exceeded by a
whole file, and it is a security control.

**The agent blocked its own build.** Adding three `threading.Lock()` fields
made `PERFORMANCE.MEMORY_LEAK` report three HIGH findings, because `Lock` was
in the resource-opener table. It is a false positive — constructing a lock
acquires nothing — and it was fixed rather than suppressed, with a unit test
and an evaluation case pinning it (E-03). `acquire` stays in the table: a lock
taken and never released is the real defect and is a different call.

**Concurrency is a flag, and `--concurrency 1` is the old path.** One worker
selects the sequential runner outright rather than a pool of one, which would
quietly acquire an ability to interrupt that the old path never had.

**Nothing about the verdict changes.** The analyzers run before any agent and
remain sequential; the gate reads their findings. Asserted by running the same
review both ways and comparing the exit code, the outcome, the findings and the
comment.
