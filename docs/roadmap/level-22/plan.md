# Level 22 — Plan

Branch: `feature/level-22-remediation`, off `development`, merged with
`--no-ff`.

## Step 1 — What a suggestion is

*Tests* — `tests/unit/domain/test_suggestion.py`

- A `Suggestion` carries the rule, the file, the line range, the replacement
  lines and the recipe that produced it.
- A range whose end is before its start is refused; so is an empty replacement
  with an empty range (a suggestion that changes nothing).
- AC-5: `applied_to(source)` returns the file with the range replaced, or
  `None` when the range is not in the file.
- AC-9: a suggestion over `MAX_SUGGESTION_LINES` is refused at construction.

*Change* — `code_reviewer/domain/remediation.py`.

## Step 2 — The recipes

*Tests* — `tests/unit/infrastructure/test_fix_recipes.py`

- AC-1, AC-2, AC-3: the three transformations, each on the line the finding
  names.
- AC-4: the secret recipe declines without `import os` in the file.
- AC-5: every recipe declines when its pattern is not on the named line — a
  finding at the wrong line must not produce an edit somewhere else.
- A recipe declines a line it would not change (an idempotent edit is noise).
- The registry maps a rule id to at most one recipe, and an unknown rule maps
  to none.

*Change* — `code_reviewer/infrastructure/remediation/recipes.py`.

## Step 3 — Proposing, and refusing

*Tests* — `tests/unit/application/test_suggestion_service.py`

- AC-6: a replacement that leaves the file unparseable is discarded, and the
  discard is logged.
- AC-7: a line range past the end of the file is discarded.
- AC-8: an agent-produced finding never yields one.
- Two findings on one line yield at most one suggestion: overlapping edits are
  not applicable and the reader cannot tell which one they clicked.
- Nothing raises. A recipe that throws costs its own suggestion and nothing
  else.

*Change* — `code_reviewer/application/remediation_service.py`.

## Step 4 — Saying it where it can be applied

*Tests* — `tests/unit/application/test_report.py` (extended)

- AC-10: the block is ` ```suggestion:-0+0 ` anchored on the finding's line,
  with the replacement lines inside it.
- AC-11: with no suggestions the comment is byte-identical to the one before
  this level.
- A file's section carries its own suggestions and no other file's.

*Change* — `render_review_comment` and the section renderer.

## Step 5 — Wiring and the record

*Tests* — `tests/unit/application/test_review_recording.py` (extended),
`tests/unit/test_main_wiring.py` (extended)

- AC-12: the record carries rule, location and recipe; a test asserts the
  replacement text is absent from the serialised record.
- AC-13: the exit code with and without suggestions is the same.
- `--no-suggestions` turns the whole thing off, and the comment is then the
  one from Level 21.

*Change* — `ReviewService`, `DecisionRecord`, `cli.py`, `__main__.py`.

## Step 6 — Proving it cannot apply

*Tests* — `tests/unit/test_architecture.py` (extended)

- AC-14: no module under `remediation` imports `subprocess`, `os.remove`,
  `open(...,'w')`, `Path.write_text` or `git`.
- The forge port gains no write method beyond `publish_comment`.

## Step 7 — Documentation

- `docs/adr/0024-propose-never-apply.md`: D-1, D-2, D-3.
- `README.md`, `docs/ARCHITECTURE.md`, `SECURITY.md` (a suggestion is a change
  a human applies, and what that means for review), `CHANGELOG.md`,
  `capability-sources.md` (C-22), the roadmap table.

## Order and rationale

The value object first, because "what is a suggestion" decides what a recipe
has to return. The recipes second, because they are the level's subject matter.
The service third — it is where the refusals live, and refusals are only
testable once there is something to refuse. Rendering fourth: a suggestion
nobody can apply is a comment.
