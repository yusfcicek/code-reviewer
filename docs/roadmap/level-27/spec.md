# Level 27 — Measuring the half that was never measured

## Problem statement

[Level 23](../level-23/spec.md) built two tiers over the repository's prose and
left four things, three of them in its own non-goals and one in its plan:

- **`DOCS` blocks nothing.** The rules were unmeasured, and this project's rule
  since Level 12 is that a floor is earned by the level that measured it.
- **`DRIFT` is not measured and there is no method.** Its answer comes from a
  model, and a corpus that pinned a model's answers would measure the recording.
- **Tier B has no relevance floor.** `CodeRetriever.related` returns chunks
  without scores, so the floor the plan described could not be built without a
  port change, and it was dropped.
- **The symbol index is Python only**, so a document naming a symbol in any
  other language resolves to nothing and is silently out of scope.

The first three compound. The self-review of Level 23 found that Tier B returned
**nothing at all** — zero documents in the top twenty — and nothing detected it
for the length of a level, because there was no measurement to fail. A tier with
no floor and no corpus is a tier whose complete absence is indistinguishable from
its working.

Capabilities addressed: **C-32** (a retrieval tier measured without grading a
model), **C-33** (relevance as a number a floor can be applied to), **C-34**
(documentation resolution beyond one language).

## Goals

1. **Retrieval is scored**, through the port, so a relevance floor is
   expressible — and a retriever that cannot score says so rather than being
   silently unfloored.
2. **Tier B is measured** by the half that is deterministic: given a change and
   a corpus, does the section a human says is related come back? That is a
   recall measurement over authored cases and needs no model.
3. **The symbol index reads more than Python**, enough that a document naming a
   symbol in another language resolves rather than being ignored.
4. **`DOCS` blocking is decided by the measurement**, not by preference — and if
   the corpus does not support it, the level says so and says what would.

## Non-goals

- **Grading the model's drift answers.** Unchanged from Level 23 and for the
  same reason. What is measured is *retrieval*: whether the candidate reached
  the model at all. Whether the model was right about it is not gradeable
  without a human on every case, and inventing a corpus of "correct" answers
  would be measuring the corpus author.
- **A full parser for every language.** The index reads declarations, not
  programs: what a document names is a function, a class, a constant. A regex
  over declaration syntax is enough for that and is honest about being enough
  for nothing else.
- **Blocking on `DRIFT`.** Never, and not for want of measurement: its producer
  is an `AGENT` and [ADR 0022](../../adr/0022-a-verdict-that-can-be-audited.md)
  makes a blocking verdict citing one impossible to construct.
- **Suggesting documentation prose.** A model-authored sentence in a README is
  a claim nobody reviewed, in the position Level 23 exists to distrust. What
  ships instead is deterministic: where the diff renamed a symbol, the old and
  new names are both known, and the edit is arithmetic.
- **A retrieval quality benchmark.** One corpus, one number, floored. Not an
  information-retrieval evaluation framework.

## Behavioural contracts

### C-1 — Retrieval can be scored, or says it cannot
The port gains a scored query. A retriever that has no notion of a score returns
its results marked unscored, and a floor applied to unscored results is reported
as *not applied* rather than silently passing everything.

### C-2 — A candidate below the floor never reaches the model
And the number of candidates the floor removed is reported, on the rule Level 23
set: a truncation nobody can see reads as coverage.

### C-3 — Retrieval recall is measured over authored cases
Each case names a change and the document section a reader says is related.
The measurement is whether that section is retrieved, at what rank, and nothing
about what a model then said.

### C-4 — The retrieval corpus states what it is
Authored, small, and a measurement of *this* corpus. The same sentence the
narration corpus carries, for the same reason.

### C-5 — The floor is on the lower bound
Level 25's rule, applied to this measurement too.

### C-6 — The symbol index resolves more than Python
A declaration in another language the index reads produces a name a document can
resolve against. A language it does not read produces nothing, and the coverage
is stated rather than implied.

### C-7 — A rename produces a documentation suggestion
Where the diff removed one name and added another in the same file, and a
document names the old one, the edit is the substitution. Deterministic, one
line, and declined when the rename is ambiguous.

### C-8 — Whether `DOCS` blocks is a conclusion, not a preference
The level measures and then states what the measurement supports. If it does not
support blocking, that is the finding and the corpus size that would is named.

### C-9 — Nothing here changes what the model is asked
The prompt is untouched. This level measures the machinery around it.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | The port exposes a scored query and a default that marks results unscored | Port test |
| AC-2 | The hybrid retriever returns real fused scores | Retriever test |
| AC-3 | A candidate below the floor is dropped before the model is asked | Service test |
| AC-4 | The number the floor dropped is reported | Service test |
| AC-5 | A floor over unscored results is reported as not applied | Service test |
| AC-6 | The retrieval corpus loads and every case names an existing document | Dataset test |
| AC-7 | Recall at the shipped limit is measured and floored on the lower bound | Baseline test |
| AC-8 | The rank of each retrieved section is reported, not just whether it appeared | Report test |
| AC-9 | A case whose section is not retrieved is named | Report test |
| AC-10 | The index resolves a declaration in a second language | Index test |
| AC-11 | A language the index does not read contributes nothing and is not claimed | Index test |
| AC-12 | A rename yields a documentation suggestion substituting the name | Recipe test |
| AC-13 | An ambiguous rename yields nothing | Recipe test |
| AC-14 | A documentation suggestion is never authored by a model | Architecture test |
| AC-15 | The level states what the measurement supports about blocking | Spec + report |
| AC-16 | The six checks stay green, coverage holds, every eval floor holds | `ruff`, `mypy`, `pytest --cov`, audit, eval ×4 |

## Decisions taken

**D-1 — Measure retrieval, not judgement.** The tier has two halves and only one
is gradeable without a human. Measuring the gradeable half is worth more than
measuring nothing, and it is exactly the half that failed silently in Level 23:
the model was never asked, because nothing reached it.

**D-2 — A score is on the port, with an honest default.** A retriever that
cannot score is a real thing — a keyword-only adapter, a stub in a test — and
the floor must report itself as inapplicable rather than passing everything.
Silence there is how Level 23 lost a whole tier.

**D-3 — Declarations, not programs.** The index answers *does this name exist*.
Regexes over declaration syntax answer that for the common languages, and a
language nobody wrote a pattern for contributes nothing and is listed as not
covered. The alternative is a parser per language, which is a different project.

**D-4 — A rename is arithmetic; prose is not.** The diff knows the old name and
the new one. Substituting one for the other in a document is a substitution, and
it is the only documentation edit this repository will offer.

**D-5 — The blocking question is answered by the number.** Level 12's rule, and
this level applies it to itself: whatever the corpus supports is what is
claimed, and if that is "still nothing", the report says which corpus would
change the answer.
