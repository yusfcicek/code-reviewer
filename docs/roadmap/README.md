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
| [7](level-7/spec.md) | Dependency & tool-protocol upgrade | ✅ Done |
| [8](level-8/spec.md) | Untrusted input hardening | ✅ Done |
| [9](level-9/spec.md) | Fail-closed decisions | ✅ Done |
| [10](level-10/spec.md) | Operability | ✅ Done |
| [11](level-11/spec.md) | Verification depth | ✅ Done |

Levels 0–11 answered a single question: *is this repository trustworthy?* The
levels below answer a different one — *is this agent capable?* — and they are
sourced differently. Levels 0–11 came from the findings inventory, i.e. from
defects. Levels 12–20 come from three role descriptions
([`capability-sources.md`](capability-sources.md)) that state what an agentic
AI system in a regulated bank is expected to do, and from the gap between that
statement and what this repository does today.

| Level | Theme | Status |
|---|---|---|
| [12](level-12/spec.md) | Evaluation harness — measuring review quality | ✅ Done |
| [13](level-13/spec.md) | Retrieval over the repository | ✅ Done |
| [14](level-14/spec.md) | Long-term memory across reviews | ✅ Done |
| 15 | Multi-agent orchestration | ⏳ Planned |
| 16 | Tracing & agent observability | ⏳ Planned |
| 17 | Asynchronous execution | ⏳ Planned |
| 18 | Service surface — HTTP API & webhooks | ⏳ Planned |
| 19 | Containerisation & cloud-native deployment | ⏳ Planned |
| 20 | Governance, explainability & compliance | ⏳ Planned |

### Why *this* order for 12–20

Measurement first. Every level after 12 changes what the agent says, and a
change to what an LLM says has no natural regression signal — test coverage
proves the code ran, not that the review got better. Level 12 builds the
scoreboard so levels 13–15 can be judged rather than asserted.

Then capability, in dependency order: retrieval (13) gives the agent evidence
beyond the diff; long-term memory (14) is retrieval over the *project's own
history*, so it reuses 13's index rather than inventing a second one;
multi-agent orchestration (15) is only worth its cost once each specialist has
something to retrieve.

Then the operational consequences of having built all that. Tracing (16) is
scoped after 15 deliberately — tracing a single-agent loop is logging with
extra ceremony, whereas tracing an orchestrator with handoffs is the only way
to answer "which agent decided this". Async (17) follows tracing so the spans
survive concurrency instead of being retrofitted onto it. The service surface
(18) and its deployment (19) turn a CI job into something callable.

Governance (20) is last because it is a claim *about* the other eight: it
records which model, which prompt version, which retrieved evidence and which
agent produced each finding. There is nothing to record until they exist.

### Deferred, then done

| Item | Why it waited | Closed by |
|---|---|---|
| LangChain 0.1 → 1.x upgrade | 0.2 relocated `AgentExecutor` and 1.0 removed it, and its replacement cannot parse a tool call out of message text — which is the only way the Hermes path works. It needed its own spec and its own contracts, not a line change inside a CI level. | [Level 7](level-7/spec.md): the loop moved in-tree, and the upgrade followed with no source change. 59 advisories → 0. |

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
