# Level 4 — Implementation Plan

Branch: `feature/level-4-observability` (off `development`)

## Step 1 — Logging infrastructure (F-47)

Test-first: `tests/unit/infrastructure/test_logging.py`.

- `configure_logging()` honours `LOG_LEVEL`; `WARNING` suppresses INFO records.
- An unknown `LOG_LEVEL` falls back to INFO with a warning rather than raising.
- `LOG_FORMAT=json` emits one parseable JSON object per record, including the
  structured fields.
- The default format appends `key=value` pairs after the message.
- Configuring twice does not duplicate handlers.

Implementation: `code_reviewer/infrastructure/observability/logging.py` with
`configure_logging()`, a `StructuredFormatter` and a `JsonFormatter`.

## Step 2 — Replace every print (F-47)

Mechanical, guarded by a test that greps the package. Each call site gets a
level that reflects what it means:

| Site | Level |
|---|---|
| policy source, triage decision, file counts | INFO |
| unreadable file, disabled TLS verification, memory pressure | WARNING |
| blocking issues, review failure | ERROR |
| token accounting, dependency analysis detail | DEBUG |

## Step 3 — Metrics that describe the review (F-16, F-17)

Test-first: `tests/unit/infrastructure/test_metrics.py`.

- Three recorded files produce one aggregate with the sum of their lines.
- Triage decisions are counted across files.
- Severity counts come from the findings the workflow recorded.
- The worst gate result wins: one `fail` among two `pass` makes the review fail.
- Every exported series has `# HELP` and `# TYPE`.
- Exported text parses: every non-comment line is `name{labels} value`.
- An empty collector exports nothing rather than a malformed file.

Implementation: `ReviewMetrics` loses the fields nothing populates and gains
finding counts; `MetricsCollector.aggregate()` returns a `ReviewAggregate`;
`export_prometheus` formats the aggregate with HELP/TYPE.

## Step 4 — A failing file does not end the run (F-58)

Test-first: `tests/unit/application/test_review_service.py`.

- A reviewer that raises on the second of three files still produces a comment
  covering the first and third.
- The failed file is recorded on the outcome and named in the comment.
- With `gate.fail_on_review_error = true` the run exits non-zero.
- With it false (the default) the run exits zero but still reports.
- A failing analyzer does not stop the model review of the same file.

Implementation: `ReviewService._review_one` wraps analysis and review
separately; `ReviewOutcome.record_failure(path, reason)`; the report renders a
"could not be reviewed" section.

## Step 5 — Bounded external calls (F-59)

Test-first: `tests/unit/infrastructure/test_vllm.py`.

- The provider passes `LLM_TIMEOUT_SECONDS` to the client.
- `LLM_MAX_RETRIES` reaches the client.
- Defaults are sane when neither is set.
- A non-numeric value falls back to the default with a warning.

Implementation: `VLLMProvider` reads both, with documented defaults.

## Step 6 — Close the level

README observability section, roadmap and findings statuses, merge.

## Risks

| Risk | Mitigation |
|---|---|
| Replacing prints changes CI output people rely on | The default format keeps the message text; levels and fields are additive |
| Removing metric fields breaks an existing dashboard | Those fields only ever exported `0`; the removal is recorded in the changelog |
| Catching per-file exceptions hides real bugs | The exception is logged at ERROR with a traceback and surfaces in the comment; it is not swallowed |
