# Level 10 — Implementation Plan

Branch: `feature/level-10-operability` (off `development`)

Grouped by the file each change lands in, so a step is one module and its
tests rather than a thread running through four.

## Step 1 — The marker and the size bound (G-12, G-19, C-1, C-3)

Both live in `application/report.py`, which is why they move together.

Test-first: `tests/unit/application/test_report.py` gains

| Test | Asserts |
|---|---|
| marker present | The body starts with the marker |
| marker invisible | It is an HTML comment, so a reader never sees it |
| marker stable | Two renders of different content carry the same marker |
| under the limit | A short body is returned unchanged |
| over the limit | The result is at most the limit |
| head survives | The verdict and blocking reasons are still present |
| notice | The tail is replaced by a line saying how much was dropped |
| boundary | A body exactly at the limit is untouched |

`REVIEW_COMMENT_MARKER` is a module constant. `MAX_COMMENT_CHARS` reads
`REVIEW_MAX_COMMENT_CHARS` with a default of 900 000 — under GitLab's
1 000 000, with room for the notice.

## Step 2 — Find-or-create in the forge (G-12, C-1, C-2)

Test-first: `tests/unit/infrastructure/test_gitlab_forge.py` gains a fake
client whose notes are inspectable.

| Test | Asserts |
|---|---|
| first publish | Creates a note |
| second publish | Edits the same note; no second note exists |
| foreign note | A note without the marker is left alone |
| human reply | A reply posted between runs survives |
| edit fails | Falls back to creating, rather than losing the review |
| list fails | Falls back to creating |

The port signature does not change: the marker travels in the body, so
`publish_comment(reference, body)` is still the whole contract (decision D-1).

## Step 3 — Typed errors and the exit-code taxonomy (G-13, C-4, C-5)

New module `code_reviewer/domain/errors.py`? **No** — these are operational
categories, not domain concepts, so `code_reviewer/errors.py` at package root,
importable from any layer without inverting the dependency rule.

Test-first: `tests/unit/test_exit_codes.py`

| Test | Asserts |
|---|---|
| clean | A non-blocking outcome exits `0` |
| blocked | A blocking outcome exits `1` |
| missing credentials | `2` |
| unloadable policy | `2` |
| forge failure | `3` |
| unexpected exception | `3` |
| the codes are named | `EXIT_OK`, `EXIT_BLOCKED`, `EXIT_CONFIG_ERROR`, `EXIT_RUNTIME_ERROR` exist and are distinct |

Then: the hierarchy, `MissingCredentialsError` re-parented onto
`ConfigurationError`, and `main()` mapping category to code.

## Step 4 — The operational flags (G-13, C-6, C-7, C-8)

Test-first: `tests/unit/test_cli.py` gains the parsing cases, and
`tests/unit/test_main_wiring.py` (new) gains the behavioural ones:

- `--dry-run` prints the report and calls no publish;
- `--dry-run` still returns the blocking exit code;
- `--no-llm` builds no provider and still reaches a verdict;
- `--repo-root` becomes the workspace root;
- `--metrics-path` is where metrics are written;
- `--log-level` reaches `configure_logging`.

`--no-llm` needs a `Reviewer` that produces no narrative. A null object rather
than a `None` check at the call site: `ReviewService` should not learn that a
reviewer is optional.

## Step 5 — Documentation

- ADR `0012-one-comment-per-merge-request.md`: the marker, why it is in the
  body, and why truncation keeps the head.
- `README.md`: the flag table, the exit-code table, and the plain statement
  that `--no-llm` reaches the same verdict.
- `.gitlab-ci.yml` and `.github/workflows/ci.yml`: nothing to change, but the
  README's `allow_failure` note can now say what `1` means.
- `CHANGELOG.md`: breaking — the exit code for a crash moves from `1` to `3`.

## Verification

```bash
uv run ruff check code_reviewer tests
uv run ruff format --check code_reviewer tests conftest.py
uv run mypy
uv run pytest --cov
./scripts/audit-deps.sh
```

## Risk register

| Risk | Mitigation |
|---|---|
| The exit-code change breaks a pipeline that treats `1` as "crashed" | It is in `CHANGELOG.md` under Breaking. The previous meaning was ambiguous, which is the finding |
| Editing a note the agent did not write | The marker is checked before every edit, and a test pins that a human reply survives |
| Truncation cuts mid-table and produces broken markdown | The notice is appended after the cut, so the output always ends in prose. A malformed table is a rendering nuisance; a rejected comment is a lost review |
| `--no-llm` produces a report that looks empty | The report states that narration was not requested, so a reader is not left wondering |
| The fake GitLab client drifts from the real API | It models `notes.list`, `note.save` and `notes.create` only — the three calls this step makes — and the adapter is thin enough that the risk is in GitLab's API changing, not in the fake |
