# Level 29 — Plan

Branch: `feature/level-29-prompt-alignment`, off `development`, merged with
`--no-ff`.

The order matters in one place: **measure first, then edit the prompt.** Editing
the prompt and then writing the measurement would produce a measurement that
passes, and this repository has found that shape four times.

## Step 1 — The domain: what a check needs the prompt to say

*Tests* — `tests/unit/domain/test_alignment.py`

- `Expectation`: the phrases a check needs, and how many must appear. `ALL` for
  a rule with two halves ("cite `path:line`" *and* "only lines that exist"),
  `ANY` where a prompt may phrase one idea two ways.
- `sections_demanded(prompt)`: the headings an output format asks for, taken
  from the Markdown rather than from a list somebody keeps in step.
- `alignment(prompt, expectations, checked, declined)`: the report — `unbacked`,
  `ungoverned`, `aligned`, in that order of interest.
- Pure. No I/O, no model, no clock (AC-6).

*Change* — `code_reviewer/domain/alignment.py`.

## Step 2 — The expectations, beside the checks

*Tests* — `tests/unit/domain/test_narration_checks.py` (extended)

- One `Expectation` per check in `CHECKS`, in the same module, so a new check
  with no expectation fails a test rather than passing silently (AC-1).
- `UNCHECKED_SECTIONS`: the headings nothing grades, each with its reason, in
  the shape `fix_recipes.DECLINED` established. An empty reason is refused
  (AC-4).

*Change* — `code_reviewer/domain/narration.py`.

## Step 3 — The report, and what it refuses to say

*Tests* — `tests/unit/application/test_alignment_report.py`

- Markdown: the unbacked checks by name with what was looked for, the
  ungoverned headings, and the declined ones with their reasons.
- The sentence about the endpoint, in the same words every time (AC-5, C-6).
- No ratio anywhere in it (C-5, D-2).

*Change* — `code_reviewer/application/alignment_report.py`.

## Step 4 — The command

*Tests* — `tests/unit/test_evaluation_cli.py` (extended)

- `--alignment`: reads the shipped prompt through the same accessor
  `prompt_fingerprint` uses, so the thing measured is the thing that runs.
- `0` aligned, `1` a gap, `2` the prompt could not be read (AC-7).
- Both pipelines run it; `test_ci_gates.py` learns the fifth mode (AC-8).

*Change* — `code_reviewer/evaluate.py`, `.github/workflows/ci.yml`,
`.gitlab-ci.yml`.

## Step 5 — Close what the measurement found

*Tests* — `tests/unit/test_alignment_baseline.py`

- The shipped prompt: no unbacked check, no ungoverned heading (AC-9).
- Three instructions to write, from step 1's output: citations, the verdict, and
  severity backing. Additive and minimal — this is not tuning, and the
  distinction is the level's own non-goal.
- The two ungoverned headings get an answer: a check, or a written reason.
- The fingerprint changes, which the narration corpus already reports for every
  case. Recording it again needs an endpoint and is named rather than faked.

*Change* — `code_reviewer/infrastructure/llm/review_agent.py`.

## Step 6 — Say it once, truthfully

- ADR 0031: the prompt and the checks over its output are one artefact.
- `capability-sources.md`: C-36.
- README, CHANGELOG, version 2.23.0.
- The report states, in one place, the two questions that need an endpoint.

The dogfooding gate runs this level against itself.
