# 0016 — Memory informs, and never decides

Status: Accepted
Date: 2026-08-09
Level: [14](../roadmap/level-14/spec.md)

## Context

Every review started from zero. `SmartMemoryStrategy` carries findings from one
file to the next inside a run, and then the process exits and takes everything
with it — so a rule that has fired on the same line eleven times looks new
every time, a settled suppression is re-litigated, and a tool that has run 400
times on a repository knows nothing the tool that ran once does not.

Giving it a history raises three questions that are much easier to answer
wrongly than to answer late: what the history is allowed to *do*, what it is
allowed to *contain*, and how it is *found*.

## Decision

### Memory informs; it never decides

No recollection changes a severity, a gate result or an exit code. The report
gains a section naming the findings this project has reported before, with how
often and since when. The prompt gains a table of the same. The verdict is
computed from the findings alone, exactly as
[ADR 0004](0004-findings-drive-the-gate.md) says.

The tempting version of this feature is "downgrade a finding the team has
ignored eleven times". That is a tool learning to stop complaining. The honest
reading of eleven ignored reports is that either the rule is wrong or the debt
is real, and both are decisions for a person — one of which the team can act on
with `review-ignore`, which is already narrow, reasoned and counted
([ADR 0013](0013-suppression-is-narrow-and-counted.md)).

This is asserted rather than asserted-about: `TestMemoryNeverDecides` runs the
same review twice, once against a history of 99 sightings of exactly the
finding it is about to report, and requires the verdict, the exit code and the
findings to be identical.

### Only identifiers are stored

A recollection is a kind, a path, a rule id, a severity, two dates and a count.
The one piece of free text is a suppression's written reason, which comes from
a source comment written by the repository's own maintainers rather than from
the change under review.

Nothing from a finding's `evidence`, `description` or `remediation` is stored,
and no model output is stored. Two reasons, either sufficient on its own:

- A diff is written by whoever opened the merge request. A file that
  accumulates it is a **stored injection** with a much longer half-life than a
  prompt — it would be replayed into every future review of that repository.
- A diff may contain a secret. A file that accumulates it is a **credential
  store nobody declared**, sitting in the checkout.

### It is a keyed store, not a second index

The roadmap said this level would "reuse Level 13's index rather than inventing
a second one". On contact with the problem that was wrong, and the reversal is
recorded rather than quietly performed.

Level 13 answers *what code is like this*: a fuzzy question over thousands of
chunks, which is what embeddings are for. This answers *what happened here
before*: an exact lookup on `(kind, path, rule)` over a few hundred entries.
Embedding them to answer a question their key already answers would be slower,
fuzzier, and impossible to explain in a report — "this rule has fired here 7
times" is a fact; "this rule is 0.83 similar to something that happened" is not.

### It forgets

Salience is occurrences, weighted by severity, halved every 30 days since the
last sighting. Below a floor, a fact is dropped; past a capacity, the least
salient go first. Exponential rather than linear decay so nothing reaches zero
at an arbitrary point — the floor forgets, not the arithmetic.

A memory with no forgetting is a file that grows until somebody deletes it, and
what they delete is the whole history rather than the stale part of it.

## Consequences

**Recall reads the pre-run memory.** A finding reported for the first time this
morning is not a recurring finding, and a memory that counted the sighting it is
currently describing would say it was.

**The store is one JSON file, written atomically, with no lock.** Two reviews
of the same repository racing will have one overwrite the other's increment.
Losing one count from a decaying score is not worth a lock file that a killed
runner can leave behind.

**A stateless CI runner has no memory unless the file travels with it.** The
default location is `.review-memory.json` inside the workspace, so the obvious
answer is to commit it — the history then reviews as any other file does, and a
team can read, question or delete it. A runner cache keyed on the default branch
works too. A fresh clone with neither produces an empty memory on every run,
which is a correct and quiet degradation rather than a failure, and it is worth
knowing about before concluding the feature does nothing.

**Anything can turn it off.** `--no-memory` produces exactly the behaviour of
every level before this one, and `--memory-path` moves the file. A team that
does not want a state file in its checkout has to be able to say so in one flag.

**Nothing here can fail a review.** An unreadable store is an empty memory; an
unwritable one is a log line. This is retrieval's rule
([ADR 0015](0015-retrieval-is-hybrid-local-and-untrusted.md)), not analysis's —
a review with no history is exactly what every review before Level 14 was.
