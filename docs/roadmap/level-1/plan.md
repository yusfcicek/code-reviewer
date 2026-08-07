# Level 1 — Implementation Plan

Branch: `feature/level-1-correctness` (off `development`)

Each step is a red-green-refactor cycle: write the test, watch it fail for the
right reason, make it pass, commit. Steps are ordered so that the fixes with the
largest blast radius land first, while the suite is still small enough to read.

## Step 1 — Unblock the test process (F-37, F-36)

`tests/unit/test_agent_core.py` stubs LangChain into `sys.modules` at import
time, which contaminates every later test in the process. LangChain is a real
dependency and is installed, so the stubbing is unnecessary.

- Delete the `sys.modules` assignments; import `ReviewAgent` normally.
- Replace `test_summarization_trigger`'s `if …: pass / else: pass` with an
  assertion on the observable outcome: after crossing the threshold, the
  low-priority bucket shrinks and the summary buffer grows.

**Red:** `grep -r "sys.modules\[" tests/` finds matches; the summarization test
passes even when summarisation is disabled.
**Green:** suite passes with no module stubbing, in any collection order.

## Step 2 — Gate correctness (F-01, F-10)

- New test `tests/unit/test_review_gate.py`: a report the gate marks `FAIL`
  produces `ReviewGateResult.FAIL` and a non-empty `blocking_issues`.
- New test: a report with no `SOLID Compliance` line yields
  `scores["quality"] is None` and no quality-threshold reason.
- New `openhands/agent/gate/outcome.py`: `ReviewOutcome`, an aggregate that
  accumulates per-file `GateEvaluation`s and answers `is_blocking` and
  `blocking_issues`. Enum in, enum out — no strings.
- `main.py` uses `ReviewOutcome` instead of the `overall_status` string.

**Red:** an aggregation test asserting `is_blocking` fails, because the current
code can only ever produce `"pass"`.

## Step 3 — TLS by default (F-20)

- New test `tests/unit/test_gitlab_client.py` on an extracted
  `build_gitlab_client(...)`: default `ssl_verify` is `True`;
  `GITLAB_SSL_VERIFY=false` disables it and warns; `GITLAB_CA_BUNDLE` is passed
  through as the verify target.
- Extract the factory out of `main.py` and delete the hard-coded
  `ssl_verify=False`.

## Step 4 — The bundled policy becomes the default (F-04)

- New test `tests/unit/test_config_loader.py`: `load_policy()` executed from a
  temporary working directory returns a policy whose
  `security.banned_patterns` contains `os\.system` — a pattern present only in
  the YAML, not in the dataclass defaults.
- Resolve the packaged file via `importlib.resources` and place it last in the
  search order, after explicit path and working-directory candidates.
- Log which source won, so a surprising policy is diagnosable.

## Step 5 — Prompt correctness (F-02, F-03, F-19)

- New test `tests/unit/test_agent_prompt.py`:
  - the prompt template's `input_variables` include `memory_context`;
  - a rendered prompt contains a sentinel string from the memory context;
  - the rendered system prompt names every registered tool;
  - `review_diff` calls `load_context()` once.
- Add `{memory_context}` to the template, render the tool catalogue into it, and
  swap the OpenAI-function scratchpad formatter for one that produces the
  Hermes dialect the parser reads.
- Remove the duplicated `load_context()` call.

## Step 6 — Token counting without side effects (F-11)

- New test `tests/unit/test_smart_memory.py::test_does_not_mutate_model`:
  after constructing the strategy, the chat model object has no injected
  attribute.
- Introduce `TokenCounter` with a `HeuristicTokenCounter` default (chars/4) and
  a `ModelTokenCounter` adapter. Inject it; delete the `object.__setattr__`
  monkey-patch.

## Step 7 — Severity ordering (F-07)

- New test in each analyzer's test module: given findings of mixed severity, the
  rendered report lists `critical` first and `low`/`info` last.
- Give each severity enum an explicit numeric rank and sort on it.

## Step 8 — Triage on added lines (F-09)

- New test `tests/unit/test_review_triage.py`: a diff whose only mention of
  `password` is in a context line is **not** `CRITICAL`; the same word on an
  added line **is**.
- Match critical and API patterns against added lines (and, for removals, the
  removed-line patterns that already encode a leading `-`).

## Step 9 — Rules that cannot fire (F-05, F-06, F-08)

- `tests/unit/test_performance_analyzer.py`: `s += "x"` inside a `for` loop is
  reported; the same statement outside a loop is not.
- `tests/unit/test_sast_analyzer.py`: `yaml.load(f)` is reported;
  `yaml.safe_load(f)` and `yaml.load(f, Loader=yaml.SafeLoader)` are not.
- `tests/unit/test_dependency_tracker.py`: each `DependencyType` branch is
  reachable, asserted case by case.

## Step 10 — Semantic honesty (F-12, F-13, F-14)

- `tests/unit/test_semantic_analyzer.py`: an empty diff classifies as `UNKNOWN`;
  a diff adding `prefix = compute()` is not `BUGFIX`; the orphan-function
  message states the limits of single-file visibility.

## Step 11 — CLI argument types (F-15)

- `tests/unit/test_cli.py`: parsing with `CI_PROJECT_ID=42` in the environment
  yields the integer `42`; a non-numeric value produces a clear error.

## Step 12 — Close the level

- Update `README.md`'s status table: no ❌ rows remain.
- Update `docs/roadmap/README.md` and `findings.md` statuses.
- Merge into `development` with `--no-ff`.

## Test inventory added by this level

| Module | New test file |
|---|---|
| gate | `tests/unit/test_review_gate.py`, `tests/unit/test_review_outcome.py` |
| infrastructure | `tests/unit/test_gitlab_client.py` |
| config | `tests/unit/test_config_loader.py` |
| agent | `tests/unit/test_agent_prompt.py` (extends `test_agent_core.py`) |
| memory | extends `tests/unit/test_smart_memory.py` |
| triage | `tests/unit/test_review_triage.py` |
| analyzers | `tests/unit/test_sast_analyzer.py`, `test_quality_analyzer.py`, `test_performance_analyzer.py`, `test_semantic_analyzer.py`, `test_dependency_tracker.py` |
| CLI | `tests/unit/test_cli.py` |

## Risks

| Risk | Mitigation |
|---|---|
| Fixing the tool loop requires a live model | The loop is exercised against a stub chat model that returns a canned Hermes tool call; no network |
| Changing the default policy changes behaviour for existing users | The shipped YAML is a superset of the dataclass defaults; the loader logs which source won |
| Severity ranks alter existing report ordering | That is the point; tests assert the new order explicitly |
