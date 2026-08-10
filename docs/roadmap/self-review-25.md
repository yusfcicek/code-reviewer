# Self-review of Level 25

**Method** unchanged: run the arithmetic and compare it against what the report
says about itself.

This level's subject is a number that does not imply more than it knows. So the
question this review asked was whether **its own numbers** do. Two of them do,
and one of the two is what set a floor.

| # | Severity | What |
|---|---|---|
| S-01 | 🔴 | The narration interval treats correlated checks as independent, and a floor was set from it |
| S-02 | 🔴 | The F1 "interval" is not an interval for the number printed beside it |
| S-03 | 🟠 | A baseline predating a check reports a rise from nothing |
| S-04 | 🟡 | A live run where nothing could be measured exits `1` rather than `2` |

---

## S-01 — 120 observations that are 24

```
reported          1.00 [0.97, 1.00] over 120
one case, one observation   1.00 [0.86, 1.00] over 24
```

The narration score counts 24 cases × 5 checks and hands 120 to Wilson as though
they were 120 independent trials. They are not, and the corpus makes the
dependence obvious: a review with no sections fails `required_sections_are_present`
*and* usually `severe_findings_are_mentioned`, because the sections that would
have mentioned the finding are the ones that are missing. Level 25's own new
case `only-a-security-section` is exactly that shape.

Treating them as independent narrows the interval from `[0.86, …]` to
`[0.97, …]`. And **the narration floor of 0.95 was chosen from the narrow
number** — a floor derived from an overclaim, in the level built to remove
overclaims.

## S-02 — an interval around a different number

```
precision  0.80 [0.49, 0.94] over 10
recall     0.80 [0.49, 0.94] over 10
f1         0.80 [0.55, 0.95] over 12    <- the bounds belong to 0.83, not 0.80
```

F1 is a harmonic mean, not a proportion, so it has no sample of successes to put
an interval around. The code manufactured one: `wilson(round(f1 * total), total)`
with `total` set to every graded outcome. The result's own point estimate is
0.8333 while the number printed beside it is 0.80 — the bounds are an interval
for a quantity that is not on the line.

The docstring says it is "not a derivation anybody should quote in a paper",
which is an admission rather than a fix: the report prints it in the same column
as the other two, and **a committed floor is applied to it.**

F1 is monotone increasing in both precision and recall, so a real conservative
bound is available for free — the harmonic mean of the two bounds. That is a
statement that can be defended, and it is what should have been there.

## S-03 — a rise from nothing

```
baseline recorded when the corpus had one check
compare -> four checks reported as +1.00 each
```

`baseline.rates.get(check, 0.0)` reads a check the baseline never measured as a
rate of zero, so adding a check to the corpus renders as the reviewer improving
on four fronts at once. This is the same error class the level refused
elsewhere — attributing a corpus edit to the thing being measured — and it slipped
through because the corpus-set refusal compares *case names* and nothing compares
*check names*.

## S-04 — nothing measured, reported as measured badly

A live run where every case fails produces zero graded cases, an interval of
`[0, 1]`, a lower bound of 0.0 and therefore exit `1`. But nothing was measured:
that is exit `2`, and the distinction is one this repository has enforced since
Level 10 and re-enforced in Level 24 three commits ago.

---

## What this round says about the level

Two of the four are the level committing its own headline sin at one remove. It
went looking for numbers that imply more than they know, found them in Level 12's
output, fixed those — and printed two of its own on the way past.

The pattern worth naming: **a number becomes credible by being formatted like
the ones beside it.** `f1 0.80 [0.55, 0.95] over 12` is believable because
precision and recall above it are real. The narration `[0.97, 1.00]` is
believable because the machinery that produced it is the same machinery that
produced the honest ones. Formatting is not evidence, and a column is not a
derivation.
