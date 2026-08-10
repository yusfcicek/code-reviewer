# Self-review of Level 27

**Method** unchanged, and this time it turns on one question: **can the
measurement fail?**

The level exists because Level 23 shipped a tier whose complete absence was
indistinguishable from its working. The first finding is that its replacement has
the same property.

| # | Severity | What |
|---|---|---|
| S-01 | 🔴 | The retrieval measurement cannot fail: every case returns every section |
| S-02 | 🔴 | Any one-removal, one-addition diff is called a rename, whatever the two are |
| S-03 | 🟠 | The only informative number in the report is not floored |

---

## S-01 — a corpus with no haystack

```
case                            sections   limit   can it miss?
exit-codes                             3       3   no
forgetting                             3       3   no
gate-reads-findings-not-prose          3       3   no
memory-keeps-identifiers               3       3   no
suppression-reason-required            3       3   no
```

Every case carries three document sections and the measurement asks for the top
three. **Every section is returned, always.** Recall is 1.00 by construction, and
would stay 1.00 if the retriever ranked at random, returned its input unchanged,
or scored by string length.

The floor of 0.55 is therefore held by arithmetic rather than by the retriever,
and the ADR, the CHANGELOG, the README and the level report all quote the number
as though it measured something.

This is exactly the defect the level was built to close. Level 23's tier could
return nothing and nobody could tell; Level 27's measurement can return
everything and nobody can tell. The shape is identical — a check whose outcome is
independent of the thing it checks — and I built the second one while writing an
ADR about the first.

The fix is a haystack: sections a reader would not pick, in the same documents,
enough of them that a limit of three is a choice rather than a formality.

## S-02 — a rename is two things of the same kind

```
diff                                          rename_in says
a function removed, a constant added          start_app -> MAX_RETRIES
a class removed, a function added             OldGate   -> evaluate
a flag removed, another flag added            --legacy  -> --modern
a genuine rename                              start_app -> create_app
```

Only the last two are renames. The first two are a deletion and an unrelated
addition, and `rename_in` calls them a rename because it counts names without
asking what kind of name each is. The consequence is a **one-click button that
substitutes the wrong word into somebody's README** — the failure Level 22's
declining discipline exists to prevent, and the same shape as self-review 26's
S-02: a recipe acting on a shape it did not verify.

`scope_from_diff` is the reason the information is missing: it returns bare
names, having thrown away whether each came from a `def`, a `class`, a constant
or a quoted flag. A rename needs both sides to be the same kind.

## S-03 — the number that means something is not the one with the floor

`first_rank_share` is 60 %: three of five cases put the related section first.
That is the only figure in the report that a retriever could fail, and nothing
holds it to anything. Recall — the floored number — is the one S-01 shows to be
free.

---

## What this round says about the level

S-01 is the level committing, in its own new corpus, the exact defect it was
written to fix. The ADR argues that a tier with no measurement is a tier whose
absence is invisible; the corpus shipped alongside it measures nothing and looks
like a measurement.

The pattern across the last four self-reviews is now hard to miss:

- Level 24 claimed more than the seal bought.
- Level 25 printed two numbers that implied more than they knew.
- Level 26 wrote three recipes against a mental model of their input.
- Level 27 built a measurement that cannot fail.

Every one is a **check that was never tested against the possibility of its own
success being meaningless.** The question that finds them is the same each time,
and it is cheap: *what would this say if the thing it checks were broken?*
