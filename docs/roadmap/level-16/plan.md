# Level 16 — Plan

Branch: `feature/level-16-tracing`, off `development`, merged with `--no-ff`.

## Step 1 — What a span is

*Tests* — `tests/unit/domain/test_span.py`

- A `Span` carries its id, parent, kind, name, start, end, status and
  attributes.
- AC-6: a span that ends before it starts is refused.
- An unfinished span (no end) has no duration rather than a negative one.
- Attributes are immutable, and a mutable dict handed in is copied.
- AC-6 (spec C-6): an attribute whose value is longer than a stated cap is
  refused at construction — a long attribute is how a diff gets into a trace.
- `SpanStatus.ERROR` requires a stated error type, the way a failed
  `AgentReport` requires a reason.

*Change* — `code_reviewer/domain/trace.py`: `SpanKind`, `SpanStatus`, `Span`.

## Step 2 — The tree

*Tests* — `tests/unit/domain/test_trace_tree.py`

- AC-1: a flat list builds one tree with the parentless span at the root.
- Children are ordered by start time, then by id, so two runs render alike.
- AC-2: an orphan attaches to the root and appears in `anomalies`.
- AC-3: a two-span cycle, and a three-span cycle, are broken and recorded.
- AC-3 (property): tree building over arbitrary parent assignments terminates
  and returns every span exactly once.
- Two roots: the earlier is the root, the later is recorded as an anomaly and
  attached — a trace with two roots is a bug in the recorder, not a reason to
  lose half the spans.
- An empty trace builds an empty tree rather than raising.

*Change* — `TraceNode`, `Trace`, `Trace.tree()`, `Trace.anomalies`.

## Step 3 — Where the time went

*Tests* — `tests/unit/domain/test_trace_timing.py`

- AC-4: self time is duration minus the children's durations.
- AC-4: floored at zero when children overlap or a clock moved backwards.
- AC-5 (property): the sum of every span's self time never exceeds the root's
  duration by more than the rounding.
- `by_kind` totals self time per kind, so "40 % of this review was tool calls"
  is computable.
- A trace of one unfinished span reports no duration rather than zero — those
  are different facts.
- The critical path is the deepest chain by duration, and is deterministic on
  a tie.

*Change* — `self_time`, `Trace.by_kind`, `Trace.critical_path`.

## Step 4 — The recorder

*Tests* — `tests/unit/infrastructure/test_tracer.py`

- AC-9: `with tracer.span(...)` nests; siblings do not.
- Identifiers are dotted counters: the third child of `1.2` is `1.2.3` (D-6).
- AC-7: an exception marks the span `ERROR`, records the type, and propagates.
- AC-10: closing a span twice is logged and ignored.
- A clock that goes backwards produces a zero duration, not a negative one.
- `NullTracer` satisfies the same interface and records nothing, so an
  uninstrumented caller costs nothing.
- The current span id is readable while inside a span and empty outside.

*Change* — `code_reviewer/infrastructure/observability/tracer.py`: `Tracer`,
`NullTracer`, and the module-level `current_trace_context()` the log filter and
the tools read.

## Step 5 — Logs join the trace

*Tests* — `tests/unit/infrastructure/test_logging.py` (extended)

- AC-8: a record emitted inside a span carries `trace_id` and `span_id` in the
  structured format and in the JSON format.
- A record emitted outside any span carries neither, rather than empty strings.
- The ids survive the `fields` mechanism without colliding with a caller's own
  key of the same name.

*Change* — a `logging.Filter` installed by `configure_logging`.

## Step 6 — The review path

*Tests* — `tests/unit/application/test_review_tracing.py`

- AC-11: one run span, one span per file, and spans for analysis, retrieval and
  memory recall beneath each file.
- AC-12: one span per agent, carrying its specialism and its budget.
- A failed specialist's span is `ERROR` and names the exception type.
- AC-14: no attribute value anywhere in a real review's trace contains the
  diff, the file content, or a finding's description.
- Without a tracer the workflow behaves exactly as before — asserted by running
  the same review with a `NullTracer` and comparing the result.

*Change* — `ReviewService`, `ReviewOrchestrator` and `SpecialistAgent` take a
tracer; `NarrationLoop` opens a span per tool call and per model call.

## Step 7 — Reading it

*Tests* — `tests/unit/infrastructure/test_trace_rendering.py`

- AC-15: the tree renders with indentation, durations and self time, bounded by
  depth and node count, stating what it omitted.
- AC-16: the JSON export names every span and round-trips through `json.dumps`.
- The rendering of an empty trace says so.
- Anomalies are rendered, because an orphan span is a bug worth seeing.

*Change* — `render_trace_tree`, `trace_to_json`, and the `TraceExporter` port
with `JsonTraceExporter` behind it.

## Step 8 — The switch and the report

*Tests* — `tests/unit/test_cli.py` (extended),
`tests/unit/test_main_wiring.py` (extended),
`tests/unit/application/test_report.py` (extended)

- AC-18: `--trace-path` writes the JSON; without it nothing is written.
- AC-17: an exporter that raises is logged and the review still exits normally.
- The report carries the bounded tree inside a collapsed section.

*Change* — `cli.py`, `__main__.py`, `application/report.py`.

## Step 9 — Documentation

- `docs/adr/0018-a-trace-of-our-own.md`: D-2, D-3, D-5.
- `docs/ARCHITECTURE.md`, `README.md`, `CHANGELOG.md`,
  `docs/roadmap/README.md`.

## Order and rationale

Steps 1–3 are the whole model and none of the clock: what a span is, how a tree
is built from a flat list, and what self time means are all decidable over
literal values, including every case that would otherwise be discovered in
production — an orphan, a cycle, a clock that moved backwards.

Step 4 introduces the only stateful object. Step 5 comes before the
instrumentation on purpose: the join between a log and a trace is the property
that makes the rest worth having, and testing it against a two-span toy is
easier than against a full review.

Steps 6–8 are the instrumentation, the reading and the switch, in that order —
each is only meaningful once the one before it exists.
