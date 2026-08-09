# Level 17 — Asynchronous execution

## Problem statement

Everything happens in sequence, and almost all of it is waiting.

A file with security, performance and dependency findings now runs four
specialists, each of which makes one to ten model calls. Every one of those is
a network round trip to an inference endpoint, and the process spends it
blocked. Four agents that each wait two seconds take eight seconds, and the CPU
is idle for all eight.

- **Wall-clock time is the sum of the waiting.** The committee introduced at
  Level 15 multiplied the number of model calls per file by four and did
  nothing about their arrangement, because concurrency was explicitly deferred:
  a race in a committee of five is not debuggable from a flat log (C-13).
- **Level 16 removed that objection.** There is now a causal record of what ran,
  under what, and for how long — which is precisely the instrument a
  concurrency bug is diagnosed with.
- **The tracer cannot survive concurrency as written.** It keeps one stack of
  open spans in one object. Two threads opening spans against it would
  interleave, and the tree would come out wrong — the first thing this level
  has to fix, and the thing that makes it worth having done Level 16 first.
- **Three pieces of shared state are unsafe.** `Workspace` mutates a read
  budget, `SmartMemoryStrategy` mutates insight lists, and the tracer mutates a
  span list and a counter table. All three are correct under one thread and
  none of them says so.

Capabilities addressed: **C-13**.

## Goals

1. The specialists reviewing one file run concurrently, bounded, with the
   result identical to running them in sequence.
2. A task that hangs costs its own section and a stated timeout, not the run.
3. The trace comes out the same shape it would have sequentially: every span
   attached to the parent it was submitted under.
4. Every piece of state two threads can now reach is made safe, and the safety
   is tested by contention rather than asserted.
5. Concurrency is a flag, and one worker is exactly the old behaviour.

## Non-goals

- **`asyncio`.** The obvious answer, and not the one taken. Every port would
  become `async`, every implementation and every fake with it, and the two
  clients in the critical path — `python-gitlab` and LangChain's
  `ChatOpenAI.invoke` — are synchronous. An `async def` wrapper around a
  blocking call in a thread pool is what this level does explicitly, rather
  than what `asyncio.to_thread` would do implicitly behind an interface change
  touching every layer. Recorded as D-1 rather than left as an omission.
- **Concurrency across files.** `ReviewOutcome`, the metrics list, the report
  sections and the project memory's observations are all appended to per file.
  Making that aggregate thread-safe *and* deterministic is a second level's
  worth of work for a smaller win than the per-file fan-out, which is where the
  model calls are. Files stay sequential and the reason is written down.
- **A process pool.** The work is I/O-bound. Threads release the GIL across a
  socket read, and a process pool would add pickling to a problem that does not
  have one.
- **Cancelling a hung task.** A Python thread cannot be killed. A task past its
  timeout is *abandoned*, reported as failed, and its worker is not reused. The
  distinction is stated rather than papered over.
- **Speculative parallelism.** No running of specialists that the routing did
  not assign, on the theory that a spare core is free. It is not: each one is a
  model call somebody pays for.

## Behavioural contracts

### C-1 — Tasks run through a port, and the default is sequential (C-13)
`TaskRunner.run_all` takes a list of callables and returns one outcome per
task, **in the order given**, whatever order they completed in. The shipped
`SequentialRunner` is the default and is exactly the pre-Level-17 behaviour.

### C-2 — Order is by plan, not by completion (C-13)
The composed report, the per-agent accounting and the metrics are identical
whether the runner is sequential or concurrent. Level 15's fixed composition
order is what makes this cheap, and this level does not weaken it.

### C-3 — A task's failure is its own (C-13)
An exception inside a task is captured into that task's outcome. It does not
propagate out of `run_all`, and it does not stop the others.

### C-4 — A task that hangs is abandoned, and says so (C-13)
Past its timeout, a task's outcome is `timed out`, the review proceeds, and the
report states it. The thread is not killed — it cannot be — so the runner
declines to reuse it and says that in the log. Wall-clock for the whole group
is bounded by the timeout regardless of how many tasks hang.

### C-5 — The trace is the same shape under concurrency (C-13)
A span opened on a worker thread attaches to the span that submitted the work,
not to whatever another thread happened to have open. Spans opened on different
threads do not interleave into each other's parents, and the resulting trace
has no anomalies.

### C-6 — The tracer, the workspace and the memory are safe under contention
Each is exercised by several threads at once, and the assertion is on the
result rather than on the absence of a crash: every span present, the read
budget respected exactly once per read, no insight lost.

### C-7 — Concurrency is bounded and configurable
`--concurrency N` sets the ceiling. `1` selects the sequential runner outright
rather than a pool of one, so the old path stays the old path.

### C-8 — Nothing about the verdict changes
The gate reads findings, and findings come from the analyzers, which run before
any agent and remain sequential. A concurrent review and a sequential one
produce the same verdict and the same exit code, and that is asserted by
running the same review both ways.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | `run_all` returns outcomes in the order the tasks were given | Unit + property test |
| AC-2 | A task that raises yields a failed outcome and does not affect the others | Unit test |
| AC-3 | A task that hangs yields a timed-out outcome within the timeout | Unit test |
| AC-4 | One hung task does not extend the group beyond the timeout | Unit test |
| AC-5 | The sequential runner and the pool produce identical outcomes | Property test |
| AC-6 | Concurrent tasks actually overlap | Unit test on observed timing |
| AC-7 | A worker's span attaches to the submitting span | Unit test |
| AC-8 | Spans from four threads produce a trace with no anomalies | Unit test |
| AC-9 | The tracer keeps every span under contention | Stress test |
| AC-10 | The workspace's read budget is exact under contention | Stress test |
| AC-11 | The memory keeps every insight under contention | Stress test |
| AC-12 | The orchestrator's report is identical sequential and concurrent | Unit test |
| AC-13 | The whole review's verdict and exit code are identical both ways | Unit test |
| AC-14 | `--concurrency 1` selects the sequential runner | Unit test on the CLI |
| AC-15 | The six checks stay green, coverage holds, the eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — Threads behind a port, not `asyncio`.** The work is a handful of
blocking network calls per file. `asyncio` would turn every port, every
adapter and every fake in this repository `async` in order to await two
libraries that are synchronous anyway. A `TaskRunner` port with a sequential
default and a thread-pool adapter buys the same wall-clock and costs one
interface. If an async-native model client ever becomes the norm here, it
arrives as a third adapter.

**D-2 — Files stay sequential.** The per-file fan-out is where the model calls
are; the per-review fan-out shares an aggregate that is appended to from four
places and rendered in order. Making that safe *and* deterministic is worth its
own level, and doing it badly would put the report's order at the mercy of a
scheduler.

**D-3 — A timed-out task is abandoned, not cancelled.** Python cannot kill a
thread. The runner stops waiting, reports the timeout, and marks its pool as
tainted so the hung worker is not handed more work. Saying "cancelled" would
be a lie that costs somebody an afternoon.

**D-4 — The parent span is captured at submission.** Not read from the worker
thread, which has its own stack and does not know what submitted it. This is
the whole of the concurrency-correctness story for tracing, and it is one
argument passed at the right moment.

**D-5 — Locks, not lock-free cleverness.** Three small critical sections, each
around a few statements, in a process that spends its life waiting on sockets.
A `threading.Lock` is the boring answer and the cost is unmeasurable next to
one network round trip.

**D-6 — Contention is tested, not asserted.** Each shared object gets a test
that runs several threads against it and checks the *result* — every span
present, the budget spent exactly once, no insight lost. "It has a lock" is not
evidence that the lock is around the right thing.
