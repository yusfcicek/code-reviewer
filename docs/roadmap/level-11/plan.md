# Level 11 — Implementation Plan

Branch: `feature/level-11-verification` (off `development`)

Ordered by dependency: suppression must exist before dogfooding can stay
green, and the lint widening goes last so it is applied once to code that has
stopped moving.

## Step 1 — Suppression (G-07, C-1…C-3)

New module `code_reviewer/domain/suppression.py`. In the domain, alongside
`triage.py`, for the same reason: the comment syntax is not incidental to the
rule, it is the rule's interface (decision D-1).

Test-first: `tests/unit/domain/test_suppression.py`

| Test | Asserts |
|---|---|
| trailing | `x = 1  # review-ignore: SAST.X - reason` covers line 1 |
| standalone | A comment on its own line covers the *next* line |
| namespace | `SAST.*` matches `SAST.SQL_INJECTION`, not `QUALITY.SRP` |
| bare star | `*` is not a valid rule id |
| unrelated | A different rule at the same line survives |
| file scope | `review-ignore-file:` covers every line |
| reason | Captured verbatim; separators `-`, `—`, `:` all work |
| no reason | Still suppresses, reported as unexplained |
| comment styles | `#` and `//` both parse |
| several rules | `review-ignore: A, B - reason` covers both |
| empty source | Yields no directives |
| not a directive | `# review this later` is not one |

Public shape: `SuppressionDirective` (frozen), `parse_directives(source)`,
`apply_suppressions(findings, source) -> SuppressionResult`.

## Step 2 — The suite returns what it silenced (G-07, C-4)

`StaticAnalysis.analyze` returns `AnalysisResult(findings, suppressed)`
instead of a list (decision D-4).

Blast radius, checked before starting: one production implementation
(`StaticAnalysisSuite`), one caller (`ReviewService._analyse`), and the test
fakes in `test_analysis_failure.py` and `test_sandbox_findings.py`.

Test-first: `tests/unit/infrastructure/test_analysis_suite.py` gains

- a suppressed finding is absent from `findings` and present in `suppressed`;
- the directive and its reason travel with it;
- suppression happens after deduplication, so one directive silences one
  finding rather than a duplicate pair;
- a file with no directives returns everything, and `suppressed` is empty.

Then `application/report.py` states the count, with a test.

## Step 3 — Dogfooding (G-16, C-5)

Test-first — and this one is written expecting to fail:
`tests/unit/test_dogfooding.py` runs the suite over every `.py` under
`code_reviewer/` and asserts the outcome is not blocking, with no `CRITICAL`
and no `HIGH`.

**Expect real findings.** Each is triaged by hand into one of three:

1. a genuine defect → fix it, and say so in the commit;
2. a false positive on a rule worth keeping → a `review-ignore` with a reason;
3. a rule that misfires generally → its own finding, recorded, not suppressed
   wholesale.

The suppression cap starts at whatever category 2 needs and is stated in the
test. Raising it later has to be a deliberate edit.

## Step 4 — Property-based tests (G-17, C-6)

Add `hypothesis` to the dev group. New
`tests/unit/test_diff_properties.py`, guarded with `pytest.importorskip` so
the suite still runs where it is absent.

Properties:

- triage returns a decision for any diff-shaped input;
- the semantic analyzer returns an analysis for any diff-shaped input;
- triage returns a decision for any *path*, including empty and unicode;
- the suppression parser returns directives for arbitrary source text.

Deadlines disabled: the first run compiles regexes and would flake otherwise.

## Step 5 — Widen `mypy` and add `S` (G-18, C-7, C-8)

Measured before starting: **32 `mypy` errors in 10 files**, **6 `ruff S`
errors**. Both are small enough to close rather than exempt wholesale.

1. `[tool.mypy] files = ["code_reviewer"]`, then fix what falls out. Anything
   genuinely untypable gets a narrow `type: ignore[code]` with a comment.
2. `select` gains `S`. Per-file ignores for `tests/**` (`S101`, the assert
   rule). Each remaining exemption carries a written reason — a bare
   `# noqa: S…` is the same failure as a suppression without one.
3. CI already runs `uv run mypy`, which reads the config, so no workflow
   change is needed.

## Step 6 — Documentation

- ADR `0013-suppression-is-narrow-and-counted.md`.
- `README.md`: the suppression syntax, and the dogfooding claim.
- `CONTRIBUTING.md`: when a `review-ignore` is the right answer.
- `CHANGELOG.md`: the `StaticAnalysis` port change.
- `docs/roadmap/README.md`: Level 11, and the roadmap's completion note.

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
| Dogfooding surfaces more than a level's worth of findings | Category 3 in Step 3: a rule that misfires generally is recorded as its own work item, not suppressed to make the test green |
| Suppression becomes the way findings get handled | The cap in the dogfooding test, and the reason requirement. Both are visible in a diff |
| The port change ripples further than expected | Blast radius counted before starting: one implementation, one caller, two fakes |
| `hypothesis` makes CI flaky | Deadlines disabled, and a fixed example count. A property that fails is a real bug; a property that times out is a configuration mistake |
| Widening `mypy` produces changes with no tests behind them | 32 errors is small enough to read individually. Anything that would need a behavioural change becomes a `type: ignore` with a reason rather than a silent fix |
