# Self-review of Level 24

**Method** the one the last three rounds established: run the attacks and count
what survives, rather than reading what the code says about itself. Every result
below was produced by executing the shipped code.

The level's whole argument is *"we say exactly what this buys and no more."* So
the question this review asked was the obvious one: **is that sentence true?**

Twice, it is not.

| # | Severity | What |
|---|---|---|
| S-01 | 🔴 | A signed store can be **truncated at the tail** and still verifies |
| S-02 | 🔴 | An **unsigned** store detects nothing an attacker with the tool does |
| S-03 | 🟠 | An undated record is **destroyed** by every age-based erasure |
| S-04 | 🟠 | Timestamps are compared as strings, so an offset survives erasure |

---

## S-01 — a prefix of a valid chain is a valid chain

```
signed store, five records, last three deleted  ->  intact
```

Truncation is the oldest attack on a hash chain and the level does not detect
it. Every link that remains is correct and every signature that remains is
valid, because the store carries nothing that says how long it should be.

The consequence is not theoretical. The record somebody wants gone is usually
the **most recent** one — the blocking verdict from an hour ago — and deleting
the tail is both the easiest edit and the one this level reports as sound.

Worse, the claim is written down:

> *README, ADR 0026, CHANGELOG:* "a deleted or reordered line is detectable
> without trusting the file's length"

That is false for the tail, and it is the sentence in a level whose subject is
not overclaiming. Level 23 was built to catch documentation that claims
behaviour the code does not have; here it is, in the ADR.

**What can honestly be done:** truncation is undetectable from the file alone —
any anchor inside it can be truncated with it. What the store *can* do is carry
a **sequence number** per record, so a verifier reports "this store ends at
sequence 412" and an operator with any external anchor (a monitoring counter, a
previous run's output, a note) can compare. That is a real improvement and it is
not detection, so it will be described as what it is.

## S-02 — an unsigned chain is evidence about accidents, not attackers

```
unsigned store, one record edited, every seal recomputed  ->  intact
```

Of course: the digest takes no key. Anybody who can edit the file can run the
same three lines the sink runs. An unsigned chain detects a careless edit — the
`sed` that changed a verdict and left the digests alone — and detects nothing at
all from somebody who has the tool.

The code calls this "the cheaper guarantee" and never says what it is cheaper
*than*. A deployment reading that has been told it has integrity protection when
what it has is a corruption check.

## S-03 — the record it cannot date is the record it deletes

```
store: one record with no `recorded_at`, one from 2026-07
erase --before 2026-01-01                      ->  the undated record is removed
```

`"" >= before` is false, so an undated record falls through every guard and
matches. The one record whose age is unknown is the one that must **not** be
removed by an age policy, and it is the only one that was.

## S-04 — ISO timestamps compared as strings

```
record  2026-06-01T05:00:00+03:00   (= 02:00Z)
cutoff  2026-06-01T03:00:00+00:00
instant: the record is older        -> should be erased
strings: "…05:00…" >= "…03:00…"     -> survives
```

An erasure request that leaves the data in place is the failure mode with a
legal consequence attached, and any store written by a runner in a non-UTC zone
is exposed to it.

---

## What this round says about the tests

Level 24 has 22 erasure tests and 20 chain tests, and none of them found any of
this. They are all built from **fixtures this level wrote**: records with the
same timestamp format, tampers of the kind the spec listed, stores produced by
the sink two lines earlier.

The four findings came from a different question: *what would somebody who wants
a record gone actually do?* Delete the newest lines. Run the tool they already
have. Feed it a record with a missing field. Deploy in Istanbul.

That is the same lesson as the last two rounds, and it is worth stating in the
form it keeps taking: **a test written from the specification tests the
specification.** The specification is what was wrong.
