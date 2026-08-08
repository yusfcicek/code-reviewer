# Level 12 — the baseline, and what taking it found

Two measurements. The first is what the instrument read on the day it was
built; the second is the same instrument after Level 13 acted on what it said.

## After Level 13 (2026-08-09)

| Metric | Level 12 | Level 13 |
|---|---|---|
| Cases | 8 | 10 |
| True positives | 8 | 10 |
| False positives | 0 | 0 |
| False negatives | 1 | 0 |
| Precision | 1.00 | 1.00 |
| Recall | 0.89 | **1.00** |
| F1 | 0.94 | **1.00** |
| Ungraded findings | 2 | 1 |
| Floors in CI | 0.95 / 0.85 / 0.90 | **0.95 / 0.95 / 0.95** |

E-01 and E-02 are both closed, and both were closed *against* the harness: the
`parameterised-query` case was added in the same commit as the taint pass,
holding every safe spelling, so a fix that overreached would have shown up as
lost precision rather than as an opinion. It did not. The `dead-private-helper`
case does the same job for E-02 in the other direction — it stops the narrowing
becoming a removal by neglect.

With ten expectations, one new false positive now puts precision at 0.91 and
fails the gate. That is what raising a floor buys.

## As first measured (Level 12)

Measured on 2026-08-09, `StaticAnalysisSuite` with no policy file, over the
eight cases in `evaluation/` as they then stood.

| Metric | Value |
|---|---|
| Cases | 8 |
| True positives | 8 |
| False positives | 0 |
| False negatives | 1 |
| Precision | 1.00 |
| Recall | 0.89 |
| F1 | 0.94 |
| Ungraded findings | 2 |

Floors committed at the time: precision **0.95**, recall **0.85**, F1 **0.90**
— the baseline minus a margin, per decision D-4. They are asserted twice: by
the `evaluate` job, and by `tests/unit/test_evaluation_baseline.py` so that a
change that breaks them fails locally before it reaches a pipeline.

## Per rule

| Rule | TP | FP | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| `PERFORMANCE.HIGH_COMPLEXITY` | 1 | 0 | 0 | 1.00 | 1.00 |
| `QUALITY.SOLID_SRP` | 1 | 0 | 0 | 1.00 | 1.00 |
| `SAST.HARDCODED_SECRET` | 2 | 0 | 0 | 1.00 | 1.00 |
| `SAST.SQL_INJECTION` | 1 | 0 | 1 | 1.00 | 0.50 |
| `SAST.WEAK_CRYPTO` | 2 | 0 | 0 | 1.00 | 1.00 |
| `SEMANTIC.BREAKING_CHANGE` | 1 | 0 | 0 | 1.00 | 1.00 |

## What the instrument found on its first run

Two observations, neither acted on in Level 12. This level built the
instrument; pointing it at the analyzers was the next level's work, and the
spec's non-goals said so. Both were closed in Level 13, and the outcome is the
table above.

**E-01 — SQL injection is missed when the query is built into a local.**
`SAST.SQL_INJECTION` matches `execute\s*\([^)]*\+` — a single line. The
`find_by_name` fixture concatenates into a variable and executes the variable,
which is the ordinary way anyone writes it, and the rule sees nothing. This is
the whole of the committed recall gap.

Closing it means the analyzer has to follow an assignment, which is a taint
question rather than a pattern question. That is a change with a false-positive
budget of its own, and it now has an instrument to spend it against.

**Closed in Level 13** by `analyzers/sql_taint.py`, an AST pass over Python
that follows local assignments within one scope and reports at the line where
the string was built. Precision did not move.

**E-02 — `SEMANTIC.UNREFERENCED_IN_FILE` fires on a module's only public
function.** A public API is called from outside the module it is defined in;
reporting that as an integrity issue is arguably noise. The `breaking-change`
case is scoped to `SEMANTIC.BREAKING_CHANGE` rather than `SEMANTIC.*`, so the
rule shows up in the report's ungraded count instead of being charged as a
false positive or blessed as ground truth. Deciding which it is needs a
judgement about the rule, not about the dataset.

**Closed in Level 13** by narrowing the rule to names with a single leading
underscore. A private function referenced only by its own definition genuinely
has no callers — module scope says so — and that case is worth reporting. The
`breaking-change` case widened to `SEMANTIC.*` as a result.

The second ungraded finding, `PERFORMANCE.MEMORY_LEAK` on the SQL injection
fixture's unclosed cursor, is a true report of something the case is not about.
It is the ordinary reason a scope exists.
