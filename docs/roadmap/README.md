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
| [15](level-15/spec.md) | Multi-agent orchestration | ✅ Done |
| [16](level-16/spec.md) | Tracing & agent observability | ✅ Done |
| [17](level-17/spec.md) | Asynchronous execution | ✅ Done |
| [18](level-18/spec.md) | Service surface — HTTP API & webhooks | ✅ Done |
| [19](level-19/spec.md) | Containerisation & cloud-native deployment | ✅ Done |
| [20](level-20/spec.md) | Governance, explainability & compliance | ✅ Done |
| [21](level-21/spec.md) | Grading the reviewer's prose | ✅ Done |
| [22](level-22/spec.md) | A fix you can apply, and never one we applied | ✅ Done |
| [23](level-23/spec.md) | Documentation that cannot quietly lie | ✅ Done |
| [24](level-24/spec.md) | A record somebody else can check | ✅ Done |
| [25](level-25/spec.md) | A measurement that says how much it knows | ✅ Done |
| [26](level-26/spec.md) | More of the fixes that are arithmetic | ✅ Done |

### Why *this* order for 12–20

Measurement first. Every level after 12 changes what the agent says, and a
change to what an LLM says has no natural regression signal — test coverage
proves the code ran, not that the review got better. Level 12 builds the
scoreboard so levels 13–15 can be judged rather than asserted.

Then capability, in dependency order: retrieval (13) gives the agent evidence
beyond the diff; long-term memory (14) is retrieval over the *project's own
history* — the plan said it would reuse 13's index, and Level 14 found that
wrong and said so: a chunk index answers "what code looks like this" and a
memory answers "what has this rule done in this file", and forcing one to serve
both would have made both worse
([ADR 0016](../adr/0016-memory-informs-and-never-decides.md));
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

### What the second roadmap closed, and what it did not

Twenty capabilities were drawn from three role descriptions
([`capability-sources.md`](capability-sources.md)). Nine levels closed them:

| Capability | Where |
|---|---|
| C-01, C-02, C-03 — measured review quality, a quality signal, regression across a prompt change | [12](level-12/spec.md) |
| C-04, C-05, C-06 — retrieval over the checkout, embeddings, hybrid ranking | [13](level-13/spec.md) |
| C-08 — long-term memory, and forgetting | [14](level-14/spec.md) |
| C-09, C-10 — an orchestrator of specialists, and a handoff protocol | [15](level-15/spec.md) |
| C-12 — a trace of the whole review, joined to the logs | [16](level-16/spec.md) |
| C-13 — concurrent agents behind a port | [17](level-17/spec.md) |
| C-14, C-15 — an HTTP surface, webhooks, and a second integration point | [18](level-18/spec.md) |
| C-16, C-17 — a tested image, manifests, readiness and a bounded drain | [19](level-19/spec.md) |
| C-18, C-19, C-20 — a decision record, an enforced invariant, a versioned run | [20](level-20/spec.md) |

C-07 (short-term memory) and C-11 (tool-calling loops) were already met when
the inventory was taken, and are recorded that way rather than rebuilt.

Three things were named as goals and deliberately not built, each with the
reason written down rather than left to be inferred: a trained embedding model
(the hashed one is deterministic and needs no endpoint — the port is there),
signing and an append-only audit store (the key belongs to a deployment, not to
this repository), and any mapping onto a compliance framework (an
organisation's obligations are not this project's to guess at).

Two predictions in this file were wrong and were reversed in the open: Level
14's index reuse, above, and Level 16's "the trace goes in the comment" — a
forty-span tree in a merge-request comment is noise, so the comment carries the
trace *id* and the tree is an artefact.

The project's own gate blocked its own build four times during these levels —
complexity in the retrieval query builder, a quality score on the tool
definitions, complexity in the comment renderer, and a false positive where a
`threading.Lock` was reported as a leaked resource. Each was fixed rather than
suppressed; the last one became an evaluation case, so it stays fixed.

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
