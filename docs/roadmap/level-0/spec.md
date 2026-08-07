# Level 0 — Foundation & Documentation Truth

## Problem statement

The imported repository has no history, no packaging metadata, contradictory
licensing, and a README that describes a product noticeably better than the one
in the tree. In that state nothing can be verified: a reader cannot tell which
claims are aspirational and which are implemented, and a contributor cannot
install the package or run the test suite in a reproducible way.

Level 0 does not change runtime behaviour. It makes the repository **honest and
installable**, so that every later level can be judged against a stable
baseline.

Findings addressed: **F-40, F-41, F-42, F-43, F-46 (partial), F-49, F-50, F-51,
F-52, F-53**, plus the testing scaffolding needed by every later level
(**F-38, F-39**).

## Goals

1. **One answer per question.** Licence, supported Python versions, entry point
   and project structure are stated once and agree everywhere.
2. **Installable package.** `uv sync` followed by an import of the package works
   without `sys.path` manipulation from the caller's side.
3. **Runnable test suite.** `uv run pytest` collects and runs the existing
   tests, with configuration living in `pyproject.toml`.
4. **Honest README.** Every capability listed is either implemented today or
   explicitly marked as planned, with a pointer to the roadmap.
5. **Traceable roadmap.** The findings inventory and the per-level specs and
   plans live in the repository, not in a conversation.

## Non-goals

- Fixing any of the correctness defects (Level 1).
- Moving or renaming modules (Level 2).
- Adding CI pipelines beyond documenting that they are missing (Level 5).

## Acceptance criteria

| # | Criterion | How it is verified |
|---|---|---|
| AC-1 | The repository declares exactly one licence, and `LICENSE`, `README.md` and `pyproject.toml` agree on it | Read all three; `grep -c "GNU GENERAL PUBLIC" LICENSE` returns `0` |
| AC-2 | `pyproject.toml` has a `[build-system]`, a `license`, `authors`, `urls`, `classifiers` and a console entry point | `uv run python -c "import importlib.metadata as m; m.version('...')"` succeeds |
| AC-3 | `requires-python` agrees with the version README promises | Both state `>=3.12` |
| AC-4 | `uv run pytest` collects and passes the existing tests | Command exits `0` |
| AC-5 | Test layout has `tests/__init__.py`, `tests/unit/__init__.py` and a `conftest.py` that keeps the repository root importable | `uv run pytest` works from a clean checkout |
| AC-6 | README documents no CLI flag that `main.py` does not define | Every flag in README appears in `argparse` |
| AC-7 | README's project-structure block matches `find . -type d` | Manual diff, checked in review |
| AC-8 | README distinguishes implemented behaviour from planned behaviour | A "Current status" section exists and links to the roadmap |
| AC-9 | The roadmap (`docs/roadmap/`) contains the findings inventory and this level's spec and plan | Files exist and are linked from the root README |

## Decisions taken

**D-1 — Licence: MIT.** `LICENSE` contained GPL-3.0 while `README.md` linked it
as "MIT License". The repository has no publication history (Level 0 creates the
first commit), so no third party has relied on either text. README states the
author's intent explicitly, and a permissive licence matches a tool meant to be
embedded in other organisations' pipelines. `LICENSE` is therefore replaced with
the MIT text and `pyproject.toml` declares `license = "MIT"`. *If the GPL text
was deliberate, this is the one decision in Level 0 that must be reverted before
publication.*

**D-2 — `requires-python = ">=3.12"`.** The baseline pinned `==3.12.12`, a
single patch release, which makes the project uninstallable on any other
interpreter; README promised 3.10+. The code itself only needs 3.9+ features
(`ast.unparse`, `end_lineno`), but the committed `uv.lock` resolves against
3.12, and loosening to 3.10 would require re-resolving every dependency without
a way to test the older interpreters here. `>=3.12` is the honest, verifiable
middle: it keeps the locked resolution valid and stops pinning a patch release.
README is corrected to match.

**D-3 — Keep the `openhands` package name for now.** Renaming touches every
import and every test. It is scheduled for Level 2, where the package is
restructured anyway, so the churn happens once.

**D-4 — README shrinks before it grows.** Claims that are not true today are
either removed or moved under a "Planned" marker, rather than being left in
place with a caveat. A feature list is a contract.
