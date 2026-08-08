# Level 9 — Implementation Plan

Branch: `feature/level-9-fail-closed` (off `development`)

Ordered so the widest-reaching change lands first, while the branch is empty
enough to see what it breaks. Every step names the test that fails before the
code is written.

## Step 1 — Namespaced rule ids, a frozen `Finding`, and deduplication (G-08)

Three changes that have to move together: the key needs a namespace, the key
needs to be hashable, and the dedup needs both.

Test-first, in this order:

1. `tests/unit/domain/test_finding.py`
   - `Finding` is hashable and two identical findings are equal;
   - `metrics` is immutable — mutating it raises;
   - `namespace` returns the segment before the first `.`, and `""` when there
     is none.
2. `tests/unit/infrastructure/test_analysis_suite.py`
   - every id the suite emits matches `NAMESPACE.RULE`;
   - two findings sharing rule and location collapse to one;
   - the survivor is the more severe;
   - findings differing only in line number both survive;
   - the returned order is still most-severe-first.

Then: `frozen=True` on `Finding`, `metrics` through `MappingProxyType`, a
`namespace` property, `_rule_id(namespace, value)` in the suite, and
`_deduplicate` before the sort.

**Expected fallout:** every construction site of `Finding`. There are six in
`code_reviewer/` and three test modules. Freezing turns any assignment after
construction into an error at the point it happens, which is why this step is
first.

## Step 2 — A failed analysis blocks (G-09, C-4)

Test-first: `tests/unit/application/test_analysis_failure.py`

| Test | Asserts |
|---|---|
| suite raises | the file is recorded as unanalysed, with the error |
| default policy | an unanalysed file makes the outcome blocking |
| reason | the blocking reason names the file and the error text |
| opt out | `fail_pipeline_on_analysis_error: false` demotes it to a warning |
| narration failure | a reviewer that raises still only warns (regression guard) |
| partial | one analyzer failing inside the suite is not a suite failure |
| report | the comment says the file was not analysed |

Then: `GatePolicy.fail_pipeline_on_analysis_error` (default `True`),
`ReviewOutcome.record_unanalysed`, `ReviewService._analyse` stops swallowing,
and `exit_code` honours the flag.

The distinction from the existing `fail_on_review_error` is worth keeping
sharp: that one is "the reviewer crashed on this file", this one is "the
analysis could not run". The first defaults to `False` because the model is
allowed to fail; the second defaults to `True` because the evidence is not.

## Step 3 — Fail-closed policy loading (G-10, C-5)

Test-first: `tests/unit/infrastructure/test_config_loader.py` gains

| Test | Asserts |
|---|---|
| unknown key | raises, message names the key and the file |
| unknown section | raises, message names the section |
| bad YAML | raises rather than falling back |
| non-mapping root | raises |
| wrong type | a string where an int belongs raises |
| explicit missing file | `--policy /nope.yaml` raises |
| **implicit absence** | no policy file anywhere still returns the bundled default |
| valid file | still loads, and the source is still reported |

Then: replace each `logger.warning(...)`-and-continue with a raised
`PolicyLoadError`, and add a validation pass comparing section and key names
against the dataclass fields.

**Check the bundled policy first.** If `review_policy.yaml` carries a key the
dataclasses do not declare, this step turns the shipped default into a startup
failure — so the validation pass runs against it as part of the test.

## Step 4 — Manifests are always reviewed (G-11, C-6)

Test-first: `tests/unit/domain/test_triage.py` gains

- `.github/workflows/ci.yml`, `.gitlab-ci.yml`, `package.json`,
  `package-lock.json`, `go.mod`, `Cargo.toml`, `pom.xml`, `Dockerfile`,
  `docker-compose.yml`, `Makefile`, `Jenkinsfile`, `requirements.txt`,
  `pyproject.toml` — each reaches `FULL_REVIEW` on a two-line diff;
- an ordinary two-line source change still reaches `AUTO_APPROVE`;
- a path matching both a skip pattern and a manifest pattern is skipped —
  skip is an explicit statement about the file, and the more specific one wins;
- the reason names the manifest rule, so the report says why.

Then: `TriagePolicy.manifest_patterns`, compiled alongside the skip patterns,
and a rule in `decide` between the API check and the size checks.

## Step 5 — Documentation

- ADR `0011-unknown-means-blocked.md`: the three-state model, and why analysis
  failure and narration failure are treated differently.
- `README.md`: the new policy keys, `manifest_patterns`, and a plain statement
  that an unknown key now fails at startup.
- `SECURITY.md`: manifests and CI definitions are never auto-approved, and why
  that class of change is small by nature.
- `CHANGELOG.md`: breaking — fail-closed loading, the new blocking condition,
  the namespaced rule ids.

## Verification

```bash
uv run ruff check code_reviewer tests
uv run ruff format --check code_reviewer tests conftest.py
uv run mypy
uv run pytest --cov
./scripts/audit-deps.sh
```

## Risk register

| Risk | Mitigation |
|---|---|
| Freezing `Finding` breaks a call site that mutates after construction | It breaks loudly, at the line that does it. Step 1 is first precisely so this surfaces against an otherwise-unchanged tree |
| Fail-closed loading breaks an existing deployment's policy file | That is the intent — the file was not doing what its author thought. The error names the key, and `CHANGELOG.md` records it as breaking |
| The bundled `review_policy.yaml` itself fails validation | Step 3's tests validate it explicitly, so this is caught here rather than at someone's startup |
| Blocking on analysis failure makes a flaky analyzer fail merges | It is behind a flag with a documented default. A flaky analyzer is a bug worth surfacing, not a reason to trust its silence |
| `manifest_patterns` catches a file a team wants auto-approved | It is policy, editable per repository, and the reason string names the rule that fired |
