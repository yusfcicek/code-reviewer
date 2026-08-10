# Level 28 — Plan

Branch: `feature/level-28-earned-floors`, off `development`, merged with
`--no-ff`.

One order matters: **read the coverage, then write cases, then raise the floor.**
Raising a floor first and authoring until it passes is how a corpus becomes a
number rather than a measurement.

## Step 1 — Read what is blind

*Tests* — none; this step produces a list.

- The analyzer dataset: which of the 39 emittable rules has no case.
- The documentation corpus: which of the five `DOCS` rules is graded once.
- The retrieval corpus: which retrieval shapes are absent — a section in a
  document the change does not name, a change touching two files, a document with
  one section, a section that is genuinely unrelated and must *not* come back.
- Recorded in the level's report so the choices are auditable rather than
  remembered.

## Step 2 — The analyzer corpus to sixteen graded findings

*Tests* — `tests/unit/test_evaluation_baseline.py` (extended)

- Six more graded findings, chosen from the uncovered rules in step 1 — the
  namespaces that currently rest on one or two cases each.
- AC-5: no two cases exercise the same rule on the same shape. A duplicate is a
  number, and the reviews here have twice found that a bigger number is the
  easiest thing to fake.
- Any case that fails is a defect in an analyzer, and it is fixed (AC-11).

*Change* — `evaluation/cases/`, `evaluation/fixtures/`.

## Step 3 — The documentation corpus to sixteen

*Tests* — `tests/unit/test_documentation_baseline.py` (extended)

- Ten more graded findings. The corpus is thirteen cases and six findings,
  because seven cases deliberately expect nothing — so this step adds *positive*
  cases without dropping the negative half below its own share.
- Each `DOCS` rule reaches at least three demonstrations, matching the minimum
  Level 25 set for narration checks and for the same reason.

*Change* — `evaluation/documentation/`.

## Step 4 — The retrieval corpus to sixteen cases

*Tests* — `tests/unit/test_retrieval_baseline.py` (extended)

- Eleven more cases, the heaviest authoring in the level.
- AC-10 holds for every one: the answer hides among more sections than the limit
  asks for. A case that cannot fail is what self-review 27 was about.
- At least one case where **no** section is related and the expected answer is
  that nothing should be retrieved — the negative direction, which the corpus
  has none of and which is where a retriever that returns everything gets caught.

*Change* — `evaluation/retrieval/`, and the measurement if a "nothing should
match" case needs one.

## Step 5 — Raise the floors, with the arithmetic beside them

*Tests* — the three baseline tests

- 0.80 where sixteen observations were reached; the number the corpus supports
  where they were not.
- Each constant carries the count and the bound it comes from, so the next person
  reads the derivation rather than trusting the number.
- `identity.py`'s `EVALUATION_BASELINE` moves with the analyzer floor — the pair a
  test already pins because two numbers in two files drift.

## Step 6 — Ask the blocking question again

*Tests* — `tests/unit/test_documentation_baseline.py`

- 0.80 on the lower bound, against a gate that wants 0.95. Answer the question
  with the new number and name what would change it.

## Step 7 — Say it once, truthfully

- ADR 0030: a floor is earned, and what earning one costs.
- `capability-sources.md`: C-35.
- README, CHANGELOG, version 2.22.0, and every quoted floor corrected.

The dogfooding gate runs this level against itself. Whatever it finds is part of
the level — and this time the new cases may find something first.
