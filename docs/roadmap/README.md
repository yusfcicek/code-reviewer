# Improvement Roadmap

This roadmap turns the imported prototype into a maintainable product. It is
organised into **levels**. A level is a coherent slice of work that leaves the
repository in a better, still-shippable state.

Every level follows the same three-step rhythm:

1. **Spec** (`level-N/spec.md`) — what is wrong today, what "done" means, and
   which observable behaviour must change. Written before any code.
2. **Plan** (`level-N/plan.md`) — the ordered, testable steps that satisfy the
   spec, including the tests that must exist and fail first.
3. **Implementation** — executed on a `feature/level-N-*` branch, merged into
   `development` when the level's acceptance criteria hold.

## Working agreements

| Topic | Agreement |
|---|---|
| Branching | `feature/level-N-<slug>` off `development`; merged back with `--no-ff` |
| Commits | Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`) |
| Tests | TDD — a failing test precedes every behaviour change |
| Design | Domain-Driven Design — domain logic stays free of I/O and framework types |
| Docs | Documentation may never claim behaviour the code does not have |

## Levels

| Level | Theme | Status |
|---|---|---|
| [0](level-0/spec.md) | Foundation & documentation truth | 🚧 In progress |
| 1 | Correctness — fix behaviour that silently does nothing | 📋 Planned |
| 2 | DDD layering — domain, application, infrastructure | 📋 Planned |
| 3 | Analyzer accuracy & policy enforcement | 📋 Planned |
| 4 | Observability & resilience | 📋 Planned |
| 5 | CI/CD & quality gates | 📋 Planned |
| 6 | Documentation & productisation | 📋 Planned |

The complete inventory of defects that produced these levels is in
[`findings.md`](findings.md). Each finding carries an ID (`F-NN`) that the
level specs reference, so every fix is traceable back to an observation.

## Why this order

The levels are ordered by **dependency, not by ambition**.

- Level 0 makes the repository trustworthy: without a baseline commit, a
  `.gitignore` and honest documentation, every later claim is unverifiable.
- Level 1 fixes code that *looks* correct but does nothing. Refactoring broken
  behaviour into a nicer architecture would only preserve the bugs.
- Level 2 can then move working code into a layered structure with confidence,
  because tests from Level 1 pin the behaviour down.
- Levels 3–6 build product quality on top of a structure that can absorb it.
