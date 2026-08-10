# Level 26 — More of the fixes that are arithmetic

## Problem statement

[Level 22](../level-22/spec.md) shipped three deterministic recipes and named
its own limits:

> **Fixing everything.** Three recipes ship. A rule with no recipe produces the
> advice it always did.

> **Multi-file or multi-hunk changes.** One finding, one file, one contiguous
> range.

The first was a scoping decision and the second a design one, and both are worth
revisiting now that the machinery exists and has been used.

Measured today: the analyzers can emit **32 rule ids** across four namespaces.
Three of them have a recipe. So the observable behaviour of the level is that
9 % of findings get a button and 91 % get a paragraph telling somebody what to
type — including several where the edit is exactly as mechanical as the three
that shipped.

The second limit costs a different thing. A finding whose fix needs **two edits
in one file** — the import at the top and the call in the middle — is not
suggestible at all under a one-contiguous-range rule, and that shape covers most
of what remains. `hashlib.md5` → `sha256` happened to need no import. `random`
→ `secrets` does.

Concretely:

- **A recipe exists for the three easiest rules and nothing else**, and the
  easiest three were chosen because they were easy rather than because they were
  common.
- **A fix that touches two places in a file cannot be offered**, so the rules
  whose fixes are two-part are excluded by the format rather than by judgement.
- **Nothing measures recipe coverage.** How many emittable rules have a recipe
  is not reported anywhere, so "we ship three" is a fact somebody has to count
  by hand — the same gap Level 25 closed for check coverage.

Capabilities addressed: **C-30** (a suggestion that can touch more than one
place), **C-31** (recipes for the rules that are mechanical, measured rather
than asserted). Both come from Level 22's own non-goals.

## Goals

1. A suggestion may carry **more than one edit in one file**, each a contiguous
   range, validated together.
2. **More recipes**, chosen by what is mechanical rather than by what is quick,
   with the reasoning for each refusal written where the recipe is.
3. **Recipe coverage is measured and reported** — how many emittable rules have
   one, which do not, and why the missing ones are missing.
4. Every existing guarantee survives unchanged: nothing is applied, nothing is
   authored by a model, a recipe that does not fit returns nothing.

## Non-goals

- **Multi-file suggestions.** Still out, and now for a stated reason rather than
  an unexamined one: GitLab applies a suggestion within one diff note on one
  file, so a two-file suggestion cannot be one click. A change that spans files
  is a merge request, and offering it as a button would be offering something
  the platform will not honour.
- **Deleting code by button.** Level 22 refused an empty replacement — *"deleting
  code is a change worth writing by hand"* — and this level honours that rather
  than quietly reversing it. `SAST.DEBUG_CODE` would be the obvious candidate
  and is therefore declined *on the record*, in the coverage report, with that
  reason beside it.
- **A recipe for every rule.** Most of the remaining 29 are not mechanical:
  `QUALITY.SOLID_SRP` and `PERFORMANCE.N_PLUS_ONE` need a design decision, and a
  recipe that guesses one produces a button that breaks a build. What ships is
  the set where the edit follows from the finding, and the report says which
  rules were considered and declined.
- **Model-authored patches.** Unchanged from
  [ADR 0024](../../adr/0024-propose-never-apply.md). The producer must be
  deterministic.
- **Applying anything.** Unchanged, and still asserted by a test that parses the
  remediation modules.
- **Semantic equivalence proofs.** Unchanged. `random` → `secrets` changes
  behaviour on purpose, and that belongs in the remediation text.
- **Rewriting the whole file.** An edit that replaces more than
  `MAX_SUGGESTION_LINES` in total is a refactor, and a refactor arriving as a
  button is how a reviewer stops reading.

## Behavioural contracts

### C-1 — A suggestion is a set of edits, and the set is validated together
Each edit names a contiguous range. The whole set is applied in memory and the
result re-parsed; if any part does not fit, **the whole suggestion is discarded**
rather than published half-applied.

### C-2 — Edits within one suggestion may not overlap
Two edits claiming the same line produce a result nobody can predict. Overlapping
edits are refused at construction, not resolved by ordering.

### C-3 — Edits are applied from the bottom up
Applying from the top invalidates every later line number. This is arithmetic
and it is a place to be wrong once, so it is done in one place and tested.

### C-4 — One file
The suggestion names one path. A change spanning files is not offered.

### C-5 — An added import goes where imports go
A recipe that needs an import inserts it after the last existing import, or at
the top of the file after any module docstring. It never inserts one that is
already there.

### C-6 — A recipe still returns nothing when it does not fit
Unchanged from Level 22, and now over a larger set: absent pattern, wrong line,
already-correct code, a shape the recipe cannot read.

### C-7 — Coverage is reported
How many emittable rule ids have a recipe, which do not, and — for the ones
deliberately declined — the reason. Named rather than counted by hand.

### C-8 — The bound is on the whole suggestion
`MAX_SUGGESTION_LINES` applies to the total replaced across every edit, not per
edit. Otherwise five edits of twelve lines is a sixty-line button.

### C-9 — The verdict is untouched
A finding with a suggestion blocks exactly as it did without one.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A suggestion carrying two edits applies both | Domain test |
| AC-2 | Overlapping edits are refused at construction | Domain test |
| AC-3 | Edits apply bottom-up, so an earlier edit does not move a later one | Domain test |
| AC-4 | A suggestion whose second edit does not fit is discarded whole | Service test |
| AC-5 | The line bound counts every edit together | Domain test |
| AC-6 | `SAST.INSECURE_RANDOM` becomes `secrets`, with the import added | Recipe test |
| AC-7 | The import is not added when it is already present | Recipe test |
| AC-8 | The import lands after the last import, not before a docstring | Recipe test |
| AC-10 | `SAST.INSECURE_HTTP` becomes `https` where the scheme is a literal | Recipe test |
| AC-11 | `QUALITY.ERROR_HANDLING` turns a bare `except:` into `except Exception:` | Recipe test |
| AC-12 | `SAST.INSECURE_FILE_OPERATION` adds the missing mode where it is unambiguous | Recipe test |
| AC-13 | Each new recipe declines a line its pattern does not match | Recipe test |
| AC-14 | Each new recipe declines code that is already correct | Recipe test |
| AC-15 | Coverage reports the number with a recipe and names those without | Coverage test |
| AC-16 | A rule declined on purpose carries its reason in the coverage report | Coverage test |
| AC-17 | An agent-produced finding still never yields a suggestion | Service test |
| AC-18 | Nothing in the remediation modules writes | Architecture test |
| AC-19 | The six checks stay green, coverage holds, all three eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval ×3 |

## Decisions taken

**D-1 — A suggestion becomes a set of edits, not a range.** The one-range rule
excluded a whole shape of fix — the two-part edit — and it excluded it by
accident of format rather than by judgement. Every guarantee that mattered was
about *validation*, and validating a set is the same operation as validating one.

**D-2 — Bottom-up, in one place.** Applying edits top-down invalidates later
line numbers. It is the kind of arithmetic that is wrong once and then wrong
everywhere, so it lives in one function with its own tests.

**D-3 — Recipes chosen by mechanism, not by ease.** The bar is: does the fix
follow from the finding without a decision? `random` → `secrets` does.
`SOLID_SRP` does not, and the coverage report says so rather than leaving a
reader to assume the rule was forgotten.

**D-4 — Coverage is reported because Level 25 taught that.** "We ship three
recipes" was a number nobody could check without counting. The same argument
that put check coverage in the narration report puts recipe coverage here.

**D-5 — An earlier refusal is honoured rather than reversed in passing.**
`DEBUG_CODE` is the most obviously mechanical rule left and its fix is a
deletion, which Level 22 refused for a stated reason. Reversing that reason
would need an argument this level does not have, so the rule is declined and the
coverage report carries the refusal — which is what the report is for.

**D-6 — Multi-file stays out, with the platform reason recorded.** Level 22 left
it out without saying why. The why is that a suggestion is applied from one diff
note on one file, so a cross-file suggestion is not a thing the platform can
honour — a better reason than "we did not get to it".
