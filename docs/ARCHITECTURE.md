# Architecture

## The shape of it

```
infrastructure  ──►  application  ──►  domain
```

Dependencies point one way. The domain imports nothing but the standard
library; the application imports the domain and the ports it declares itself;
infrastructure implements those ports and is imported by nothing above it,
except the composition root, which exists to wire everything together.

`tests/unit/test_architecture.py` parses every module's imports and fails if
that direction is ever reversed. It also asserts that exactly one `Severity`,
one `Finding` and one `AffectedCode` exist in the tree.

## The layers

### `domain/` — the rules of code review

| Module | What it holds |
|---|---|
| `severity.py` | The one severity scale. Ordered, so the most severe compares as the smallest and `sorted()` needs no key. |
| `finding.py` | `Finding`, `FindingCategory`, `AffectedCode`, `DependencyType`. What every analyzer produces. |
| `policy.py` | `ReviewPolicy` and its sections. Plain dataclasses; reading them from YAML happens elsewhere. |
| `triage.py` | How much review a change warrants, and why. |
| `gate.py` | One file's verdict: `PASS`, `WARN` or `FAIL`. |
| `outcome.py` | The merge request's verdict, aggregated from the files'. |

No I/O, no frameworks, no mocks needed to test any of it.

### `application/` — the workflow

| Module | What it holds |
|---|---|
| `ports.py` | `CodeForge`, `LLMProvider`, `MemoryStrategy`, `Reviewer`, `StaticAnalysis`, plus the `FileChange` and `MergeRequestRef` value objects. |
| `review_service.py` | The use case: triage, analyse, review, gate, report. |
| `report.py` | The merge-request comment. |

`ReviewService` takes every collaborator through its constructor, so the whole
workflow runs against in-memory fakes with no network and no GitLab.

### `infrastructure/` — everything that touches the world

| Package | Implements |
|---|---|
| `analyzers/` | The five analyzers plus `StaticAnalysisSuite`, which runs them and translates their reports into `Finding`. |
| `config/` | The YAML policy loader and the shipped `review_policy.yaml`. |
| `forge/` | The GitLab client (`gitlab_client.py`) and `GitLabForge`, the `CodeForge` adapter. |
| `llm/` | The vLLM provider, the review agent and token counting. |
| `memory/` | `SmartMemoryStrategy`. |
| `metrics/` | OpenMetrics aggregation and export. |
| `observability/` | Logging configuration and formatters. |
| `tools/` | The tools the agent can call, and the `Workspace` that confines them. |

## Ports and adapters

| Port | Adapter | Substituting it means |
|---|---|---|
| `CodeForge` | `GitLabForge` | Supporting GitHub is a sibling module and nothing else |
| `Reviewer` | `ReviewAgent` | A different model, or a rule-only review |
| `StaticAnalysis` | `StaticAnalysisSuite` | A language-specific suite |
| `LLMProvider` | `VLLMProvider` | Any OpenAI-compatible endpoint |
| `MemoryStrategy` | `SmartMemoryStrategy` | A different compression policy |

## The path of one review

```
  main()                          composition root: build the adapters
    │
    ▼
  ReviewService.review(project, mr)
    │
    ├─► CodeForge.fetch_merge_request()      what are we reviewing?
    ├─► CodeForge.fetch_changes()            what moved?
    │
    └─► for each changed file:
          ├─► CodeForge.fetch_file()          the file at the reviewed commit
          ├─► ReviewTriage.decide()           does this need a model at all?
          │     ├─ SKIP           → nothing further
          │     ├─ AUTO_APPROVE   → a line in the comment, no gate
          │     └─ otherwise      ↓
          ├─► StaticAnalysis.analyze()        findings, unconditionally
          ├─► Reviewer.review_diff()          the model's architectural read
          ├─► ReviewGate.evaluate(text, findings)
          │      findings block; prose warns
          └─► ReviewOutcome.record()
    │
    ├─► render_review_comment()  → CodeForge.publish_comment()
    ├─► MetricsCollector         → metrics.txt
    └─► ReviewOutcome.exit_code(policy)
```

Two properties of that path are deliberate:

**Analysis is unconditional.** The analyzers are also exposed as agent tools,
but the suite runs whether or not the model asks. Whether a file gets a security
scan must not depend on what the model felt like doing
([ADR 0004](adr/0004-findings-drive-the-gate.md)).

**A failing file is not a failing run.** An exception on one file is caught,
recorded against that file, and reported in the comment as *not reviewed* —
which is a warning, not an approval
([ADR 0006](adr/0006-a-failing-file-is-reported-not-fatal.md)).

## Extending it

**A new analyzer.** Add it under `infrastructure/analyzers/`, then a
`_x_findings` adapter on `StaticAnalysisSuite` translating its report into
`Finding`. Nothing above infrastructure changes. Keep its own result type: the
suite adapts, which is why five analyzers did not need rewriting when the gate
started reading findings.

**A new forge.** Implement `CodeForge` beside `GitLabForge` and construct it in
`__main__.py`. `FileChange` and `MergeRequestRef` are the vocabulary; if a
forge concept does not fit them, extend the value objects rather than leaking
the forge's own types upward.

**A new model provider.** Implement `LLMProvider`. If it does not speak the
Hermes tool dialect, `ReviewAgent`'s parser and scratchpad formatter are what
change.

**A new policy knob.** Add the field to the dataclass in `domain/policy.py`,
document it in `review_policy.yaml`, and read it where it applies. The loader
merges by attribute name, so nothing else is needed — and a key it does not
recognise is logged rather than ignored.

## What is deliberately not abstracted

**The analyzers have no common interface.** Their only consumer is the suite,
which calls them by name. An `Analyzer` protocol would be speculative
generality; if a second implementation of one appears, that is the moment.

**There is no repository or unit of work.** A review reads a merge request and
writes one comment. A persistence abstraction over that would be ceremony.

**The prompt is not templated beyond `ChatPromptTemplate`.** It is one system
message, one tool catalogue and one user turn. Making it configurable would
invite a class of bug — a prompt that no longer matches the parser — for a
flexibility nobody has asked for.

## Where the decisions are

`docs/adr/` holds one record per binding decision, each with its context and
consequences. [`docs/roadmap/`](roadmap/README.md) holds how the work was
sequenced and the 59-item findings inventory it came from.
