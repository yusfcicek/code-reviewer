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
| `evaluation.py` | Whether a produced finding *is* the expected one, and the confusion matrix that follows. Beside `gate.py` because both turn findings into a verdict. |
| `retrieval.py` | `CodeChunk`, rank fusion, maximal marginal relevance, cosine. The arithmetic of choosing evidence; building the index is an adapter's job. |
| `recollection.py` | What a project's reviews remember: identity, consolidation, salience with a half-life, forgetting, and recall scoped to a path. |
| `orchestration.py` | Who reviews a file, for how much, in what order, and what may be handed on. Routing, the budget split, composition and the handoff rule — all pure. |
| `trace.py` | What a review did, as a tree: spans, tree building that survives orphans and cycles, self time, the critical path. |
| `job.py` | One request for a review: its target, its lifecycle, and every transition that is refused. |
| `health.py` | `CheckResult` and `Readiness`: every failing check reported, in a stable order, naming settings and never their values. |

No I/O, no frameworks, no mocks needed to test any of it.

### `application/` — the workflow

| Module | What it holds |
|---|---|
| `ports.py` | `CodeForge`, `LLMProvider`, `MemoryStrategy`, `Reviewer`, `StaticAnalysis`, `EvaluationDataset`, `EmbeddingModel`, `LexicalIndex`, `VectorIndex`, `CodeRetriever`, plus the `FileChange`, `MergeRequestRef` and `CaseFixture` value objects. |
| `review_service.py` | The use case: triage, analyse, review, gate, report. |
| `report.py` | The merge-request comment. |
| `evaluation_service.py` | The second use case: grade the suite against a dataset. |
| `evaluation_report.py` | The evaluation run, as markdown and as JSON. |
| `retrieval_service.py` | `HybridRetriever`: two searches, fused and diversified, and what happens when one of them fails. |
| `project_memory.py` | `ProjectMemory`: recall before the run, observe during it, persist after. |
| `orchestration_service.py` | `ReviewOrchestrator`: a committee of specialists presented to the workflow as one `Reviewer`. |
| `tracing.py` | The `Tracer` and `TraceExporter` ports, and the `NullTracer` that makes instrumentation free when nobody is looking. |
| `tasks.py` | The `TaskRunner` port, `TaskOutcome`, and the `SequentialRunner` that is the default. |
| `jobs.py` | The `JobStore` port, an in-memory one, and `JobService`: accept once, hand out, record. |
| `health.py` | `ReadinessProbe`: named checks, each isolated from the others. |

`ReviewService` takes every collaborator through its constructor, so the whole
workflow runs against in-memory fakes with no network and no GitLab.

### `infrastructure/` — everything that touches the world

| Package | Implements |
|---|---|
| `analyzers/` | The five analyzers plus `StaticAnalysisSuite`, which runs them and translates their reports into `Finding`. |
| `config/` | The YAML policy loader and the shipped `review_policy.yaml`. |
| `evaluation/` | `FileSystemDataset`, which reads `evaluation/cases/*.yaml` and their fixtures. |
| `retrieval/` | Chunking, BM25, the hashed embedding, the in-memory vector index, and the corpus builder. |
| `memory/` | `SmartMemoryStrategy` for one run, and `JsonMemoryStore` for the project's history across them. |
| `forge/` | The GitLab client (`gitlab_client.py`) and `GitLabForge`, the `CodeForge` adapter. |
| `llm/` | The vLLM provider, the review agent and token counting. |
| `memory/` | `SmartMemoryStrategy`. |
| `metrics/` | OpenMetrics aggregation and export. |
| `concurrency/` | `ThreadPoolRunner`: bounded, ordered, and honest about what a timeout can and cannot do. |
| `deployment/` | The checks a running container answers `/readyz` from. |
| `http/` | The WSGI application, the GitLab webhook reader, and the worker that drains the queue. |
| `observability/` | Logging configuration and formatters, the span recorder, and the trace renderer and JSON exporter. |
| `tools/` | The tools the agent can call, and the `Workspace` that confines them. |

## Ports and adapters

| Port | Adapter | Substituting it means |
|---|---|---|
| `CodeForge` | `GitLabForge` | Supporting GitHub is a sibling module and nothing else |
| `Reviewer` | `ReviewAgent`, `ReviewOrchestrator` | A different model, a rule-only review, or a committee — the workflow cannot tell |
| `StaticAnalysis` | `StaticAnalysisSuite` | A language-specific suite |
| `LLMProvider` | `VLLMProvider` | Any OpenAI-compatible endpoint |
| `MemoryStrategy` | `SmartMemoryStrategy` | A different compression policy |
| `EvaluationDataset` | `FileSystemDataset` | Cases exported from real reviews, or held anywhere but a directory |
| `EmbeddingModel` | `HashingEmbedding` | A trained model, hosted or local — one constructor call |
| `LexicalIndex` | `BM25Index` | A search server, if a repository outgrows an in-process index |
| `VectorIndex` | `InMemoryVectorIndex` | Qdrant, or any approximate index, above ~10⁵ vectors |
| `CodeRetriever` | `HybridRetriever` | A different retrieval strategy entirely; the workflow knows one method |
| `MemoryStore` | `JsonMemoryStore` | A durable store, if a team wants its history off the checkout |
| `Specialist` | `SpecialistAgent` | A different agent per subject — a hosted assistant, a rule-only pass |
| `Tracer` | `SpanRecorder`, `NullTracer` | A different recorder; the null one is the default everywhere |
| `TraceExporter` | `JsonTraceExporter` | OTLP, or anything else — without the review path changing |
| `TaskRunner` | `SequentialRunner`, `ThreadPoolRunner` | An async-native runner, if the clients ever become async |
| `JobStore` | `InMemoryJobStore` | A store that survives a restart, when somebody decides which |

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

## The path of one retrieval

```
  main()                            build_retriever(repo_root) — once per run
    │                                 walk, chunk, embed, index
    ▼
  ReviewService._retrieve(change)
    │
    ├─► query_from_change()          the added lines, plus the file's name
    └─► CodeRetriever.related(query, limit, exclude_path)
          ├─► LexicalIndex.search()        BM25 over tokenised identifiers
          ├─► VectorIndex.search()         cosine over hashed embeddings
          ├─► reciprocal_rank_fusion()     order, not magnitude
          └─► maximal_marginal_relevance() relevance against novelty
    │
    ▼
  Reviewer.review_diff(..., related=chunks)
      rendered inside <untrusted_repository_context>
```

Two properties of that path are deliberate, and they are opposites of two
properties of the review path.

**Retrieval never blocks.** An index that cannot be built, a search that
raises, an embedding endpoint that is down: each costs the prompt some context
and nothing else. Static analysis failing *does* block, because a gate must not
read "nothing examined" as "nothing found"
([ADR 0011](adr/0011-unknown-means-blocked.md)); a prompt with less in it is
still a prompt ([ADR 0015](adr/0015-retrieval-is-hybrid-local-and-untrusted.md)).

**Retrieved code is untrusted.** It sits in the checkout, and the checkout is
what the merge request changed. Same trust boundary, same escaping, same
declaration in the system prompt.

## The deployable artefact

```
  Dockerfile          two stages; the runtime carries the venv and nothing else
    USER 10001        numeric, so runAsNonRoot can check it
    gunicorn …        code_reviewer.serve:create_app()

  deploy/kubernetes/  namespace, config, example secret, deployment, service
    livenessProbe     /healthz   ─┐ compared against ReviewApi.ROUTES in a test:
    readinessProbe    /readyz    ─┘ a renamed endpoint breaks a test, not a cluster
    replicas: 1       the queue is in memory; two replicas do not share it
```

Both are parsed by `tests/unit/test_deployment_manifests.py`. A Dockerfile that
claims a non-root user and a manifest that claims a readiness path are claims,
and this repository's oldest rule is that documentation may never claim
behaviour the code does not have
([ADR 0021](adr/0021-a-deployment-that-is-tested.md)).

`SIGTERM` stops the server and drains the worker within a bound, then says
which of "finished" and "gave up" happened — and
`terminationGracePeriodSeconds` is asserted to exceed that bound, because the
two numbers live in different files.

## The service surface

```
  POST /reviews          202 + id + Location   ← or 200 when it is already in flight
  GET  /reviews/{id}     state, verdict, exit code, trace id — never the comment
  POST /webhooks/gitlab  X-Gitlab-Token, verified before the body is read
  GET  /healthz          this process is running
  GET  /readyz           it can accept work — no third party is called
  GET  /metrics          OpenMetrics text
```

A WSGI callable, not a framework
([ADR 0020](adr/0020-a-wsgi-application-not-a-framework.md)). It is one adapter:
it calls `JobService`, and a worker thread takes what it accepted through
`ReviewService`. No gate logic, no policy, no rendering — a gRPC surface would
be a sibling module against the same objects.

```
  ReviewApi (WSGI)  ──►  JobService  ──►  JobStore
                              ▲
                              │ claim / complete / fail
                        ReviewWorker  ──►  ReviewService.review(...)
```

Three properties are deliberate.

**Authentication is asserted over the route table**, which is data — so a route
added later is covered by construction rather than by somebody remembering.

**Idempotency is keyed on the commit**, not the merge request: a push is a new
review, and collapsing the two would silently drop it.

**Job state is in memory and the process says so.** The store is a port, so the
decision about persistence has somewhere to go.

## What runs at once

The specialists reviewing one file run concurrently; files stay sequential.

```
  ReviewOrchestrator._run_group(brief, assignments)
    │
    ├─ parent = tracer.current_span_id      ← captured HERE, on this thread
    │
    └─► TaskRunner.run_all([task, task, task, task], timeout_s)
          each task:  with tracer.bind(parent):  Specialist.review(...)
    │
    └─► outcomes, in the order the assignments were planned
```

Three properties, and each is asserted as an equality against the sequential
path rather than described.

**Order is by plan.** The futures list *is* the plan; the composed report, the
per-agent accounting and the verdict are byte-identical under either runner.

**The parent span is captured at submission.** A worker has its own stack and
it is empty — it does not know what queued it. That one argument is the whole
of the concurrency-correctness story for tracing.

**A timed-out task is abandoned, not cancelled.** Python cannot kill a thread,
so the pool is marked tainted and replaced rather than reused
([ADR 0019](adr/0019-threads-behind-a-port.md)).

Three objects acquired locks with this level: the tracer's span list, the
workspace's read budget, and the memory's insight lists. Each has a test that
runs eight threads at it and checks the result.

## The trace over all of it

```
  1     review                          project, merge request
  1.1   file        src/app.py
  1.1.1 analysis    static analysis      path
  1.1.2 retrieval   related code         path, chunks
  1.1.3 memory      recall               path
  1.1.4 agent       architecture         budget, tool_calls, ok
  1.1.4.1 model     invoke               iteration
  1.1.4.2 tool      run_semantic_analysis
  1.1.5 agent       security             budget, tool_calls, ok
```

Identifiers are dotted counters, so the tree's shape is visible in a flat log
line and two spans can be compared by eye. Every log record emitted inside a
span carries `trace_id` and `span_id`, which is the join between a log line and
this tree — and what makes two interleaved reviews separable.

Three properties are deliberate.

**Self time, not duration.** A parent's duration includes everything below it;
the number that answers "where did the time went" is its own share, and it is
totalled per kind.

**Nothing is lost to bad input.** An orphan attaches to the root, a cycle is
broken, a second root is adopted — each recorded as an anomaly rather than
hidden.

**Attributes are identifiers, never content.** Enforced by a length cap at
construction and by a test that runs a real review whose diff contains a
credential-shaped string and asserts it reaches no attribute
([ADR 0018](adr/0018-a-trace-of-our-own.md)).

## The path of one committee

```
  ReviewService                     one question: "review this file"
    │
    ▼
  ReviewOrchestrator.review_diff(brief)      ← a Reviewer, like any other
    │
    ├─► plan_assignments(findings, is_manifest)   pure: who this file warrants
    ├─► split_budget(total - reserve, plan)       pure: weighted, sums exactly
    │
    ├─► for each specialism, in order:
    │     └─► Specialist.review(brief, assignment)
    │           ├─ narrowed tool catalogue
    │           ├─ its own system prompt, with the shared trust boundary
    │           └─ budget → iteration cap
    │
    ├─► accept_handoffs(requests, ran, depth=0)   pure: at most one round
    │     └─► the accepted, on the reserve, at depth 1 — where all are refused
    │
    └─► compose(reports) + footer                 fixed order, attributed
```

Three properties are deliberate.

**The workflow does not know.** `ReviewService` calls a `Reviewer`; whether one
model or five answered is the reviewer's business
([ADR 0017](adr/0017-an-orchestrator-of-specialists-not-a-framework.md)).

**Nothing here reaches the gate.** The analyzers ran before any agent, and the
verdict is theirs ([ADR 0004](adr/0004-findings-drive-the-gate.md)). Four
narrators change what the report says, not what the pipeline does.

**One failure costs one section.** A specialist that raises is recorded, stated
in the report, and the rest still run.

## The path of one memory

```
  main()                          JsonMemoryStore(.review-memory.json)
    │                               unless --no-memory
    ▼
  ReviewService.review(...)
    │
    ├─► ProjectMemory.recall(path)          → Reviewer.review_diff(recollections=…)
    │     what was known BEFORE this run
    │
    ├─► ProjectMemory.recurrence_of(finding) → render_review_comment(recurring=…)
    │
    └─► after the comment is built:
          ├─► observe_findings() / observe_suppressions()
          ├─► consolidate → forget → retain
          └─► MemoryStore.save()            atomic: temp file, then rename
```

Recall reads the state from *before* the run. A finding reported for the first
time this morning is not a recurring finding, and a memory that counted the
sighting it is describing would say it was.

Nothing on this path reaches the gate. `TestMemoryNeverDecides` runs one review
twice — with a 99-sighting history and with none — and requires the verdict, the
exit code and the findings to be identical
([ADR 0016](adr/0016-memory-informs-and-never-decides.md)).

## The path of one evaluation

```
  ai-code-review-eval               second entry point, not a subcommand
    │
    ▼
  EvaluationService.evaluate(dataset)
    │
    └─► for each case:
          ├─► EvaluationDataset.cases()      the annotation, and the fixture
          ├─► StaticAnalysis.analyze()       the same call the review makes
          └─► grade(case, findings)          expectations claim findings, 1:1
    │
    ├─► render_evaluation_report()  → stdout or a file
    ├─► evaluation_summary()        → JSON artefact, so F1 becomes a series
    └─► exit 0 / 1 / 2              cleared / too low / could not be measured
```

No model, no network, no forge. The harness drives the `StaticAnalysis` port
and nothing else, which is what lets it run on every push
([ADR 0014](adr/0014-evaluation-is-a-dataset-not-a-fixture.md)).

A finding a case does not grade is *ungraded*, counted and named — never
dropped. That is what stops a narrow scope from being an invisible way to
improve a score, and it is the same argument suppression makes at Level 11.

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
