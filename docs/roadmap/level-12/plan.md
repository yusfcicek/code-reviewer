# Level 12 — Plan

Branch: `feature/level-12-evaluation`, off `development`, merged with `--no-ff`.

Each step lists the tests written first and the change that makes them pass.
No step is complete while a check is red.

## Step 1 — The confusion matrix and its scores

*Tests* — `tests/unit/domain/test_evaluation_scores.py`

- Precision, recall and F1 for a hand-computed matrix.
- The empty matrix: no expectations, no findings. Precision and recall are
  1.0, not a `ZeroDivisionError` and not 0.0 — a case with nothing to find and
  nothing found is a case that passed.
- All false positives, no true positives: precision 0.0.
- Two matrices add, and addition is associative over a list.
- Property: F1 lies between precision and recall for every non-degenerate
  matrix.

*Change* — `code_reviewer/domain/evaluation.py`: `ConfusionMatrix` with
`true_positives`, `false_positives`, `false_negatives`, the three ratios, and
`__add__`.

## Step 2 — Expectations, and what satisfies one

*Tests* — `tests/unit/domain/test_evaluation_matching.py`

- AC-1: exact rule and line yields one true positive, nothing else.
- AC-2: `line_tolerance: 2` matches a finding two lines away; three lines away
  is a miss *and* a false positive.
- AC-3: two findings of the same rule at lines 10 and 14, one expectation at
  12 with tolerance 3 — the closest wins; with both equidistant the lower line
  wins. Asserted against a shuffled input to pin determinism.
- AC-4: expected `CRITICAL`, produced `HIGH` — one false negative, zero false
  positives, and the finding is listed as a severity mismatch.
- AC-5: an in-scope finding no expectation claims is a false positive.
- AC-6: with `scope: ["SAST.*"]`, a `QUALITY.*` finding is neither, and its
  rule id appears in the ungraded list.
- AC-7: `expect_absent` on an out-of-scope rule still produces a false
  positive.
- One expectation cannot be satisfied twice, and one finding cannot satisfy
  two expectations.

*Change* — `ExpectedFinding`, `ForbiddenFinding`, `EvaluationCase`,
`CaseResult` and `grade(case, findings) -> CaseResult` in the same module.
Matching is a two-pass assignment: expectations first, in written order, each
taking its nearest unclaimed finding; whatever is left is judged against scope
and the forbidden list.

## Step 3 — The report and the threshold

*Tests* — `tests/unit/domain/test_evaluation_report.py`

- AC-7 (spec): the per-rule matrices sum to the overall one — as a property,
  over generated case results.
- A rule that appears only as a false positive still gets a row.
- AC-13: a threshold above the measured score reports one shortfall per breached
  bound, naming the metric, the floor and the value.
- A report containing a case error is below threshold whatever the scores.

*Change* — `EvaluationReport` (results, `overall`, `by_rule`, `ungraded`,
`errors`) and `EvaluationThreshold` with `shortfalls(report) -> list[str]`.

## Step 4 — The service

*Tests* — `tests/unit/application/test_evaluation_service.py`

- A dataset of two cases is graded through a fake `StaticAnalysis`, and the
  report carries both results.
- The diff a case supplies reaches `analyze`, so diff-only rules can be graded.
- AC-12: an analysis that raises is recorded as a case error, named, and does
  not abort the remaining cases — the run reports every failure it found, not
  just the first.
- Suppressed findings do not count: a fixture carrying `review-ignore` grades
  as though the rule never fired, because that is what the reviewed pipeline
  would see.

*Change* — `CaseFixture` and the `EvaluationDataset` port in
`application/ports.py`; `application/evaluation_service.py` with
`EvaluationService(analysis).evaluate(dataset)`.

## Step 5 — Rendering

*Tests* — `tests/unit/application/test_evaluation_rendering.py`

- The markdown carries the overall table, the per-rule table, the ungraded
  count and each shortfall.
- AC-10 (spec): the JSON summary round-trips through `json.dumps` and contains
  the same numbers as the markdown.
- A run with no ungraded findings says so, rather than omitting the section —
  an absent section reads as an oversight.

*Change* — `application/evaluation_report.py`:
`render_evaluation_report(report, threshold)` and `evaluation_summary(report)`.

## Step 6 — The dataset loader

*Tests* — `tests/unit/infrastructure/test_evaluation_dataset.py`

- AC-10: a directory of case files loads into `CaseFixture`s, in a stable
  order (sorted by file name, so the report diffs cleanly between runs).
- A case whose `file` is missing from disk raises `DatasetError` naming the
  path.
- A case with an unknown key raises rather than ignoring it — the same
  fail-closed rule the policy loader follows (Level 9).
- A malformed severity, a missing `rule`, and a case file that is not a
  mapping each raise with the offending file named.
- A fixture path escaping the dataset root is refused. The dataset is
  data that a contributor may open a merge request against, so it is
  untrusted input, and `Workspace` already states what that means here.

*Change* — `code_reviewer/infrastructure/evaluation/dataset.py` with
`FileSystemDataset(root)` and `DatasetError`.

## Step 7 — The golden dataset

*Files* — `evaluation/cases/*.yaml`, `evaluation/fixtures/*`

Eight cases, chosen to cover each analyzer and both directions of error:

| Case | Grades | Why it is in the set |
|---|---|---|
| `sql-injection` | `SAST.*` | The rule the gate blocks on most often |
| `hardcoded-secret` | `SAST.*` | Distinguishes a real secret from an example value |
| `weak-crypto` | `SAST.*` | Pins the bounded DES pattern fixed in Level 11 |
| `god-class` | `QUALITY.*` | A rule driven by a policy threshold, not a pattern |
| `nested-loops` | `PERFORMANCE.*` | Complexity, where line attribution is easy to get wrong |
| `n-plus-one` | `PERFORMANCE.*` | `expect_absent` on `dict.get`: the Level 11 false positive |
| `breaking-change` | `SEMANTIC.*` | The only rule that needs a diff |
| `clean-module` | *(everything)* | Nothing expected. The case that catches a rule firing on ordinary code |

`evaluation/**` is added to `ruff`'s per-file ignores for the same reasons
`tests/**` is: the fixtures contain deliberately bad code, which is the point
of them.

*Test* — `tests/unit/test_evaluation_dataset_quality.py`: the shipped dataset
loads, every fixture is referenced by at least one case, every analyzer
namespace appears in at least one case's scope, and at least one case expects
nothing.

## Step 8 — The command

*Tests* — `tests/unit/test_evaluation_cli.py`

- AC-14: a dataset meeting the thresholds exits 0.
- AC-13: below any threshold, exit 1 and the shortfall is printed.
- AC-11: a missing fixture exits 2, and the message names the case.
- `--json` writes a file that parses; `--markdown -` writes to stdout.
- Defaults come from the environment the same way `cli.py` does it, so a
  pipeline sets them once.

*Change* — `code_reviewer/evaluate.py` (parser and `main`), and the
`ai-code-review-eval` entry point in `pyproject.toml`.

## Step 9 — The gate in CI, and the baseline

*Tests* — `tests/unit/test_evaluation_baseline.py`

- AC-15: the shipped dataset, graded by the real `StaticAnalysisSuite`, meets
  the thresholds committed to CI. This is the test that turns the dataset from
  documentation into a gate, and it is the one that will fail when an analyzer
  changes.

*Change* — an `evaluate` job in `.gitlab-ci.yml` and a step in the GitHub
workflow, both running `ai-code-review-eval` with the committed floors and
publishing the JSON as an artefact.

Per D-4 the floors are read off the baseline once step 7 is in place, then
written into CI and into this plan, so the number and its justification live
together.

## Step 10 — Documentation

- `docs/ARCHITECTURE.md`: the evaluation path, and the new port.
- `README.md`: how to run the harness and how to add a case.
- `docs/adr/0014-evaluation-is-a-dataset-not-a-fixture.md`: D-2 and D-3.
- `CHANGELOG.md`: the level's entry.

## Order and rationale

Steps 1–3 are pure domain and need nothing else to exist; they are where every
edge case of scoring is settled while it is still cheap. Step 4 introduces the
only I/O boundary. Steps 6–7 build the dataset *after* the grader, so the cases
are written against a grader whose behaviour is already pinned rather than
against an intention. Step 9 is last because a baseline can only be measured
once there is something to measure — writing the CI floor before that would be
D-4's mistake in miniature.
