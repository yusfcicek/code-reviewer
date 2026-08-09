# Level 17 — Plan

Branch: `feature/level-17-concurrency`, off `development`, merged with
`--no-ff`.

## Step 1 — What running a group of tasks means

*Tests* — `tests/unit/application/test_task_runner.py`

- AC-1: outcomes come back in the order the tasks were given, whatever order
  they finished in.
- AC-2: a task that raises produces a failed outcome carrying the exception's
  type, and the others still produce values.
- An outcome knows whether it succeeded, and reading `.value` from a failed one
  is refused rather than returning `None` — `None` is a value a task may
  legitimately return.
- AC-3: a task that outlives its timeout produces a timed-out outcome.
- Running no tasks returns no outcomes rather than raising.
- AC-5 (property): for any list of tasks that terminate, the sequential runner
  and the pool produce the same outcomes.

*Change* — `TaskOutcome` and the `TaskRunner` port in
`application/ports.py`; `SequentialRunner` beside it, because a null-ish
default belongs with the interface it satisfies (the argument
`application/tracing.py` already made for `NullTracer`).

## Step 2 — The pool

*Tests* — `tests/unit/infrastructure/test_thread_pool_runner.py`

- AC-6: four tasks that each sleep 100 ms finish in well under 400 ms — the
  assertion that says this level does anything at all.
- AC-4: one task that hangs does not extend the group beyond the timeout, and
  the tasks beside it still return their values.
- After a timeout the runner reports its pool as tainted and does not reuse it;
  a second `run_all` gets a fresh pool.
- `max_workers` bounds how many run at once, observed by a counter the tasks
  increment.
- A pool of one still returns ordered outcomes.

*Change* — `infrastructure/concurrency/thread_pool.py`: `ThreadPoolRunner`.

## Step 3 — A tracer that survives threads

*Tests* — `tests/unit/infrastructure/test_tracer_concurrency.py`

- AC-7: a span opened inside `tracer.bind(parent)` attaches to `parent`, not to
  whatever the calling thread had open.
- AC-8: four threads each opening two spans under one parent produce a trace
  with no anomalies and the right shape.
- AC-9 (stress): 200 spans opened from 8 threads are all present, all uniquely
  identified, and none is lost.
- A worker thread's own nesting still works: a span opened inside a bound span
  is that span's child.
- The sequential behaviour is unchanged — every Level 16 test still passes.

*Change* — `SpanRecorder`: a thread-local stack, a lock around the span list
and the counters, and `bind(parent_span_id)`.

## Step 4 — The other two shared objects

*Tests* — `tests/unit/infrastructure/test_shared_state_contention.py`

- AC-10: eight threads reading through one `Workspace` spend the budget
  exactly once per read — the total bytes counted equals the total bytes
  returned, and a refusal happens at the right point rather than twice or not
  at all.
- AC-11: eight threads logging insights into one `SmartMemoryStrategy` lose
  none of them.

*Change* — a `threading.Lock` in `Workspace` around the budget check and
increment, and one in `SmartMemoryStrategy` around the insight lists and the
token recount.

## Step 5 — The committee runs concurrently

*Tests* — `tests/unit/application/test_orchestrator_concurrency.py`

- AC-12: the composed report is byte-identical with the sequential runner and
  with the pool.
- The per-agent accounting is identical both ways.
- Each specialist's span attaches to the file's span, not to another agent's.
- A specialist that hangs is reported as failed with a timeout, and the others
  still appear.
- The handoff round runs after the first round completes, not alongside it —
  it cannot be planned until the first round's requests exist.

*Change* — `ReviewOrchestrator` takes a `TaskRunner` and a per-agent timeout,
and submits the first round as a group.

## Step 6 — End to end

*Tests* — `tests/unit/application/test_review_concurrency.py`

- AC-13: the same review, run sequentially and concurrently, produces the same
  verdict, the same exit code, the same findings and the same comment.
- The trace from the concurrent run has no anomalies and the same set of span
  kinds.

## Step 7 — The switch

*Tests* — `tests/unit/test_cli.py`, `tests/unit/test_main_wiring.py`

- AC-14: `--concurrency 1` builds the sequential runner; a larger value builds
  a pool with that ceiling.
- A value below 1 is refused at parse time.

*Change* — `cli.py`, `__main__.py`.

## Step 8 — Documentation

- `docs/adr/0019-threads-behind-a-port.md`: D-1, D-2, D-3, D-4.
- `docs/ARCHITECTURE.md`, `README.md`, `CHANGELOG.md`,
  `docs/roadmap/README.md`.

## Order and rationale

Step 1 settles what a group of tasks *is* before anything runs concurrently,
including the two cases that only exist because of concurrency — a failure that
must not propagate, and a timeout that must not wait.

Step 3 comes before step 5 deliberately. The tracer is the thing most likely to
be subtly wrong under threads, and it is also the instrument every later
concurrency bug will be diagnosed with; getting it wrong would mean debugging
step 5 with a broken microscope.

Step 4 is the unglamorous half: two locks, and two tests that run eight threads
at an object and check the *result* rather than the absence of a crash. "It has
a lock" is not evidence that the lock is around the right thing.

Steps 5 and 6 are the payoff, and both are asserted as *equalities* against the
sequential path — which is the only honest way to claim that a concurrency
change did not change anything else.
