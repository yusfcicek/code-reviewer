# Level 5 — Implementation Plan

Branch: `feature/level-5-ci-quality-gates` (off `development`)

## Step 1 — Configure ruff

- `[tool.ruff]` in `pyproject.toml`: line length 100, target `py312`.
- `[tool.ruff.lint]` selecting `E`, `F`, `W`, `I`, `UP`, `B`, `C4`, `SIM`, `RUF`.
- Ignore `RUF001`/`RUF002`/`RUF003` with a comment (decision D-2).
- Per-file ignores for tests where a rule is noise there and only there.

## Step 2 — Apply the automatic fixes

`ruff check --fix` then `ruff format`, in that order, with the suite run
between and after. Roughly 819 of the 1 574 findings are mechanical: import
order, `List` → `list`, `Optional[X]` → `X | None`, trailing whitespace.

**Gate:** 412 tests still pass. A formatting pass that changes behaviour is a
formatting pass with a bug.

## Step 3 — Fix what the linter surfaced

The remaining findings are read one by one. Expected classes:

| Rule | Meaning | Action |
|---|---|---|
| `E722` | bare `except:` | Catch what is actually expected |
| `RUF013` | implicit `Optional` | Annotate honestly |
| `RUF012` | mutable class default | `ClassVar` where the value is shared configuration |
| `F401` | unused import | Delete |
| `SIM102` | collapsible `if` | Collapse where it reads better, keep where the nesting carries meaning |
| `E501` | long line | Rewrap |

## Step 4 — Type checking

- `[tool.mypy]` with `packages = ["code_reviewer"]`, non-strict, and
  `ignore_missing_imports` for the untyped third parties.
- Errors in `domain/` and `application/` are fixed; the infrastructure layer is
  reported but not gating, until its dependencies carry annotations.

## Step 5 — Coverage floor

- Measure current total coverage.
- `--cov-fail-under=<floor>` in `addopts`, floor set to the measured value
  rounded down to a whole percent.

## Step 6 — Pipelines

Test-first: `tests/unit/test_pipelines.py` parses both files and asserts their
shape, so a broken pipeline fails locally rather than on push.

- `.github/workflows/ci.yml`: checkout, install uv, `uv sync`, lint, format
  check, mypy, pytest with coverage.
- `.gitlab-ci.yml`: the same checks, plus an `ai-code-review` job that runs this
  agent against the merge request that triggered the pipeline.
- `.pre-commit-config.yaml`: ruff check and format on commit.

## Step 7 — Dependency position

- Annotate each pin in `pyproject.toml` with why it is where it is.
- Add a roadmap entry for the LangChain upgrade with its own scope.

## Step 8 — Close the level

README badges and a "Development" section, roadmap and findings statuses,
merge.

## Risks

| Risk | Mitigation |
|---|---|
| A mass reformat hides a regression | Fixes are applied in stages with the suite run between each; formatting is a separate commit from behaviour |
| The coverage floor blocks legitimate work | It is set at the current value, so only a regression trips it |
| A pipeline that cannot be run locally rots | A test parses both files; the checks they run are the same commands a contributor runs |
