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
| [0](level-0/spec.md) | Foundation & documentation truth | ✅ Done |
| [1](level-1/spec.md) | Correctness — fix behaviour that silently does nothing | ✅ Done |
| [2](level-2/spec.md) | DDD layering — domain, application, infrastructure | ✅ Done |
| [3](level-3/spec.md) | Analyzer accuracy & policy enforcement | ✅ Done |
| [4](level-4/spec.md) | Observability & resilience | ✅ Done |
| [5](level-5/spec.md) | CI/CD & quality gates | ✅ Done |
| [6](level-6/spec.md) | Documentation & productisation | ✅ Done |

### Deferred with a reason

| Item | Why it is not done | Where |
|---|---|---|
| LangChain 0.1 → 0.3 upgrade | 0.2 relocated `AgentExecutor` and reworked the prompt and scratchpad APIs the Hermes tool loop is written against. It needs its own spec, its own contracts and a run against a live model — not a line change inside a CI level. | F-45, `pyproject.toml` |

The complete inventory of defects that produced these levels is in
[`findings.md`](findings.md). Each finding carries an ID (`F-NN`) that the
level specs reference, so every fix is traceable back to an observation.

Five of the 59 findings were discovered *while fixing others* — F-55 and F-56
when the policy file was loaded for the first time, F-57 when the workflow got
its first tests, F-58 and F-59 while specifying observability. That is the
argument for the order: each level makes the next one's defects visible.

## Why this order

The levels are ordered by **dependency, not by ambition**.

- Level 0 makes the repository trustworthy: without a baseline commit, a
  `.gitignore` and honest documentation, every later claim is unverifiable.
- Level 1 fixes code that *looks* correct but does nothing. Refactoring broken
  behaviour into a nicer architecture would only preserve the bugs.
- Level 2 can then move working code into a layered structure with confidence,
  because tests from Level 1 pin the behaviour down.
- Levels 3–6 build product quality on top of a structure that can absorb it.
