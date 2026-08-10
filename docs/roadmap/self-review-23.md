# Self-review of Level 23

**Method** the one the last two rounds established: not reading the claims, but
**enumerating the inputs a user actually produces** and measuring which ones the
code agrees with. Every number below was taken by running the shipped code
against this repository.

| # | Severity | What |
|---|---|---|
| S-01 | 🔴 | The retrieved tier returns nothing at all — 0 documents in the top 20 |
| S-02 | 🔴 | The shape test cancels the diff's proof; 17 % of functions are invisible |
| S-03 | 🟠 | A deleted file removes nothing, so the most obvious stale reference is missed |
| S-04 | 🟠 | `Raises:` on an abstract method is reported — 1 of 3 findings on this repo |
| S-05 | 🟡 | `corpus.py` has the path defect this level found and fixed in its own copy |
| S-06 | 🟡 | The documentation block is unbounded and sits above the reviews |

---

## S-01 — the tier the level was asked for does not fire

Tier B exists because the user's requirement was explicit: *"her türlü ilişki
yakalanmalı, derinlemesine taranmalı"* — catch every kind of relationship, scan
deeply. It is the half no token match reaches.

Measured, with the real corpus and a realistic diff:

| retrieval limit | documents returned |
|---|---|
| 3 (the shipped default) | **0 of 3** |
| 5 | 0 of 5 |
| 10 | 0 of 10 |
| 20 | 0 of 20 |

The cause is an ordering mistake, not a tuning one. Documents and code share one
index — 4 205 code chunks against 1 129 document chunks — and the **limit is
applied by the retriever, before the document filter runs in the service.** Code
wins every ranking, so the three chunks that come back are always code and are
always discarded. The tier produces no candidate, ever, and every test passed
because each one hands the service a document chunk directly.

The level's non-goals said *"a second index would be a second thing to keep
correct"*, and that reading was too literal. One retrieval *implementation* is
the property worth keeping; two *instances* of it cost nothing to keep correct.
Documents get their own.

The tests deserve the blame here. All eleven of them are about bounds — what the
tier never asks about, how many it asks about, what happens when the model fails
— and none of them exercised the tier against a corpus that also contained code.
A fake retriever that returns what it was handed cannot fail this way.

## S-02 — two safeguards, and the blunt one cancels the sharp one

`_symbol_shaped` refuses a bare lowercase word with no underscore, so `async`
and `false` in a README are not read as symbols. That was the right rule when
every backtick was resolved against the tree.

It is the wrong rule now. Since the scope rework, `DEAD_REFERENCE` fires only
for a name **the diff removed** — which is direct evidence that the name was
this repository's. The shape test then throws that evidence away:

```
diff removes:  def drain(worker):
document says: Call `drain` on exit.
reported:      nothing
```

The scale, measured against the real index: **113 of 648 indexed bare functions
(17 %) are invisible to the shape test** — `add`, `analyze`, `bind`, `cases`,
`claim`, `covers`, `consolidate`, `compose`. Every one of them is a name a
document would write in prose, and every one is unreportable however plainly the
change deleted it.

The fix is not to weaken the shape test. It is to notice that it answers a
question the scope has already answered, and to let a proved-removed name
through regardless of its shape.

## S-03 — deleting the file is the case it misses

`ReviewService` filters `is_deleted` changes out before anything sees them
(reasonably: there is nothing left to review). A deletion also carries no diff
lines to subtract. So the single most obvious way to make a document stale —
**delete the module it documents** — leaves `scope.removed` empty and produces
nothing. Confirmed against a fixture: zero findings.

## S-04 — an abstract method documents a contract, not a body

Run over this repository, the docstring rule produces three findings. One is:

```
code_reviewer/application/jobs.py:44  submit
  documents raising (QueueFull), the body raises nothing
```

`submit` is an `@abstractmethod` whose body is a docstring. Documenting
`Raises: QueueFull` there is *correct* — it is the contract every implementer
must honour, and it is the only place to state it. The rule is right that the
body raises nothing and wrong that this is a defect.

One false positive in three findings is a 33 % rate on the only real corpus
available, and it lands on the file where the project states its ports.

The other two are true positives this repository should fix:
`render_review_comment` and `analyze_performance` each grew a parameter that
their `Args:` sections never learned about.

## S-05 — the defect this level found in Level 13's code and fixed only in its own

Building the symbol index from a relative root silently produced an empty index,
because `Workspace` resolves the paths it is given against its root. Level 23
found that in its own dry run and fixed it. `corpus.py` — where the pattern was
copied *from* — still has it:

```
collect_chunks('code_reviewer')    -> 0 chunks
collect_chunks('./code_reviewer')  -> 0 chunks
collect_chunks('.')                -> 4205 chunks
collect_chunks('<absolute>')       -> 1172 chunks
```

Retrieval has therefore been silently dead since Level 13 for any relative root
other than `.`. The default happens to be `.`, which is why nobody noticed —
and why the log line reads `Indexed 0 chunk(s)` rather than an error.

Finding a bug in your own copy of a pattern and not looking at the original is
the mistake worth recording here.

## S-06 — the block that eats the reviews

`_documentation_lines` lists every finding, with no bound, and the block sits
**above** the per-file sections so that truncation keeps the verdict. A change
that removes a symbol documented in forty places therefore spends the comment
budget on a list of forty locations and truncates the reviews that were the
point of the run.

Level 5 solved this shape once (G-19) and Level 22 respected it. This block did
not.

---

## What this round says about the tests

Nine of Level 23's eleven Tier B tests are about bounds, and they are good tests
of bounds. Not one of them put a document and a piece of code in the same index,
which is the only configuration the tier ever runs in.

The pattern is the same one the last self-review named: **a test written against
a fake that returns what it was handed confirms the author's mental model of the
collaborator, not the collaborator.** The previous round found it in prose
checks; this round finds it in a retrieval pipeline. The move that catches it is
the same — build the real thing, ask it the real question, count the answers.
