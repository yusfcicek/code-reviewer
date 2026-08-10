# Level 25 — Plan

Branch: `feature/level-25-measured-measurement`, off `development`, merged with
`--no-ff`.

Ordered so the honesty arrives before the capability: the interval and the
coverage report land first, they make the existing corpus look worse, and the
corpus grows in response. Doing it the other way round would be growing the
corpus until a number looked acceptable.

## Step 1 — An interval, and what it does at the boundary

*Tests* — `tests/unit/domain/test_confidence.py`

- AC-2: 15 of 15 yields a lower bound well under 1.00. This is the number the
  level exists for: the normal approximation gives `[1.00, 1.00]` here, which is
  how a fifteen-case corpus came to be quoted like a measurement.
- AC-3: 150 of 150 is tighter than 15 of 15, and 1500 tighter still.
- AC-4: zero cases yields `[0, 1]` rather than dividing by nothing.
- 0 of 15 yields an upper bound well under 1.00 — the interval is symmetric in
  what it refuses to conclude.
- The bounds never leave `[0, 1]`, at any sample size, for any count.
- The method is named on the value, so nobody has to guess which convention
  produced a number they are about to quote.

*Change* — `code_reviewer/domain/confidence.py`.

## Step 2 — Scores that carry their interval

*Tests* — `tests/unit/domain/test_evaluation_scores.py` (extended),
`tests/unit/application/test_narration_report.py`

- AC-1: every rendered score has a lower bound, an upper bound and an `n`.
- AC-17: no output says the corpus is large enough, adequate or representative;
  a test greps for the words.
- The rendered form is stable enough to diff between runs, because that is what
  a delta is read from.

*Change* — the report renderers, and `EvaluationThreshold`.

## Step 3 — The floor moves to the lower bound

*Tests* — `tests/unit/domain/test_thresholds.py`

- AC-5: a corpus small enough that 1.00 is consistent with 0.80 fails a 0.95
  floor. The gate gets *harder*, which is the point: the way to clear it is more
  cases.
- A corpus large enough clears the same floor with the same point estimate.
- The shortfall message names the bound, the floor and the sample size, so the
  reader knows whether to fix the reviewer or write more cases.

*Change* — `EvaluationThreshold.shortfalls`, and the narration floor.

## Step 4 — Coverage, per check

*Tests* — `tests/unit/application/test_narration_coverage.py`

- AC-6: the report states how many cases exercise each check.
- AC-7: a check no case exercises is an error — the same shape as Level 12's
  "no case grades this namespace", and for the same reason.
- AC-8: a check under `MINIMUM_CASES_PER_CHECK` is named rather than averaged
  away.
- A check exercised only by cases that *expect it to fail* is reported as
  uncovered in the direction that matters: a check nothing ever passes is not
  a check anybody has tested passing.

*Change* — `application/narration_evaluation.py`, `narration_report.py`.

## Step 5 — The corpus grows where it is thinnest

*Tests* — `tests/unit/test_narration_baseline.py` (extended)

- AC-9: every check meets the minimum, asserted rather than hoped.
- New cases are chosen from the coverage report produced in step 4, and the
  report is recorded in the level's report so the choice is auditable.
- The corpus README states the new size and repeats that it is not a sample
  anybody should generalise from.

*Change* — `evaluation/narration/*.yaml`.

## Step 6 — Live mode

*Tests* — `tests/unit/application/test_live_narration.py`

- AC-10: `--live` grades what the reviewer produces now; the recording is not
  read, and a test asserts a recording that would fail every check does not
  affect the live result.
- AC-11: no endpoint exits `2`, never `1`.
- AC-12: the default test run never calls a model — asserted by the same kind of
  architecture test Level 22 used for its no-write claim.
- A model that fails on one case costs that case and marks it, rather than
  failing the run: a measurement with a hole in it must say where the hole is.

*Change* — `evaluate.py --live`, `application/live_narration.py`.

## Step 7 — Baselines and deltas

*Tests* — `tests/unit/application/test_baseline_comparison.py`

- AC-13: a baseline carries model, prompt fingerprint, corpus size, date and
  per-check rates.
- AC-14: a comparison names which checks rose and which fell, not one number.
- AC-15: two runs over different case sets refuse to be compared. This is the
  most confident wrong number the repository could produce.
- AC-16: a baseline from a different prompt fingerprint is compared *and
  labelled*, because that is the comparison somebody actually wants — it is the
  same comparison, with the thing that changed named.

*Change* — `application/baselines.py`, `evaluate --write-baseline`,
`--compare-baseline`.

## Step 8 — Say it once, truthfully

- ADR 0027: a score that states its own uncertainty, and why the floor moved to
  the lower bound.
- `capability-sources.md`: C-27, C-28, C-29, sourced from Level 21's non-goals.
- Every place that quotes `1.00 over 15 cases` is corrected to quote the
  interval — README, CHANGELOG, level reports. There are several, and they are
  the reason this level exists.
- Version 2.19.0.

The dogfooding gate runs this level against itself; whatever it finds is part of
the level.
