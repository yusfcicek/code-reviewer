# Level 21 — Plan

Branch: `feature/level-21-narration-evaluation`, off `development`, merged with
`--no-ff`.

## Step 1 — What a review was written about

*Tests* — `tests/unit/domain/test_narration_brief.py`

- A `NarrationCase` carries the file, its line count, the diff's touched lines,
  and the findings the analyzers produced — the facts a check can be answered
  against.
- A case with no recorded review is refused: there is nothing to grade.
- `Citation.parse` finds `path:line` in prose, including inside backticks and
  inside a markdown table cell, and finds nothing in a sentence that merely
  contains a colon.

*Change* — `code_reviewer/domain/narration.py`: `NarrationCase`, `Citation`.

## Step 2 — The checks

*Tests* — `tests/unit/domain/test_narration_checks.py`

- AC-1, AC-2, AC-3: grounded citations.
- AC-4: no verdict claimed.
- AC-5, AC-6: severity discipline, both directions.
- AC-7: required sections, naming the missing one.
- A check reports the substring that failed it, so a reader can act without
  re-reading the whole review.
- A check that has nothing to say — no findings at all, no citations at all —
  passes rather than dividing by zero, which is Level 12's rule for an empty
  denominator applied here.

*Change* — the check functions and a `NarrationCheck` protocol in the same
module.

## Step 3 — Grading a corpus

*Tests* — `tests/unit/application/test_narration_evaluation.py`

- One case produces one `GradedNarration` with a result per check.
- A corpus produces a `NarrationReport`: pass rate per check, overall score,
  the failing cases named.
- AC-8: two runs produce identical reports.
- AC-10: cases recorded under a fingerprint other than the current one are
  counted and reported.
- AC-9 belongs to the loader, not here.

*Change* — `code_reviewer/application/narration_evaluation.py`.

## Step 4 — The corpus on disk

*Tests* — `tests/unit/infrastructure/test_narration_dataset.py`

- A case is a YAML file naming a fixture and a recorded review.
- AC-9: a recorded review containing a credential-shaped string refuses to
  load — the corpus may not become the thing four levels kept out of the
  artefacts.
- An unknown key, a missing fixture and an unreadable review each refuse to
  load, exactly as Level 12's loader does.
- Fixture paths go through `Workspace`.

*Change* — `code_reviewer/infrastructure/evaluation/narration_dataset.py`, and
`evaluation/narration/` holding the first twelve cases.

## Step 5 — The command

*Tests* — `tests/unit/test_evaluation_cli.py` (extended)

- AC-11: `ai-code-review-eval --narration` grades the corpus and prints the
  report.
- AC-12: a broken corpus exits `2`, a score under the floor exits `1`, a good
  run exits `0`.
- `--min-narration` sets the floor; the default is the committed one.

*Change* — `code_reviewer/evaluate.py`, and a CI job beside the existing one.

## Step 6 — The corpus is real

*Tests* — `tests/unit/test_narration_baseline.py`

- AC-13: the shipped corpus holds its floor, run against the real checks.
- Every fixture on disk is referenced by a case, the way Level 12 asserts it.
- At least one case is a *bad* review — a hallucinated citation, a claimed
  verdict — so the harness is known to be able to fail.

## Step 7 — Documentation

- AC-14: `tests/unit/test_architecture.py` gains the rule that nothing in the
  review path imports the grader.
- `docs/adr/0023-the-prose-is-graded-by-code.md`: D-1, D-2, D-3.
- `capability-sources.md`: C-02 and C-03 corrected to name both levels, C-21
  added with its source.
- `README.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`, the roadmap table.

## Order and rationale

The checks come before the loader because the checks are the level: a corpus
that loads strictly and grades nothing is a filing system. The command comes
last because a floor cannot be chosen before the first measurement is taken,
which is exactly how Level 12 sequenced it — and the number it picks has to be
the measured one, not the hoped-for one.
