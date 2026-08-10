# ADR 0028 — A suggestion is a set of edits

**Status** Accepted · **Level** 26 · **Supersedes** nothing ·
**Depends on** [0024](0024-propose-never-apply.md)

## Context

[Level 22](../roadmap/level-22/spec.md) shipped three deterministic recipes and
named two limits in its own non-goals: *"a rule with no recipe produces the
advice it always did"*, and *"one finding, one file, one contiguous range"*.

Measured before this level: the analyzers can emit **39 rule ids** and three had
a recipe. So 8 % of findings got a button and the rest got a paragraph telling
somebody what to type — including rules where the edit is exactly as mechanical
as the three that shipped.

The range rule cost the other half, and it cost it by accident. A fix that needs
**two edits in one file** — the import at the top and the call in the middle —
was not expressible at all. `hashlib.md5` → `sha256` happened to need no import.
`random` → `secrets` does, and so does most of what remained.

## Decision

**A suggestion carries a set of edits rather than a range.**

Every guarantee that mattered was about *validation*, and validating a set is
the same operation as validating one: apply them all in memory, re-parse, and
discard the whole suggestion if any part does not fit. Three properties are
enforced rather than hoped:

- **Edits may not overlap.** Two claiming one line produce a result nobody can
  predict, and predicting it is the entire value of a one-click button. Refused
  at construction rather than resolved by ordering.
- **Edits apply bottom-up.** Applying from the top invalidates every later line
  number — arithmetic that is wrong once and then wrong everywhere, so it lives
  in one function with its own tests.
- **The line bound counts the whole set.** Otherwise five edits of twelve lines
  is a sixty-line button.

**One note per edit, not one note per suggestion.** This level's own plan said
two blocks in one note, and the platform does not work that way: a
`suggestion:-a+b` block replaces lines *around the note's own line* and must
include it, so two disjoint edits cannot share a note. Each edit is posted on its
own line and names its position in the whole — *part 1 of 2* — because a reader
who applies one must be able to see there is another.

**Recipe coverage is measured, not asserted.** *"We ship three recipes"* was a
number somebody had to count by hand. Every emittable rule now either maps to a
recipe or carries a recorded reason, and a rule with neither is a red test — the
shape [ADR 0022](0022-a-verdict-that-can-be-audited.md) used for attribution and
Level 24 used for controls.

## Consequences

**Six recipes of thirty-nine rules, 15 %, and the number is printed.** The
thirty-three without one each say why. Most are declined because the fix is a
*decision* — splitting a class, choosing an escaping, naming a confinement root
— and a recipe that guesses a decision produces a button that breaks a build.

**An earlier refusal is honoured rather than reversed in passing.**
`SAST.DEBUG_CODE` is the most obviously mechanical rule left and its fix is a
deletion, which Level 22 refused: *"deleting code is a change worth writing by
hand"*. Reversing that needs an argument this level does not have, so the rule is
declined on the record.

**Multi-file stays out, now with a reason.** A suggestion is applied from one
diff note on one file, so a cross-file suggestion is not something the platform
can honour. Level 22 left it out without saying why; that is the why.

**Everything Level 22 guaranteed still holds.** Nothing is applied, no model
authors an edit, a recipe that does not fit returns nothing, and the tests that
pinned the single-range behaviour were not rewritten — they are the regression
suite for it, through `Suggestion.single`.

## Alternatives considered

**Widen one range to cover both edits.** For an import and a call that is the
whole file. Rejected immediately.

**A patch format of our own.** Rejected again, for
[ADR 0024](0024-propose-never-apply.md)'s reason: a format to generate and then
parse back is two directions to be wrong in, and the platform wants lines.

**Keep one note and put both blocks in it.** What the plan assumed. The platform
refuses it, and finding that out by reading the rules rather than by shipping it
is the only good outcome available.

**Ship a recipe for every rule.** It would double the count and halve the trust:
a button that breaks a build costs every future suggestion its credibility, and
the recipes that would have to guess are the ones most likely to.
