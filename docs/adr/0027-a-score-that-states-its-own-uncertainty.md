# ADR 0027 — A score that states its own uncertainty

**Status** Accepted · **Level** 25 · **Supersedes** nothing ·
**Depends on** [0023](0023-the-prose-is-graded-by-code.md)

## Context

Since Level 12 this repository has printed a score and a case count beside each
other and treated them as one fact. `precision 1.00, recall 1.00, F1 1.00 over
eleven cases` appears in the README, the CHANGELOG, every level report and the
run identity stamped into every decision record.

Both halves are true. Together they are misleading, and the arithmetic says by
how much:

```
1.00 over    10 findings  ->  1.00 [0.72, 1.00]
1.00 over    15 cases     ->  1.00 [0.80, 1.00]
1.00 over  1500 cases     ->  1.00 [1.00, 1.00]
```

Ten of ten is consistent with a real pass rate of seventy-two per cent. The
report printed it identically to a measurement a hundred and fifty times larger.

Two further gaps sat behind it. **An aggregate over five checks is five
different questions averaged**: the self-review of levels 21–22 found a check
that caught three phrasings of eight and the score never moved. And **coverage
was counted in one direction only** — every narration check was passed by
thirteen or fourteen cases and demonstrated *firing* by exactly one, which is
precisely how the three-of-eight defect survived a corpus built to demonstrate
that check.

## Decision

**Every score is reported with a Wilson interval, and the floor is applied to
the lower bound.**

Wilson rather than the normal approximation, because the normal approximation
gives `[1.00, 1.00]` at fifteen of fifteen: it divides by an estimated variance
that is zero when nothing failed, and so answers "how uncertain are you" with
"not at all" exactly where the honest answer is "we barely looked". The method
and the confidence level are printed beside the number, so nobody has to guess
which convention produced a figure they are about to quote.

**The floor moves to the lower bound rather than sitting beside it.** This makes
the gate strictly harder, which is the point: the way to clear a floor becomes
writing more cases rather than having a better afternoon. Flooring the point
estimate and printing the interval as decoration would have left the gate
exactly as permissive as it was.

Two consequences were accepted rather than worked around.

**The committed floors went down.** 0.95 on the lower bound is a claim ten
graded findings cannot support, so the analyzer floor is 0.70 and the
documentation floor is 0.60 — the most those samples carry. That is not a floor
lowered to make a build green, which is what the harness exists to prevent; it
is the floor coming to mean something stricter than it did, and the only way to
raise it now is to write cases.

**A dataset that measures nothing stops clearing every floor.** A case the suite
correctly stays quiet about produces no true positives and no false positives:
it used to divide nothing by nothing and pass, and now reports `[0, 1]` and says
the corpus is too small to say.

**Coverage is counted per check and in both directions.** How many cases pass a
check, and how many demonstrate it firing. A check below three demonstrations is
named in the report rather than averaged away, because one example pins one
author's idea of a check.

## Consequences

**The corpus grew where the report said it was thin.** Nine narration cases,
chosen from the coverage table rather than from what was easy to write: three
demonstrations per check, each a different way of getting the same thing wrong.

**A prompt edit is measurable.** `--live` grades what the configured reviewer
produces now, from the same cases, and never runs in the default suite — a test
suite whose result depends on a remote service fails for reasons unrelated to
the code. A model that fails one case costs that case and is named: "the model
timed out" and "the model wrote something wrong" are different facts.

**A delta has a subject.** A baseline carries the model and the prompt
fingerprint that produced it, and a comparison reports per-check movement. Two
runs over different case sets are refused rather than differenced, because
presenting that as movement would attribute a corpus edit to a prompt edit.

**No output claims the corpus is adequate**, and a test greps for the words. The
interval is the honest form of that sentence.

**This level measures and does not tune.** The instrument for measuring a prompt
change is what ships; performing the change needs an endpoint this repository
does not have, and reporting a tuning that did not happen would be the defect
[ADR 0025](0025-two-tiers-and-the-weaker-one-is-a-separate-namespace.md) and
Level 23 exist to catch.

## Alternatives considered

**Print the interval, floor the point estimate.** Rejected: decoration. The gate
would be exactly as permissive and the report would look more rigorous, which is
the worst combination available.

**A normal-approximation interval.** Rejected because it fails at precisely the
boundary this repository lives on — every corpus here scores 1.00.

**A hypothesis test and a p-value.** Rejected as a framework nobody asked for.
One interval, computed one way, named in the output, is a number a reader can
hold.

**Grow the corpus until 0.95 clears on the lower bound.** That needs roughly two
hundred graded findings per corpus. Worth doing and not worth pretending to have
done: the floors say what the samples support today, and a later level that adds
the cases earns the higher number.
