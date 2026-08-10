# Level 25 — A measurement that says how much it knows

## Problem statement

[Level 21](../level-21/spec.md) built the instrument that grades the reviewer's
prose, and refused three things in the same document:

> **A statistically meaningful corpus.** Twelve recorded reviews is not a
> sample.

> **Calling the model in CI.** The corpus holds *recorded* outputs.

> **Changing what the reviewer says.** This level builds the instrument. Tuning
> is a different job.

The corpus has since grown to fifteen and holds at 1.00, and that number is
quoted in the README, in the CHANGELOG and in every level report. It is a true
number about a small sample, presented as though the two were the same thing.

Concretely, today:

- **A perfect score says nothing about how much was tested.** `1.00 over 15
  cases` and `1.00 over 1500` are printed identically. The first is consistent
  with a real pass rate of 80 %.
- **Some checks are graded by two cases and some by fifteen**, and nothing says
  which. A check exercised twice can be broken in a way the corpus cannot see,
  and the aggregate hides it — which is exactly the defect the self-review of
  levels 21–22 found by hand.
- **A prompt edit still ships unmeasured.** The corpus grades recordings; a
  recording is a fact about the day it was captured. Level 20 records *which*
  prompt produced a review, and Level 21 grades a review no current prompt
  produced.
- **Nothing compares two runs.** Even with a live measurement, "is this better
  than last week" needs a stored baseline and a delta, and there is neither.

Capabilities addressed: **C-27** (a score that states its own uncertainty),
**C-28** (measuring the model that is actually configured), **C-29** (comparing
one measurement against another). All three come from Level 21's own non-goals.

## Goals

1. Every score is reported with a **confidence interval**, and the floor is
   checked against the interval's lower bound rather than against the point
   estimate.
2. **Per-check coverage** is reported and floored: a check no case exercises,
   or one only a single case exercises, is named as such.
3. The corpus **grows**, chosen by where coverage is thinnest rather than by
   what is easy to write.
4. A **live mode** grades what the configured model produces now, from the same
   cases, so a prompt or model change is measurable.
5. A **baseline** can be written and compared against, keyed by what produced it
   — model and prompt fingerprint — so a delta is attributable.

## Non-goals

- **Claiming the corpus is now large enough.** It will not be. The point of the
  interval is that the report stops implying otherwise; a fifteen-case corpus
  reporting `1.00 [0.78, 1.00]` is honest, and a fifty-case one reporting
  `1.00 [0.93, 1.00]` is honest about something better. Neither is a sample
  anybody should generalise from, and the docs will not say they are.
- **Calling a model in the default test run.** `--live` is opt-in and needs an
  endpoint. CI keeps grading recordings, because a test suite whose result
  depends on a remote service is a test suite that fails for reasons unrelated
  to the code.
- **Tuning the prompt in this level.** The instrument for it is what ships:
  live measurement plus an attributable baseline and a delta. Performing the
  tuning needs a model endpoint this repository does not have, and reporting a
  tuning that did not happen would be the defect Level 23 exists to catch. What
  the level *can* honestly claim is stated and no more.
- **An LLM judge.** Unchanged from [ADR 0023](../../adr/0023-the-prose-is-graded-by-code.md):
  the grader stays code.
- **A statistical framework.** One interval, computed one way, named in the
  output. Not a library, not a hypothesis test, not a p-value nobody asked for.
- **Grading style, fluency or helpfulness.** Unchanged from Level 21.

## Behavioural contracts

### C-1 — A score is never reported without its interval
Every rendered score carries a lower and upper bound and the sample size that
produced them. A bare `1.00` does not appear in any output this level touches.

### C-2 — The floor is checked against the lower bound
A corpus too small to distinguish 1.00 from 0.80 does not clear a 0.95 floor by
being lucky. This makes small corpora *harder* to pass, on purpose: the way to
clear a floor is more cases, not a better afternoon.

### C-3 — Coverage is per check, and thin coverage is named
The report states how many cases exercise each check. A check with no case is an
error; a check under the stated minimum is a warning that names it.

### C-4 — Live mode grades what is configured now
`--live` runs the configured reviewer over each case's inputs and grades the
output it produces. The recorded output is not consulted.

### C-5 — Live mode is opt-in and fails as *cannot measure*
Without an endpoint, `--live` exits `2` — the measurement could not be taken —
and never `1`. A test suite that needs a remote service is not a test suite.

### C-6 — A baseline names what produced it
Model, prompt fingerprint, corpus size, date, and every per-check rate. A
baseline that cannot say which prompt produced it cannot support a delta.

### C-7 — A comparison reports per-check movement, not one number
"Better" is not a scalar. The delta names which checks rose, which fell and
which were not exercised in one of the two runs.

### C-8 — A comparison across different corpora refuses
Two runs over different case sets are not comparable, and reporting their
difference as movement would be the most confident wrong number this repository
could produce.

### C-9 — Nothing here changes a review
Measurement is measurement. No prompt is edited by this level, and the review
path is untouched.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A score renders with a lower bound, an upper bound and a sample size | Renderer test |
| AC-2 | 15/15 successes yields a lower bound well below 1.00 | Unit test |
| AC-3 | 150/150 yields a tighter lower bound than 15/15 | Unit test |
| AC-4 | A zero-case corpus yields `[0, 1]` rather than a division by zero | Unit test |
| AC-5 | The floor is applied to the lower bound, and a small corpus fails a floor its point estimate would clear | Threshold test |
| AC-6 | Per-check case counts are reported | Renderer test |
| AC-7 | A check no case exercises is an error, not a silent absence | Corpus test |
| AC-8 | A check under the minimum coverage is named in the output | Renderer test |
| AC-9 | The shipped corpus exercises every check at least the stated minimum | Dataset test |
| AC-10 | `--live` grades freshly produced output and ignores the recording | Service test |
| AC-11 | `--live` with no endpoint exits `2` | CLI test |
| AC-12 | `--live` is not reachable from the default test run | Suite test |
| AC-13 | A written baseline carries model, prompt fingerprint, corpus size and per-check rates | Unit test |
| AC-14 | A comparison names which checks rose and which fell | Renderer test |
| AC-15 | A comparison across different corpora refuses | Unit test |
| AC-16 | A comparison against a baseline from a different prompt says so | Renderer test |
| AC-17 | No output claims the corpus is large enough | Renderer test |
| AC-18 | The review path is unchanged | Architecture test |
| AC-19 | The six checks stay green, coverage holds, all three eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval ×3 |

## Decisions taken

**D-1 — Wilson, and named in the output.** The interval is a Wilson score
interval, chosen because it behaves at the boundary: 15 successes out of 15 has
a normal-approximation interval of exactly `[1.00, 1.00]`, which is the answer
that caused the problem. The method is named where the number is printed, so
nobody has to guess which convention produced it.

**D-2 — The floor moves to the lower bound.** The alternative — floor the point
estimate and print the interval beside it — leaves the gate exactly as
permissive as it was and adds decoration. Making a small corpus fail is the
behaviour that turns "the corpus is small" from a caveat into a task.

**D-3 — Coverage is per check because failure is per check.** An aggregate over
five checks is five different questions averaged. The self-review of levels
21–22 found a check that fired on three phrasings of eight, and the aggregate
score never moved.

**D-4 — Live mode exists; tuning does not.** This level ships the instrument
for measuring a prompt change and does not make one. Shipping a tuned prompt
"measured" against a model nobody ran would be inventing a result, which is
worse than shipping the instrument alone.

**D-5 — A baseline is keyed by what produced it.** Model and prompt fingerprint,
both of which Level 20 already computes. A delta between two runs that cannot
name what differed between them is a number without a subject.
