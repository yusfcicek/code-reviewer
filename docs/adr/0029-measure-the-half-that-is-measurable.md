# ADR 0029 — Measure the half that is measurable

**Status** Accepted · **Level** 27 · **Supersedes** nothing ·
**Depends on** [0025](0025-two-tiers-and-the-weaker-one-is-a-separate-namespace.md),
[0027](0027-a-score-that-states-its-own-uncertainty.md)

## Context

[Level 23](../roadmap/level-23/spec.md) built two tiers over the repository's
prose and declared the retrieved one unmeasurable: its answer comes from a model,
and a corpus that pinned a model's answers would measure the recording.

That is true of the **judgement**. It was taken to be true of the whole tier, and
the consequence arrived immediately: the self-review of Level 23 found the tier
returning **nothing at all** — zero documents in the top twenty for a realistic
diff — and nothing had detected it for the length of a level. A tier with no
floor and no corpus is a tier whose complete absence is indistinguishable from
its working.

Two further gaps followed from the same silence. Level 23's plan described a
relevance floor, discovered the port returned chunks without scores, and dropped
it. And the symbol index read Python only, so a document naming a symbol in
another language resolved to nothing *quietly*.

## Decision

**A tier with a model in it has two halves. Measure the one that is
deterministic.**

Whether the document section a reader says relates to a change was **retrieved**
is a fact: run the retriever, look for the section, record the rank. No model, no
recording, no author's opinion about correctness. And it is exactly the half that
failed — the model was never asked, because nothing reached it.

Five authored cases, each carrying its own documents so a reader can see the
whole haystack, and each carrying the argument for why the two relate so somebody
can disagree with it. A test asserts no case's diff contains its section's
heading: a case a token match could solve would measure the wrong thing, and this
tier exists for the sections that name nothing.

What is **not** measured is printed in the report rather than implied: whether
the model was right about a candidate it saw. That needs a human on every case,
and a corpus of "correct" answers would measure its author.

**A score belongs on the port, with an honest default.** `CodeRetriever.scored`
returns the ranking's score; the default delegates to `related` and marks every
result *unscored*, because a retriever with no notion of a score is a real thing.
A floor over unscored results reports itself as **not applied** rather than
passing everything — the silence that cost a whole tier.

The score is `NaN` rather than a sentinel number, so every comparison against it
is false and a floor cannot accidentally pass or fail it. It has to be asked
about.

**Declarations, not programs, for the other languages.** The index answers *does
this name exist*, which a regex over declaration syntax answers for Go,
JavaScript, TypeScript and Java. Python keeps its AST path and therefore keeps
its parameter names, which is why a signature mismatch is only ever claimed about
Python. The covered set is a stated constant.

**A rename is arithmetic; prose is not.** The diff knows the old name and the new
one, so substituting one for the other in a document is a substitution. It is the
only documentation edit this repository offers, and an ambiguous diff — two
removals, two additions — yields nothing rather than a guess.

## Consequences

**Recall is `1.00 [0.57, 1.00]` over five cases, floored at 0.55**, at the tier's
own per-file limit of three, with the related section first 60 % of the time. Rank
is reported because a cap of three makes it consequential.

**`DOCS` still blocks nothing, and now there is a number for why.** Measured:
the corpus supports a lower bound of 0.61 over six graded findings. A blocking
gate wants the 0.95 the analyzers are held to, and on a lower bound that needs
about **a hundred** graded findings. The severity stays where it is, and a test
records the arithmetic rather than leaving it a preference nobody wrote down.

**`DRIFT` still cannot block, and not for want of measurement.** Its producer is
an `AGENT` and [ADR 0022](0022-a-verdict-that-can-be-audited.md) makes a blocking
verdict citing one impossible to construct.

## Alternatives considered

**Grade the model's drift answers against an authored corpus.** Rejected: the
corpus would encode its author's opinion of what is stale, and the measurement
would be of the author.

**Add an LLM judge to grade the judge.** Rejected again, for
[ADR 0023](0023-the-prose-is-graded-by-code.md)'s reason.

**Leave the port alone and floor on rank instead.** Rank is available without a
score, and it is the wrong quantity: a chunk at rank one in a corpus with two
chunks is not relevant, it is alone.

**A parser per language.** The right answer for a different project. The index
answers one question and a regex answers it; pretending to more would be a
signature claim about a language nobody parsed.
