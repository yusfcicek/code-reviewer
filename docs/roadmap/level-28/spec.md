# Level 28 — Earning the floors

## Problem statement

Three harnesses hold three floors, and every one of them is the most its corpus
can carry rather than a number anybody would choose:

| corpus | graded observations | lower bound | floor |
|---|---:|---:|---:|
| analyzers | 10 findings | 0.72 | 0.70 |
| documentation | 6 findings | 0.61 | 0.60 |
| drift retrieval | 5 cases | 0.57 | 0.35 |

Level 25 made the floor mean something stricter and, in doing so, made the
corpora the binding constraint. Level 27 measured `DOCS` against the blocking
question and answered *no*, with the arithmetic: about a hundred graded findings
to support 0.95.

So the honest next move is not a new capability. It is the one thing this project
has said since Level 12 and never once done in the forward direction: **a floor
is earned by the level that measured it — so earn some.**

The arithmetic, for perfect scores:

| observations | lower bound |
|---:|---:|
| 16 | 0.80 |
| 35 | 0.90 |
| 73 | 0.95 |

Capability addressed: **C-35** — the measurements are strong enough to be worth
gating on. Sourced from Level 25's non-goals (*"claiming the corpus is now large
enough"*) read forwards rather than as a refusal.

## Goals

1. Each of the three corpora reaches **at least sixteen graded observations**, so
   each floor can rise to 0.80.
2. Cases are chosen by **where the harness is blind**, not by what is quick — and
   the choice is auditable, because each harness now reports its own coverage.
3. The floors rise to what the enlarged corpora support, and the arithmetic is
   recorded beside each number.
4. Whether `DOCS` may block is asked again against the new measurement, and
   answered by the number.

## Non-goals

- **Reaching 0.95.** Seventy-three graded observations per corpus is a different
  level's worth of authoring, and pretending otherwise would produce cases
  written to be counted. This level goes to sixteen and says so.
- **Weakening a case to make it pass.** A case exists to be able to fail. If the
  enlarged corpus finds a real defect in an analyzer, a rule or the retriever,
  that defect is fixed and the finding is part of the level — the bargain every
  level here has made with its own gate.
- **Growing a corpus by duplication.** Two cases exercising one rule on one shape
  are one case counted twice, and the coverage report would say so.
- **Changing what any rule does.** Unless a new case proves it wrong, which is
  the only reason this level would touch a rule at all.
- **A new harness.** Four is enough; this level feeds them.

## Behavioural contracts

### C-1 — Every corpus reaches sixteen graded observations
Not sixteen files: sixteen things scored. A case that expects nothing contributes
to precision and not to the count, which is why the count is of *observations*.

### C-2 — A new case is justified by a coverage gap, in writing
Each carries the reason it was added — a rule with no case, a check demonstrated
once, a retrieval shape nothing exercised. The coverage reports Levels 25 and 26
built are the input.

### C-3 — Duplicates are refused
A case whose rule and shape are already covered adds nothing but a number, and
the reviews here have found twice that a bigger number is the easiest thing to
fake.

### C-4 — A floor rises only to what the corpus supports
0.80 where sixteen observations are reached, and no higher. The arithmetic sits
beside each constant.

### C-5 — A real defect found by a new case is fixed, not annotated away
Level 12's rule, and Level 13 already honoured it once when a case recorded a
recall gap the suite could not find.

### C-6 — The blocking question is asked again and answered by the number
If 0.80 is not enough to block on, that is the answer and the level says which
number would be.

### C-7 — Nothing about the review path changes
No prompt, no gate, no severity — unless a new case proves one wrong.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | The analyzer corpus reaches ≥16 graded findings | Baseline test |
| AC-2 | The documentation corpus reaches ≥16 graded findings | Baseline test |
| AC-3 | The retrieval corpus reaches ≥16 cases | Baseline test |
| AC-4 | Every analyzer namespace still has a case, and each new rule covered is named | Dataset test |
| AC-5 | No two cases exercise the same rule on the same shape | Dataset test |
| AC-6 | Every new case states why it was added | Dataset test |
| AC-7 | The analyzer floor rises to 0.80 on the lower bound | Baseline test |
| AC-8 | The documentation floor rises to 0.80 | Baseline test |
| AC-9 | The retrieval floor rises to what sixteen cases support | Baseline test |
| AC-10 | Every retrieval case still hides its answer among more sections than the limit | Baseline test |
| AC-11 | Any defect a new case exposes is fixed rather than annotated | The level's report |
| AC-12 | The blocking answer is restated against the new number | Baseline test |
| AC-13 | The six checks stay green, coverage holds, all four floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval ×4 |

## Decisions taken

**D-1 — Sixteen, because sixteen is 0.80.** A round target chosen from the
arithmetic rather than from ambition: it is reachable by authoring, it doubles
what two of the corpora have, and it makes every floor a number somebody would
recognise as a floor.

**D-2 — Coverage reports choose the cases.** Levels 25 and 26 built per-check and
per-rule coverage precisely so that "what is missing" stops being a matter of
taste. This level is the first to spend them.

**D-3 — A defect found is a defect fixed.** The alternative — annotating the case
to match the behaviour — is the one move that would make every number in this
repository worthless, and it is the move the last four self-reviews each found a
version of.

**D-4 — Stop at 0.80 and say so.** 0.95 needs seventy-three observations per
corpus. Writing them would be worth doing; claiming to have written them, or
writing shallow ones to reach the count, would not.
