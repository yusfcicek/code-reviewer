# Level 0 — Implementation Plan

Branch: `feature/level-0-foundation` (off `development`)

Level 0 changes no runtime behaviour, so it has no red-green-refactor cycle of
its own. Its testable outcome is that **the test suite runs under pytest**,
which every later level's TDD loop depends on. Step 3 is therefore written
test-first: the configuration is added, and the proof is that a previously
impossible command now succeeds.

## Steps

### 1. Roadmap documents *(no code)*

- `docs/roadmap/README.md` — working agreements, level table, ordering rationale.
- `docs/roadmap/findings.md` — the full inventory, one row per finding, with
  file:line references into the baseline commit and a level assignment table.
- `docs/roadmap/level-0/spec.md`, `docs/roadmap/level-0/plan.md` — this level.

**Done when:** a reader who has never seen the code can name the three worst
defects and say which level fixes each.

### 2. Licence consistency — F-40

- Replace `LICENSE` with the MIT text (decision D-1), copyright "Yusuf Çiçek".
- Record the decision, and how to reverse it, in the spec.

**Done when:** `grep -c "GNU GENERAL PUBLIC" LICENSE` prints `0` and README's
licence link resolves to a document that says MIT.

### 3. Packaging and test configuration — F-41, F-42, F-39, F-38

- Add `[build-system]` using `hatchling`, with an explicit
  `[tool.hatch.build.targets.wheel] packages = ["openhands"]`.
- Add `license`, `authors`, `keywords`, `classifiers` and `[project.urls]`.
- Relax `requires-python` to `>=3.12` (decision D-2).
- Add `[project.scripts] ai-code-review = "openhands.agent.main:main"`.
- Add `[tool.pytest.ini_options]` with `testpaths`, `pythonpath = ["."]` and
  strict markers.
- Add `[tool.coverage.run]` scoped to the package.
- Create `tests/__init__.py`, `tests/unit/__init__.py` and a root `conftest.py`.

**Verification:** `uv run pytest -q` — a command that does not work on the
baseline — collects and passes the 10 existing tests.

> **Known carry-over:** `tests/unit/test_agent_core.py` stubs LangChain modules
> into `sys.modules` at import time (F-37), which leaks into any test collected
> afterwards. Level 0 makes pytest *run*; Level 1 removes the leak. The
> `conftest.py` documents the hazard so it is not mistaken for working design.

### 4. README truthfulness — F-49, F-50, F-51, F-52, F-53

- Remove the undocumented `--token-limit` flag from the options list (F-49).
- Fix `cd openhands` → `cd code-reviewer` (F-50).
- Correct the `--policy` description: there is no automatic default today, and
  say so (F-51).
- Redraw the project-structure block from the actual tree (F-52).
- Downgrade the metrics claim to what is actually exported, and mark the rest
  as planned (F-53).
- Add a **Current status** section listing what works, what is known broken with
  finding IDs, and a link to the roadmap.
- State Python 3.12+ to match `requires-python` (F-42).

**Done when:** every flag, path and capability in README can be pointed at in
the code, or is explicitly under "Planned".

### 5. Contributor entry point — F-46 (partial)

- `CONTRIBUTING.md`: branch naming, Conventional Commits, the TDD expectation,
  how to run tests and how the roadmap is used.

The rest of F-46 (`CHANGELOG.md`, `SECURITY.md`, `ARCHITECTURE.md`) belongs to
Level 6, once there is an architecture worth documenting.

### 6. Merge

- Commit in the order above, one commit per step, Conventional Commits style.
- Push the branch, merge into `development` with `--no-ff`, push `development`.

## Risks

| Risk | Mitigation |
|---|---|
| The GPL licence text was intentional | Decision D-1 is recorded in the spec with explicit reversal instructions; nothing has been published under either licence yet |
| `hatchling` build backend cannot see the `openhands` package | Explicit `packages = ["openhands"]`; verified by an editable sync |
| Loosening `requires-python` invalidates `uv.lock` | `>=3.12` keeps the existing resolution valid; verified by re-running `uv sync --frozen` |
