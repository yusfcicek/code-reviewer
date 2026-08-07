# Level 4 — Observability and Resilience

## Problem statement

The agent runs inside someone else's pipeline. When it behaves oddly — blocks a
merge request nobody expected, takes four minutes on a two-line change, reports
nothing on a file that clearly has problems — the operator's only evidence is a
stream of `print()` lines with hand-written prefixes.

Concretely:

- **Diagnostics are prints.** 32 of them, prefixed `[INFO]`, `[WARNING]`,
  `[GATE]` by hand. No levels, so a noisy run cannot be quietened and a silent
  failure cannot be made louder. No structure, so nothing can be grepped
  reliably or shipped to a log aggregator (F-47).
- **Metrics describe one file.** `export_prometheus` serialises
  `self._metrics[-1]`. One `ReviewMetrics` is recorded per file, so a merge
  request touching twelve files exports the twelfth and discards eleven. The
  output also lacks the `# HELP` and `# TYPE` lines the OpenMetrics text format
  requires, which GitLab's metrics report parses (F-16).
- **Most metric fields are always zero.** `security_score`,
  `performance_score`, `critical_issues`, `high_issues` and `medium_issues` are
  declared, exported, and never populated. A dashboard built on them would show
  a flat line and be believed (F-17).
- **One file's failure ends the run.** If the model times out on file seven,
  `ReviewService` propagates the exception, the composition root catches it at
  the top and exits 1. The six completed reviews are discarded and nothing is
  posted (F-58, found while writing this spec).
- **Nothing bounds an external call.** No timeout on the model, no retry on a
  transient GitLab error. A hung endpoint hangs the pipeline until CI's own
  timeout kills it, with no output (F-59).

Findings addressed: **F-16, F-17, F-47, F-58, F-59**.

## Goals

1. An operator can raise or lower verbosity without editing code, and can parse
   the output mechanically.
2. Exported metrics describe the whole review and are valid OpenMetrics.
3. Every declared metric is either populated or removed.
4. A failure on one file costs that file, not the run.
5. Every call that leaves the process is bounded in time and retried where
   retrying is safe.

## Non-goals

- Tracing, spans, or an OpenTelemetry exporter. The unit of work is a merge
  request; a log line per file and one metrics file is proportionate.
- Log shipping. Emitting structured records is this level's job; where they go
  is the operator's.

## Behavioural contracts

### C-1 — Logging replaces printing (F-47)
All diagnostics go through the standard `logging` module. The level is set from
`LOG_LEVEL`, defaulting to `INFO`. Records carry structured fields — file path,
decision, duration, finding counts — so a line can be parsed rather than read.
A `LOG_FORMAT=json` setting emits one JSON object per line for aggregators;
the default is human-readable for a CI log.

### C-2 — Metrics describe the review, not the last file (F-16)
The exporter aggregates every recorded file: totals for files and lines, counts
per triage decision, counts per severity, the worst gate result, the total and
maximum duration. Output includes `# HELP` and `# TYPE` for every series, and
parses as OpenMetrics text.

### C-3 — Every exported field is real (F-17)
Metrics carry counts derived from actual findings. Fields nothing can populate
are removed rather than exported as zero. A dashboard reading this data reads
something true.

### C-4 — A failing file is a finding, not an abort (F-58)
When analysis or the model raises on one file, the run records the failure
against that file, continues with the rest, and reports it in the comment. The
outcome reflects that a file could not be reviewed — it does not silently pass.

### C-5 — External calls are bounded (F-59)
The model client carries a request timeout and a bounded number of retries with
backoff, both configurable from the environment. Retries apply to transient
failures only; a refused request is not retried.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | No `print()` remains in `code_reviewer/` | `grep -c` in a test |
| AC-2 | `LOG_LEVEL=WARNING` suppresses INFO records | `tests/unit/infrastructure/test_logging.py` |
| AC-3 | `LOG_FORMAT=json` emits parseable JSON lines | Same |
| AC-4 | Exporting a review of three files mentions all three files' totals | `tests/unit/infrastructure/test_metrics.py` |
| AC-5 | Exported text has `# HELP` and `# TYPE` for every series | Same |
| AC-6 | Finding counts in metrics match the findings produced | Same |
| AC-7 | A reviewer that raises on one file still produces a comment covering the others | `tests/unit/application/test_review_service.py` |
| AC-8 | The failed file appears in the outcome as unreviewed | Same |
| AC-9 | Timeout and retry settings reach the model client | `tests/unit/infrastructure/test_vllm.py` |

## Decisions taken

**D-1 — Standard `logging`, not a third-party library.** The project already
depends on more than it needs. `logging` reaches every aggregator through
standard handlers, and a JSON formatter is twenty lines.

**D-2 — Structured fields via `extra`, not f-strings.** A message that
interpolates its values cannot be filtered on them. Fields go in `extra` and the
JSON formatter emits them as keys; the human formatter appends them as
`key=value`, which greps cleanly.

**D-3 — Aggregate in the collector, not in the exporter.** The collector already
holds every `ReviewMetrics`. Aggregation is its job; the exporter formats what
it is given. This also makes the aggregate testable without touching a file.

**D-4 — A failed file blocks by default.** "The reviewer crashed on this file"
is not evidence that the file is fine. The outcome records it as a warning and
the policy decides: `gate.fail_on_review_error`, defaulting to `false`, so
adopting this level does not start failing pipelines on a flaky endpoint —
but the failure is always visible in the comment.

**D-5 — Retries only on timeouts and 5xx.** Retrying a 401 wastes time and can
lock an account; retrying a 400 repeats a malformed request. Both surface
immediately.
