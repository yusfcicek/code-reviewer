# Level 14 — Plan

Branch: `feature/level-14-memory`, off `development`, merged with `--no-ff`.

## Step 1 — What is remembered

*Tests* — `tests/unit/domain/test_recollection.py`

- A `Recollection` knows its kind, path, rule, severity, first and last seen,
  and occurrence count.
- AC-1: `merge` of two recollections with the same identity gives one with the
  summed count.
- AC-2: it keeps the earliest `first_seen` and the latest `last_seen`.
- Merging different identities is refused — a silent merge of unrelated facts
  is the bug this class exists to make impossible.
- Identity ignores severity and line: a rule that moved down two lines in a
  refactor is the same fact, and treating it as new would reset every count on
  every reformat.

*Change* — `code_reviewer/domain/recollection.py`: `RecollectionKind`,
`Recollection`, its identity and `merge`.

## Step 2 — Salience, and forgetting

*Tests* — `tests/unit/domain/test_recollection_salience.py`

- AC-3: salience rises with occurrences; falls with age.
- AC-3 (property): salience is never negative, never infinite, and monotone in
  occurrences at a fixed age.
- AC-4: a `CRITICAL` recollection outranks an `INFO` one seen equally often and
  equally recently.
- Half-life: a fact last seen exactly one half-life ago is worth half.
- AC-5: below the floor, `forget` drops it.
- AC-6: `retain(limit)` keeps the most salient, and is stable when scores tie.
- AC-6 (property): `retain` never returns more than the limit and never
  invents an entry.
- A recollection from the future does not score more than one from now —
  clocks are wrong sometimes, and a wrong clock should not rewrite a ranking.

*Change* — `salience`, `forget`, `retain` in the same module.

## Step 3 — Consolidation and recall

*Tests* — `tests/unit/domain/test_recollection_recall.py`

- `consolidate(existing, observed)` merges by identity and leaves the rest.
- AC-7: `recall_for(path, memories, limit)` returns this file's facts before
  its directory's, and nothing from an unrelated directory.
- AC-8: the result is capped and ordered by salience.
- A path with no history recalls nothing rather than the whole memory.
- The root directory is not a bucket everything falls into.

*Change* — `consolidate` and `recall_for`.

## Step 4 — The port and the service

*Tests* — `tests/unit/application/test_project_memory.py`

- `remember` turns findings into recollections, consolidates and saves.
- AC-9: a suppression becomes a recollection carrying its reason and rule.
- AC-13: nothing from a finding's `evidence` or `description` reaches the store.
- AC-16: a store that raises on load recalls nothing; one that raises on save
  is logged and the review continues.
- Loading happens once per run, not once per file.

*Change* — `MemoryStore` port in `application/ports.py`;
`application/project_memory.py` with `ProjectMemory(store, clock)`.

## Step 5 — The file

*Tests* — `tests/unit/infrastructure/test_json_memory_store.py`

- A round trip preserves every field.
- AC-14: a corrupt file loads as empty, is logged, and is still on disk
  afterwards.
- A file from a future schema version loads as empty rather than half-read.
- AC-15: a write that fails leaves the previous file byte-identical.
- The temporary file does not survive a successful write.
- An unwritable directory is reported, not raised.
- Saving an empty memory writes an empty store rather than deleting the file.

*Change* — `infrastructure/memory/json_store.py`: `JsonMemoryStore`.

## Step 6 — Into the review

*Tests* — `tests/unit/application/test_review_with_memory.py`

- Recalled facts reach `Reviewer.review_diff`.
- What the review found is remembered, once, after every file is done.
- AC-11: the gate result, the findings and the exit code are identical with
  and without memory. Asserted by running the same review twice.
- AC-16: a broken store costs the review nothing.
- Suppressions from the outcome are remembered.

*Change* — `Reviewer.review_diff` gains `recollections`; `ReviewService` takes
an optional `ProjectMemory`.

## Step 7 — The prompt and the report

*Tests* — `tests/unit/infrastructure/test_review_agent_prompt.py` (extended),
`tests/unit/application/test_report.py` (extended)

- AC-12: recollections render inside `<untrusted_project_memory>`, as a table
  of rule, location, count and age.
- No recollections means no block at all.
- AC-10: a recurring finding is marked in the report with its count and the
  date it was first seen.
- A first-time finding is not marked.
- The report states how many of its findings are recurring.

*Change* — `ReviewAgent._build_prompt`; `render_review_comment` takes the
recalled memory and marks matching findings.

## Step 8 — The switches, the metrics, the composition root

*Tests* — `tests/unit/test_cli.py` (extended),
`tests/unit/test_main_wiring.py` (extended),
`tests/unit/infrastructure/test_metrics.py` (extended)

- AC-17: `--no-memory` builds no store and the review is unchanged.
- `--memory-path` overrides the default location, and the default sits inside
  the workspace.
- The metrics export carries the number of recollections recalled and the
  number of recurring findings.

*Change* — `cli.py`, `__main__.py`, `metrics/collector.py`.

## Step 9 — Documentation

- `docs/adr/0016-memory-informs-and-never-decides.md`: D-2, D-3, D-4.
- `docs/ARCHITECTURE.md`: the memory path and the new port.
- `README.md`: what is stored, what is never stored, and how to turn it off.
- `CHANGELOG.md`, `docs/roadmap/README.md`.

## Order and rationale

Steps 1–3 are the whole of the interesting logic and none of the I/O: identity,
decay, forgetting and recall are decided against lists of four items before a
file exists to get them wrong in. Step 5 is deliberately after step 4, so the
store is written against a service whose contract is already pinned.

Step 6 comes with the assertion that matters most in the level — that the
verdict is unchanged. Memory is the first feature here that could plausibly
make the agent *less* trustworthy by making it forgiving, and the test that
runs one review twice, with and without a history, is the one that says it does
not.
