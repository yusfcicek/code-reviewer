# Level 26 — Plan

Branch: `feature/level-26-more-fixes`, off `development`, merged with `--no-ff`.

The format change lands before any recipe uses it, so the recipes are written
against the shape they need rather than around the shape that existed.

## Step 1 — A suggestion is a set of edits

*Tests* — `tests/unit/domain/test_suggestion.py` (extended)

- AC-1: two edits, both applied.
- AC-2: overlapping edits refused at construction — not resolved by ordering,
  because two edits claiming one line produce a result nobody can predict.
- AC-3: applied bottom-up, asserted by a case where a top-down application
  would corrupt the second edit. This is the arithmetic that is wrong once and
  then wrong everywhere.
- AC-5: the line bound counts every edit together; five edits of twelve lines
  is not a valid twelve-line suggestion.
- A single-edit suggestion behaves exactly as it did — the existing tests are
  the regression suite for that, and they are not rewritten.
- An empty edit set is refused.

*Change* — `code_reviewer/domain/remediation.py`.

## Step 2 — Inserting an import where imports go

*Tests* — `tests/unit/domain/test_import_insertion.py`

- AC-8: after the last import; after a module docstring when there are none;
  at the top when there is neither.
- AC-7: not inserted when already present, in any of its spellings
  (`import x`, `from x import y`, `import x as z`).
- A file that does not parse yields no insertion rather than a guess.
- The insertion is a `SuggestionEdit`, so it composes with whatever the recipe
  is already doing.

*Change* — `code_reviewer/domain/fix_recipes.py`.

## Step 3 — The new recipes

*Tests* — `tests/unit/domain/test_fix_recipes.py` (extended)

Each new recipe gets the same three tests Level 22 gave the first three: it
fires on the shape it is for, it declines a line its pattern does not match, and
it declines code already correct.

- AC-6: `SAST.INSECURE_RANDOM` — `random.random()` → `secrets.SystemRandom()`,
  with `import secrets` added. The two-part edit the format change exists for.
- AC-9: `SAST.DEBUG_CODE` — remove the line. The only recipe that deletes, and
  it declines anything on the line beside the debug call.
- AC-10: `SAST.INSECURE_HTTP` — `http://` → `https://` in a literal only.
  Declines a URL built from a variable, because upgrading a scheme it cannot see
  is a guess.
- AC-11: `QUALITY.ERROR_HANDLING` — bare `except:` → `except Exception:`.
  Declines `except:` followed by a bare `raise`, which is a deliberate re-raise.
- AC-12: `SAST.INSECURE_FILE_OPERATION` — adds the missing mode where the call
  has one positional argument and no mode. Declines anything more complex.

*Change* — `code_reviewer/domain/fix_recipes.py`.

## Step 4 — Coverage, measured rather than asserted

*Tests* — `tests/unit/test_recipe_coverage.py`

- AC-15: the number of emittable rule ids with a recipe, and the names of those
  without.
- AC-16: a rule declined on purpose carries its reason. `SOLID_SRP` is declined
  because the fix is a design decision, and that sentence lives beside the rule
  rather than in somebody's memory.
- Every rule the suite can emit is either mapped to a recipe or has a recorded
  reason — the same completeness shape Level 20 used for attribution and
  Level 24 for controls. A new rule with neither is a red test.

*Change* — `code_reviewer/domain/fix_recipes.py`, a coverage renderer.

## Step 5 — Validated together, discarded together

*Tests* — `tests/unit/application/test_suggestion_service.py` (extended)

- AC-4: a suggestion whose second edit does not fit is discarded whole, never
  published half-applied.
- The result is re-parsed once, after every edit, rather than after each.
- AC-17: an agent-produced finding still yields nothing.
- Nothing raises: a recipe that throws costs its own suggestion.

*Change* — `code_reviewer/application/remediation_service.py`.

## Step 6 — Rendered as one suggestion block per edit

*Tests* — `tests/unit/application/test_report.py` (extended),
`tests/unit/infrastructure/test_gitlab_forge.py` (extended)

- GitLab's suggestion block covers one contiguous range, so a two-edit
  suggestion is two blocks in one note. A reader applies both or neither, which
  is the honest rendering of "these go together".
- The marker still keys on the location, so a second run edits rather than adds.

*Change* — `render_suggestion`, the forge adapter.

## Step 7 — Say it once, truthfully

- ADR 0028: why a suggestion became a set, and why multi-file stayed out with
  the platform reason recorded.
- `capability-sources.md`: C-30, C-31, sourced from Level 22's non-goals.
- README, CHANGELOG, version 2.20.0, and the recipe count corrected wherever it
  is quoted.

The dogfooding gate runs this level against itself; whatever it finds is part of
the level.
