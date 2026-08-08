# Contributing

## Getting set up

```bash
uv sync
uv run pre-commit install     # runs ruff on commit
```

Before pushing, run what CI runs:

```bash
uv run ruff check code_reviewer tests
uv run ruff format --check code_reviewer tests conftest.py
uv run mypy
uv run pytest --cov
```

`pytest` on its own skips coverage so that running a single test file is fast;
`--cov` applies the floor in `[tool.coverage.report]`, which CI enforces. The
floor ratchets: raise it when coverage rises, never lower it to make a red
build green.

`uv sync` installs the project in editable mode, so `uv run ai-code-review` and
`import openhands.agent…` both work without any `sys.path` juggling.

## Branching

```
main         released state
development  integration branch — features merge here
feature/*    one branch per roadmap level or change
```

Branch off `development`, name the branch after what it does
(`feature/level-1-correctness`, `fix/gate-enum-comparison`), and merge back with
`--no-ff` so the level boundary stays visible in the history.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <imperative summary, ≤72 chars>

<body: what was wrong, what changed, why this approach>

Refs: F-NN
```

Types in use: `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `chore`,
`perf`.

The body matters more than the summary. State the defect the commit removes,
not the files it touches — the diff already lists those. When the change
addresses an entry in [`docs/roadmap/findings.md`](docs/roadmap/findings.md),
cite the finding ID so the fix stays traceable to the observation.

## Test-driven development

Every behaviour change starts with a failing test.

1. Write a test that fails for the reason you are about to fix, and run it to
   watch it fail. A test that passes before the fix is testing something else.
2. Make it pass with the smallest change that is honest.
3. Refactor with the test green.

Bug fixes get a regression test that reproduces the bug through the public
surface of the component, not through a private helper. If a defect could not be
caught by a test at the current design, that is a design finding — record it in
`findings.md` rather than reaching into internals.

Layout:

```
tests/unit/          one component, no network, no filesystem beyond tmp_path
tests/integration/   several components together, still no network (mark: integration)
```

## Design

The codebase is being moved onto Domain-Driven Design boundaries:

- **Domain** — review rules, severities, findings, policies. Pure Python: no
  I/O, no `subprocess`, no LangChain, no GitLab types. Testable without mocks.
- **Application** — orchestration of a review: triage, analyze, gate, report.
  Depends on domain types and on ports, never on concrete adapters.
- **Infrastructure** — GitLab, vLLM, the filesystem, `grep`. Implements the
  ports the application declares.

Two rules follow from this and are enforced in review:

1. A framework type may not appear in a domain signature. If a port returns
   "the underlying LangChain object", the port is not doing its job.
2. One concept, one model. Before adding a `Severity`, a `Finding` or a config
   dataclass, check whether the shared kernel already has one.

## Roadmap

Work is organised into levels under [`docs/roadmap/`](docs/roadmap/README.md).
Each level has a spec written before the plan and a plan written before the
code. If you find a defect that no level covers, add it to `findings.md` with a
file:line reference and a severity, then assign it to a level.


## Suppressing a finding

The agent analyses its own source on every push, so a finding against this
repository has to be dealt with before a change lands. There are three
answers, and they are not equally good:

1. **Fix it.** Most findings are right. Of the 33 the first dogfooding run
   surfaced, 28 were fixed.
2. **Suppress it, with a reason.** For a rule that is right in general and
   wrong here — an analyzer reading its own rule table, a docstring
   documenting the insecure default it exists to have removed:

   ```python
   verify = False  # review-ignore: SAST.INSECURE_HTTP - behind an explicit env flag
   ```

   The reason is not decoration. It is what the next person reads instead of
   re-deriving your judgement, and `tests/unit/test_dogfooding.py` fails on a
   directive without one.
3. **Report the rule.** If it misfires generally, suppressing it here hides
   the problem from every other user. Open it as its own item.

The suppression cap in the dogfooding test is deliberate. Raising it is a
visible edit in a diff someone reviews — which is the only thing standing
between "the package passes its own gate" and "the package has been quietened
until it does".
