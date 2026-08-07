# Level 5 — CI/CD and Quality Gates

## Problem statement

Four levels of work are held in place by 412 tests that nothing runs
automatically. There is no pipeline, no linter, no formatter, no type checker
and no coverage floor. Every guarantee established so far depends on a human
remembering to run `uv run pytest` before pushing.

Specifically:

- **No pipeline exists.** README presents GitLab CI integration as the primary
  use case and shows a job definition, but the repository contains no
  `.gitlab-ci.yml` and no GitHub Actions workflow. The project that reviews
  other people's merge requests does not review its own (F-44).
- **No static checks.** A first `ruff` run reports 1 574 issues across the
  package and the tests: unused imports, bare `except:` clauses, implicit
  `Optional`, mutable class defaults, deprecated typing imports (F-48).
- **No coverage floor.** Coverage is configured but nothing enforces it, so it
  can regress silently (F-39).
- **Dependencies are two years old.** `langchain==0.1.0`,
  `langchain-community==0.0.10` and `openai==1.12.0` are pinned to early-2024
  releases (F-45).

Findings addressed: **F-39, F-44, F-45, F-48**.

## Goals

1. Every push and merge request runs the full suite, the linter, the formatter
   check and the type checker.
2. The style rules are in the repository, enforced identically on a laptop and
   in CI.
3. Coverage cannot regress below a stated floor.
4. The project reviews its own merge requests with its own agent.
5. The dependency situation is either fixed or documented with a reason.

## Non-goals

- Publishing to PyPI. The distribution metadata exists; releasing is a decision
  for the owner, not a task for this level.
- Full `mypy --strict`. The codebase has partial annotations; strict mode would
  produce hundreds of errors and pressure toward `Any`. The type checker is
  introduced where it pays: the domain and application layers.

## Behavioural contracts

### C-1 — One command checks everything (F-48)
`uv run ruff check`, `uv run ruff format --check`, `uv run mypy` and
`uv run pytest` all pass on a clean checkout. Configuration lives in
`pyproject.toml`, so a contributor and CI apply the same rules.

### C-2 — The linter's findings are fixed, not silenced (F-48)
Rules are switched off only where they are wrong for this project, and each
exclusion carries a comment saying why. Real defects the linter surfaces —
bare `except:`, unused imports, implicit `Optional`, mutable class defaults —
are fixed.

### C-3 — Coverage has a floor (F-39)
`pytest` fails when total coverage drops below the stated threshold. The
threshold is set to the current value rounded down, so it ratchets rather than
aspires.

### C-4 — CI runs on GitHub and the agent runs on GitLab (F-44)
- `.github/workflows/ci.yml` runs lint, format check, types and tests on push
  and pull request.
- `.gitlab-ci.yml` runs the same checks and adds the agent reviewing the merge
  request that triggered it. The job people are told to copy is one that is
  demonstrably in use.

### C-5 — The dependency position is deliberate (F-45)
Each pinned dependency is either updated or carries a comment explaining what
blocks the update. "It is old" is a finding; "it is old and here is why" is a
decision.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | `uv run ruff check` reports no errors | Command |
| AC-2 | `uv run ruff format --check` reports no changes | Command |
| AC-3 | `uv run mypy code_reviewer/domain code_reviewer/application` passes | Command |
| AC-4 | `uv run pytest` fails if coverage drops below the floor | Deliberate check |
| AC-5 | No bare `except:` remains in the package | `ruff` rule E722 enabled |
| AC-6 | `.github/workflows/ci.yml` and `.gitlab-ci.yml` exist and are valid YAML | A test parses them |
| AC-7 | The GitLab pipeline includes a job running this agent | Same test |
| AC-8 | Every dependency pin has a rationale or a recent version | `pyproject.toml` review |

## Decisions taken

**D-1 — `ruff` for both linting and formatting.** It replaces `flake8`,
`isort`, `pyupgrade` and `black` with one tool and one configuration block. One
fewer dependency, one fewer way for two tools to disagree.

**D-2 — `RUF001`/`RUF002`/`RUF003` are disabled.** These flag "ambiguous
Unicode characters". The codebase's docstrings are partly Turkish, and typographic
dashes are used deliberately in prose. 482 of the 1 574 initial findings are
this rule objecting to correct text.

**D-3 — `mypy` on the domain and application layers only.** Those layers have
no framework types and are where a type error would be a genuine design fault.
Running it over the infrastructure layer would mostly report LangChain's own
missing annotations.

**D-4 — Coverage floor at the current value, rounded down.** A floor above the
current value fails immediately and gets disabled; a floor far below it permits
silent decay. Rounding the measured value down does neither.

**D-5 — Dependencies stay pinned for now, with the reason recorded.**
`langchain==0.1.0` is two years old, and 0.2 moved `AgentExecutor` and the
prompt APIs this project builds on. Upgrading is a level's worth of work with
its own contracts and its own risk, not a line change inside a CI level. The
pin now carries a comment saying exactly that, and the roadmap gains an entry.
Level 5 does not leave the situation undocumented, which was the actual finding.
