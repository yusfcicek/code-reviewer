# ADR 0030 — A floor is earned

**Status** Accepted · **Level** 28 · **Supersedes** nothing ·
**Depends on** [0027](0027-a-score-that-states-its-own-uncertainty.md)

## Context

Level 12 wrote the rule this project has repeated ever since: *a floor is earned
by the level that measured it.* Level 25 gave it teeth by moving every floor to
the lower bound of an interval, which made the corpora the binding constraint and
forced three floors **down** to what their samples carried — 0.70, 0.60, 0.35.

Sixteen levels of saying it, and not one of them had ever moved a floor in the
other direction.

## Decision

**Write the cases.** Sixteen graded observations support 0.80, thirty-five
support 0.90, seventy-three support 0.95; the target is chosen from that table
rather than from ambition.

Three rules govern which cases get written, and each one exists because a
self-review found somebody about to break it:

- **The coverage reports choose them.** Levels 25 and 26 built per-check and
  per-rule coverage precisely so "what is missing" stops being a matter of
  taste. This is the first level to spend them: eight of thirty-four emittable
  rules had a case, and three of the six added cover rules Level 26 had written a
  recipe or a written refusal for **without anything measuring the rule
  underneath.**
- **A defect a case finds is fixed, not annotated.** The alternative is the one
  move that would make every number in this repository worthless.
- **The quiet half is not diluted.** Growing a corpus by adding only positives is
  how a precision figure improves without anything improving.

## Consequences

| corpus | before | after | floor |
|---|---|---|---|
| analyzers | 10 findings, 0.72 | **20**, 0.84 | 0.70 → **0.80** |
| documentation | 6 findings, 0.61 | **18**, 0.82 | 0.60 → **0.80** |
| drift retrieval | 5 cases, 1.00 | **16**, 0.69 | 0.35 → **0.40** |

**Three real defects, found by cases written to look for nothing in particular.**
`QUALITY.ERROR_HANDLING` demanded a `finally` beside a `with`, which is the
construct that makes one unnecessary. `PERFORMANCE.RECURSIVE_RISK` called
`def read` recursive because its body calls `handle.read()`. And the
documentation scope compared a method's **bare** name from a diff against a
document's **qualified** one, so no method's documented signature had ever been
checked.

**One corpus stopped scoring perfectly, and that is the good news.** Retrieval is
a ranking, and eleven of sixteen over ten sections with a limit of three is a
measurement. The other three ace their corpora because the rules they grade are
deterministic; a ranking that scored 1.00 would mean the corpus was too easy —
which is exactly what self-review 27 found.

**`DOCS` still does not block, and the no is shorter.** Eighteen findings support
0.82; a blocking gate wants 0.95, which needs seventy-three. That is one more
level of authoring rather than an open question.

## Alternatives considered

**Go to 0.95 now.** Seventy-three graded observations per corpus, written in one
level, would be written to be counted. The last four self-reviews each found a
version of that.

**Lower the target to what already passes.** The definition of the move this ADR
exists to make impossible.

**Improve the retriever so its corpus scores 1.00 too.** Tempting and wrong here:
a level that changes a ranking should be the level that measures the change, and
this one is measuring. The five misses are named so a later level has somewhere
to start.
