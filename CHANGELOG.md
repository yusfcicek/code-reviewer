# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.19.0] — 2026-08-10

Level 25 — a measurement that says how much it knows. Recorded in
[`docs/roadmap/level-25/spec.md`](docs/roadmap/level-25/spec.md) and
[ADR 0027](docs/adr/0027-a-score-that-states-its-own-uncertainty.md).

This repository has printed `1.00 over eleven cases` since Level 12 and treated
the two halves as one fact. Both are true; together they mislead, and the
arithmetic says by how much — ten of ten is consistent with a real rate of 0.72.

### Added

- **A Wilson interval on every score**, with the method and confidence printed
  beside it. The normal approximation gives `[1.00, 1.00]` at fifteen of
  fifteen, which is how this happened in the first place.
- **Coverage per check, in both directions** — how many cases pass it, how many
  demonstrate it firing. A check under three demonstrations is named rather than
  averaged away.
- **Nine narration cases**, chosen from the coverage table: a citation past the
  end of a real file and one to a sibling, a verdict in the passive voice, an
  invented critical and an escalated severity, two criticals with one mentioned
  and a severe finding implied but never named, a review cut to one section and
  one whose sections are all renamed.
- **`evaluate --narration --live`** grades what the configured reviewer produces
  now. Opt-in; the default suite never calls a model, asserted by a test.
- **`--write-baseline` and `--compare-baseline`.** A baseline carries the model
  and prompt fingerprint that produced it; a comparison reports per-check
  movement and refuses two different case sets.

### Changed

- **The floor is applied to the interval's lower bound.** The gate is strictly
  harder, and the committed floors are 0.70 (analyzers), 0.60 (documentation)
  and 0.95 (narration) — the most those samples support. A later level that adds
  cases earns the higher numbers.
- A dataset that measures nothing no longer clears every floor by dividing
  nothing by nothing.
- The narration corpus README, the analyzer baseline and the run identity all
  quote the interval rather than the bare score.

### Fixed

- The narration exit code compared the point estimate while the rendered verdict
  compared the bound, so a report could say BELOW THE FLOOR and exit zero.

---

## [2.18.1] — 2026-08-10

The self-review of Level 24, and its four findings closed. Recorded in
[`docs/roadmap/self-review-24.md`](docs/roadmap/self-review-24.md).

The level's argument was "we say exactly what this buys and no more". Twice
that sentence was untrue, and the review found it by running the attacks rather
than by reading the claims.

### Fixed

- **A signed store could be truncated at the tail and still verified.** Five
  records, the last three deleted: every remaining link correct, every remaining
  signature valid, because nothing said how long the store should be — and the
  record somebody wants gone is usually the most recent. Each record now carries
  its position, verification reports where the store ends, and
  `verify --expect-at-least N` compares against a count kept outside the file.
  Truncation still cannot be *detected* from the file alone, and the README, the
  ADR and the spec now say so instead of claiming otherwise.
- **An unsigned chain detected nothing an attacker with the tool does.** The
  digest takes no key, so editing a line and recomputing every seal produced a
  store that verified. The verifier now states this on every unsigned answer;
  the code used to call it "the cheaper guarantee" without saying cheaper than
  what.
- **An undated record was destroyed by every age-based erasure.** `"" >= before`
  is false, so a record with no `recorded_at` fell through every guard and
  matched. What cannot be dated cannot be aged out; it can still be erased by
  name.
- **Timestamps were compared as strings.** `2026-06-01T05:00:00+03:00` is 02:00Z
  and sorted after a 03:00Z cutoff, so it survived an erasure it was two hours
  older than — any runner outside UTC was exposed, and an erasure request that
  leaves data in place is the failure with a legal consequence attached. Compared
  as instants now, and a cutoff that cannot be read refuses the whole operation.

---

## [2.18.0] — 2026-08-10

Level 24 — a record somebody else can check. Recorded in
[`docs/roadmap/level-24/spec.md`](docs/roadmap/level-24/spec.md) and
[ADR 0026](docs/adr/0026-detection-rather-than-prevention.md).

Level 20 wrote the decision record and refused three things in the same
document. Each refusal was right about the thing it named and wrong about the
thing beside it: a record that cannot hold a key can still be **signable**, a
control mapping is not an **obligation**, and a deletion mechanism is not a
**retention policy**.

**What this buys, stated plainly:** an operator holding the key *and* the store
can forge anything. What a chain and a signature buy is that the cheap tampers —
edit one line, delete one line, swap two — stop being invisible. Those are the
tampers an ordinary mistake and an ordinary insider produce.

### Added

- **A sealed store.** Each record names the digest of the one before it and
  its own position, so an edited, removed or reordered line is detectable.
  `--audit-path` writes one now.
- **Signing with a key this repository never produces.** No generated key, no
  bundled key, no fallback to something weaker: `REVIEW_AUDIT_KEY` or nothing is
  signed. A key that is present but too short produces no signer, and neither
  case stops the process.
- **A verifier that answers with a position.** `ai-code-review-audit verify`
  reports the first failing record and whether the *digest* disagreed (the line
  was edited) or the *link* did (one was removed, inserted or moved).
- **Three states, not two.** `unverifiable` — unsigned, partly signed, or signed
  with no key available — is distinguished from `tampered`. Conflating them is
  how a verifier gets turned off before it ever sees a real tamper.
- **A control mapping as data.** NIST SP 800-53 Rev. 5 ships as a replaceable
  YAML file naming its publisher and revision. The rendering says what a run is
  *evidence of*; a test asserts it never says "compliant" or "certified", and
  controls with **no** evidence are listed rather than omitted.
- **Erasure and redaction.** `audit erase` and `audit redact` rewrite and
  re-sign the chain so the store still verifies, leaving a **tombstone** at each
  removed position with the time and the policy. A store that did not verify
  beforehand is refused: rewriting it would re-seal somebody else's alteration.

### Changed

- `NullSigner` lives beside the `Signer` port, the way `NullTracer` sits beside
  `Tracer`.

### Notes

Nothing in this level can fail a review. A signer that raises writes the record
unsigned; a store that cannot be written loses the record and logs it. And
nothing erases by itself — a test parses the review path and asserts it does not
import the erasure module at all.

---

## [2.17.1] — 2026-08-10

The self-review of Level 23, and its six findings closed. Recorded in
[`docs/roadmap/self-review-23.md`](docs/roadmap/self-review-23.md).

### Fixed

- **The retrieved tier returned nothing at all.** Documents and code shared one
  index — 4 205 code chunks against 1 129 document chunks — and the retrieval
  limit was spent before the service's document filter ran. Measured: 0
  documents in the top 20 for a realistic diff. Documents now have their own
  index, built by the same retrieval implementation.
- **The shape test cancelled the diff's proof.** A bare lowercase name was
  refused even when the change had just deleted its definition, making 113 of
  648 indexed functions (17 %) unreportable — `add`, `analyze`, `bind`,
  `cases`, `covers`. A name the change removed is now read whatever its shape;
  everywhere the diff proves nothing the shape test still applies.
- **A deleted file removed nothing.** `is_deleted` changes were filtered out
  before the documentation tier saw them, so deleting the module a document
  describes — the plainest way to make it stale — produced no findings. The
  comment is also rendered for documentation findings alone, since such a merge
  request has no per-file section.
- **`Raises:` on an abstract method was reported.** One false positive in the
  three findings the rule produced against its own repository, on the file where
  this project declares its ports. A body that does nothing cannot contradict
  anything. The other two findings were real and are fixed; a test holds this
  repository at zero.
- **`corpus.py` had the path defect Level 23 fixed in its own copy.**
  `collect_chunks('code_reviewer')` returned 0 chunks; retrieval has been
  silently dead since Level 13 for any relative root other than `.`.
- **The documentation block was unbounded** and sits above the per-file
  reviews, so a change removing a widely documented symbol truncated the
  reviews it was reporting on. Ten locations per tier, then a count.

---

## [2.17.0] — 2026-08-10

Level 23 — documentation checked against the code it describes. Recorded in
[`docs/roadmap/level-23/spec.md`](docs/roadmap/level-23/spec.md) and
[ADR 0025](docs/adr/0025-two-tiers-and-the-weaker-one-is-a-separate-namespace.md).

The roadmap has required since Level 0 that documentation may never claim
behaviour the code does not have. Nothing enforced it: the analysis suite reads
Python and skips Markdown. The reason it earns a level is that **prose outranks
code in a reader's head and outranks it completely in a model's** — an agent
answering a question about a repository reads the README first, and believes it.

### Added

- **`DOCS.*` — what a change proves about the documentation.** Five rules: a
  document naming a symbol the change removed, a documented signature the code
  does not have, an option or environment name the change deleted, a fenced
  Python example that does not parse, and a docstring whose `Args`, `Raises` or
  `Returns` section its function contradicts.
- **`DRIFT.POSSIBLE_STALE_SECTION` — what no token match reaches.** Documents
  join the retrieval corpus; the changed diff is the query; a model is asked one
  narrow question about each retrieved section and answers with one of three
  words. This is the tier that finds the paragraph describing behaviour the
  change altered without naming a single symbol.
- **The two are separated everywhere.** Two report blocks, the second labelled
  unverified. Two namespaces in the attribution table — `DOCS` an analyzer,
  `DRIFT` an agent — which is the *entire* implementation of "a retrieved
  candidate can never block": ADR 0022 already refuses a blocking verdict citing
  a non-deterministic producer.
- **A corpus and a floor.** Thirteen cases under `evaluation/documentation`,
  graded by the analyzers' own scoring, precision/recall/F1 ≥ 0.95. Seven of
  them expect nothing. `evaluate --documentation` runs them.
- **`--no-documentation`** turns the whole check off.

### Changed

- One LLM provider per run, shared by the narrator and the drift judge. Two
  meant two connections, two budgets, and two answers to "which model produced
  this review".

### Fixed

- `Workspace` resolves paths against its root, so building an index from a
  *relative* root walked relatively produced `pkg/pkg/app.py`, every read was
  refused, and the result was an empty index — indistinguishable from a
  repository containing no Python.

### Notes

Nothing this level produces can block a merge. Both tiers emit at or below
`Severity.LOW`, because the rules are newly measured and this project's rule
since Level 12 is that a floor is earned by the level that measured one.

The first implementation of the deterministic tier resolved every backtick in
every document and reported twenty-five findings in this repository's README, of
which nearly all were wrong — `hashlib.md5` is a library call, `ConfigMap` is a
Kubernetes noun, `--cov` is pytest's. Every rule is now scoped to what the diff
proves, which is what makes it a fact rather than a resemblance.

---

## [2.16.1] — 2026-08-09

The self-review of levels 21 and 22, and its six findings closed. Recorded in
[`docs/roadmap/self-review-21-22.md`](docs/roadmap/self-review-21-22.md).

### Fixed

- **The verdict check caught three phrasings of eight.** "This blocks the
  pipeline", "this merge request is blocked", "LGTM, approved", "the pipeline
  will be blocked by this" and "do not merge" all passed the check that makes
  ADR 0004 measurable in the text. Twelve phrasings are caught now, and seven
  statements of fact are deliberately left alone (S-01).
- **The severity check fired on ordinary English.** "The function has high
  complexity" failed a review that said nothing wrong; a claim is now the word
  shouted, labelled, or parenthesised after a finding (S-04).
- **Suggestions were proposed on lines the merge request never touched.** A
  note cannot be anchored outside the diff, so the platform rejected them and
  the rejection was a warning nobody reads. `domain/diffs.py` reads the hunk
  headers, and an unreadable diff proposes nothing (S-02).
- **Suggestions had no idempotency.** Four pushes left four identical buttons
  on one line — the defect Level 5 fixed for the review comment, reintroduced
  beside it. The note now carries a marker keyed on its location (S-03).
- **`--json` was accepted with `--narration` and ignored.** It writes the
  summary now, naming the stale cases rather than counting them (S-05).
- **A batch of findings from two files no longer picks a subject by list
  order** (S-06).

---

## [2.16.0] — 2026-08-09

Level 22: the reviewer proposes a fix, and provably cannot apply one.

### Added

- **`domain/remediation.py` and `domain/fix_recipes.py`.** A `Suggestion` is a
  replacement for a bounded range of lines in one file, produced by a named
  recipe. Three recipes ship — `md5`/`sha1` → `sha256`, `yaml.load` →
  `yaml.safe_load`, a hardcoded literal → `os.environ[...]` — each reading the
  line its finding named and declining when its pattern is not there.
- **`application/remediation_service.py`.** A suggestion is applied in memory
  and the result re-parsed before it is published; an agent-produced finding
  never yields one; two findings on one line yield at most one.
- **`publish_suggestion` on the forge port**, implemented as a GitLab
  discussion anchored on the line — the only place the platform will apply a
  `suggestion` block. `MergeRequestRef` gained the three commit SHAs a note
  needs; a merge request without them costs the suggestions and nothing else.
- **Suggestions in the decision record**: rule, location, recipe. Never the
  replacement text.
- `--no-suggestions`, and an architecture test asserting these modules import
  no way to run a command, call nothing that writes, and that the forge port
  gained a way to comment rather than a way to push.
- [ADR 0024](docs/adr/0024-propose-never-apply.md), and C-22 in
  `capability-sources.md`.

### Changed

- `_review_one` split: the path a file takes when it warrants a model is now
  `_analyse_and_review`. The project's own gate reported the original at
  cyclomatic complexity 16 — the sixth time it has blocked its own build.

---

## [2.15.0] — 2026-08-09

Level 21: the model's prose gets a scoreboard, and the roadmap stops claiming
Level 12 already gave it one.

### Added

- **`domain/narration.py`.** Five checks, all pure functions over a case and its
  recorded text: grounded citations, no verdict claimed, severity claims backed
  by findings, critical findings mentioned, required sections present. Each
  failure names the substring that caused it.
- **`application/narration_evaluation.py` and `narration_report.py`.** The
  corpus scored as *agreement with what each case declared*, so a check that
  stops working shows up as a case that suddenly passes.
- **`infrastructure/evaluation/narration_dataset.py`.** A strict loader. A
  recorded review carrying credential-shaped text refuses to load, and the
  refusal does not quote it.
- **`evaluation/narration/`** — fourteen cases, five of them deliberately bad
  and each declaring the check it should break. Authored rather than captured
  from a model endpoint, which the corpus README says in its first paragraph.
- **`ai-code-review-eval --narration`**, `--min-narration`, and
  `EVALUATION_MIN_NARRATION`. Same three exit codes as the analyzer harness.
- An architecture test asserting that nothing in the review path imports the
  grader, and that the evaluation entry point does.
- [ADR 0023](docs/adr/0023-the-prose-is-graded-by-code.md).

### Fixed

- **`capability-sources.md` overstated Level 12.** C-02 and C-03 were recorded
  as closed by it while Level 12's own non-goals said it did not grade the
  model's prose. Both rows now name both levels.

---

## [2.14.1] — 2026-08-09

The self-review of levels 12–20, and its eight findings closed. Recorded in
[`docs/roadmap/self-review-12-20.md`](docs/roadmap/self-review-12-20.md).

### Fixed

- **The drain works under the entry point that is actually deployed.** README
  and ADR 0021 both said `SIGTERM` drains; that was true of
  `python -m code_reviewer.serve` and not of
  `gunicorn code_reviewer.serve:create_app`, which is what the `Dockerfile` and
  the manifest run. `create_app` registers the drain with `atexit` — under
  gunicorn the signals belong to gunicorn (R-01).
- **An analyzer that crashes is named.** The suite caught each analyzer's
  exception and contributed nothing, silently: no log, no line in the comment,
  no field in the record. A security analyzer that crashed on every file
  produced a clean report. Now reported in all three places; the verdict is
  deliberately unchanged (R-02).
- **Every published comment is redacted at the boundary.** The model's prose
  was masked where it is produced; a failure message built from an exception —
  which can carry a URL, a header dump or a response body — was not (R-03).
- **A task collected after the group's deadline is no longer called
  "abandoned".** Four agents were reported as having hung when one did (R-05).
- **A chunked request gets `411` and the reason** rather than "a body is
  required" (R-06).
- **The route table compares its auth kind by value**, not by identity (R-07).
- **`ThreadPoolRunner` refuses a concurrent caller** rather than racing on its
  own pool (R-08).

### Added

- Tests pinning that `--trace-path` reaches the exporter. The wiring was
  correct and nothing asserted it (R-04).

---

## [2.14.0] — 2026-08-09

Level 20: the verdict becomes something that can be audited — and the claim this
architecture has made since Level 4 becomes a control.

### Added

- **`domain/provenance.py`.** `Producer`, `Provenance`, `RunIdentity`,
  `SuppressionRecord`, `AgentCost` and `DecisionRecord`. A record whose verdict
  is blocking and whose blocking findings name a non-deterministic producer is
  **refused at construction**, naming the finding, the producer and
  [ADR 0004](docs/adr/0004-findings-drive-the-gate.md).
- **`application/governance.py`.** The `AuditSink` port, the rule-namespace
  attribution table and `DecisionRecorder`. Attribution is fail-closed: an
  unregistered namespace is an agent, and therefore unable to block. A test
  asserts every namespace the analysis suite emits is registered and that none
  of its findings carries an empty rule id.
- **`infrastructure/governance/`.** `build_run_identity` — package, policy,
  model, rule set, evaluation baseline and a 12-character `blake2b` digest of
  the five system prompts in use — and `JsonAuditSink`, which appends
  newline-delimited JSON.
- **`--audit-path` / `REVIEW_AUDIT_PATH`.** Without it nothing is written. The
  environment variable is what lets the HTTP service record what the command
  line records, since a container is configured with variables.
- **An accountability block in the merge-request comment**: the versions, the
  model, the prompt digest, the measured accuracy of the analyzers, and the
  sentence naming what decided. Absent rather than half-filled when there is no
  identity.
- **Per-agent cost in the record** — runs, failures, tool calls, tokens allowed
  and duration per specialism, alongside the decision they paid for. The
  metrics file is overwritten by the next review; the record is not.
- [ADR 0022](docs/adr/0022-a-verdict-that-can-be-audited.md).

### Changed

- The exit code is computed before the comment is rendered, because the record
  names it and the comment quotes the record. The value is unchanged: it is a
  function of the outcome and the policy.
- `tests/unit/test_evaluation_baseline.py` now pins the baseline string the
  record carries against the floors it claims, so the two cannot drift.
- `reports/` is git-ignored. The per-level reports are written for the reader
  of a level, not for the history.

### Not done, deliberately

- **No signing, and no append-only store.** Integrity against a hostile
  operator needs a key nobody in this repository holds. `AuditSink` is a port
  so a deployment that needs one has somewhere to put it.
- **No compliance mapping.** No control catalogue, no attestation format —
  those are an organisation's, and inventing one here would be guessing at
  somebody else's obligations.
- **No explanation of the model's reasoning.** "Why did the model conclude
  that" is not answerable, and a plausible-sounding answer to it is
  manufactured evidence.

---

## [2.13.0] — 2026-08-09

Level 19: the review becomes something that can be deployed.

### Added

- **A multi-stage `Dockerfile`.** The runtime carries the virtual environment,
  the package and `git`; no compiler, no `uv`, no source tree, no `.git`. Runs
  as uid `10001` under `gunicorn`.
- **Kubernetes manifests** — namespace, `ConfigMap` with a comment per key, an
  example `Secret` whose values are placeholders, a deployment and a service.
  Requests and limits, `runAsNonRoot`, `allowPrivilegeEscalation: false`,
  `readOnlyRootFilesystem`, all capabilities dropped, and writable mounts
  declared because a read-only root needs them.
- **`tests/unit/test_deployment_manifests.py`.** Both files parsed and every
  claim asserted, including the probe paths against `ReviewApi.ROUTES` and
  `terminationGracePeriodSeconds` against the configured drain bound.
- **`domain/health.py` and `application/health.py`.** Readiness as named
  checks: every failure reported at once, in a stable order, each isolated so a
  check that raises fails only itself.
- **`infrastructure/deployment/settings.py`.** The checks a container answers
  `/readyz` from — the forge token, the model endpoint, a policy that loads, a
  workspace that exists. A reason names the setting, never its value.
- **`SIGTERM` and `SIGINT` drain.** The server stops, the review in flight gets
  `--drain-seconds`, and the log says which of "finished" and "gave up"
  happened.
- `gunicorn` as an optional `serve` extra, and in the dev group so the lock
  file pins it and the audit sees it.
- A `docker build` step in CI.

### Changed

- `/readyz` no longer returns `(True, "ready")` from a lambda. A container
  wired to a probe that always passes is worse than one with no probe at all.

### Not shipped, deliberately

No Helm chart — six plain manifests a reader can read; a chart earns itself
when environments genuinely differ. No `HorizontalPodAutoscaler` — the queue is
in memory, two replicas do not share it, and shipping one would be a bug
delivered as configuration. No ingress and no TLS termination in the
application.

### Documented

- [ADR 0021](docs/adr/0021-a-deployment-that-is-tested.md) — why the manifests
  are tested, why readiness is an object, why one replica, and why a drain is
  bounded.

---

## [2.12.0] — 2026-08-09

Level 18: the review becomes something callable.

### Added

- **Six endpoints.** `POST /reviews`, `GET /reviews/{id}`,
  `POST /webhooks/gitlab`, `/healthz`, `/readyz`, `/metrics` — a WSGI
  application, not a framework.
- **`domain/job.py`.** A review request's lifecycle: `QUEUED → RUNNING →
  SUCCEEDED | FAILED`, and every other transition refused at the moment it is
  attempted.
- **`JobStore` port**, `InMemoryJobStore` and `JobService`. Find-or-create is
  one critical section: "look, then insert" is the shape that turns two
  simultaneous requests for one commit into two reviews.
- **A worker thread** that claims a job, runs it under its own trace, records
  the verdict, and keeps draining after a failure.
- **`ai-code-review-serve`**, with `create_app()` for gunicorn or uvicorn.
- Idempotency keyed on the head commit, with `Idempotency-Key` honoured;
  a bounded queue answering `429` with `Retry-After`; a body-size cap; and
  authentication asserted over the route table rather than route by route.

### Fixed

- The metrics handler was named `_metrics`, and so was the injected collector.
  `getattr(self, route.handler)` resolved to the field and the endpoint
  returned 500. Found by the route-table test on the first run.

### Not taken, deliberately

FastAPI, for the third framework refusal in this roadmap. It would bring
starlette, pydantic, anyio and a dozen transitive packages into a process whose
dependency audit runs with an empty ignore list, to serve six endpoints whose
bodies have two fields each. WSGI is the interface every Python server speaks,
so the server is a deployment choice; the cost — no generated OpenAPI schema,
hand-written validation — is stated in the ADR.

And a database. Job state is in memory and a restart loses the queue; the store
is a port, so the decision about persistence has somewhere to go.

### Documented

- [ADR 0020](docs/adr/0020-a-wsgi-application-not-a-framework.md) — why WSGI,
  why idempotency is keyed on the commit, why the status endpoint withholds the
  comment, and why readiness does not call GitLab.

---

## [2.11.0] — 2026-08-09

Level 17: the committee stops waiting one at a time.

### Added

- **`TaskRunner` port**, with `TaskOutcome` and `SequentialRunner` beside it.
  Outcomes come back in the order the tasks were given, whatever order they
  finished in; a task's exception is captured into its own outcome and does not
  escape.
- **`ThreadPoolRunner`.** Bounded, ordered, with a group deadline so ten hung
  tasks cost one timeout rather than ten. A pool that abandoned a task is
  marked tainted and replaced.
- **`--concurrency N`.** `1` selects the sequential runner outright, which is
  the behaviour of every level before this one.
- **`Tracer.bind(parent_span_id)`**, and a per-thread stack behind it. A worker
  attaches to the span that submitted its work, captured on the submitting
  thread — a worker's own stack is empty and knows nothing about who queued it.
- **Locks** in the tracer, `Workspace` and `SmartMemoryStrategy`, each with a
  test that runs eight threads at it and checks the result: every span present
  and uniquely identified, the budget spent exactly to its ceiling, no insight
  lost, a duplicate stored once.

### Fixed

- **`PERFORMANCE.MEMORY_LEAK` no longer fires on `threading.Lock()`** (E-03).
  Adding three locks for this level made the agent block its own build, which
  is the rule working and the table being wrong: constructing a lock acquires
  nothing. Fixed rather than suppressed, with a unit test and an evaluation
  case. `acquire` stays — a lock taken and never released is the real defect
  and is a different call.

### Not taken, deliberately

`asyncio`. Every port in this repository would become `async` in order to await
two libraries — `python-gitlab` and LangChain's `ChatOpenAI.invoke` — that are
synchronous anyway. A thread pool behind one small port buys the same wall
clock; an async-native runner arrives as a third adapter if it is ever wanted.

And concurrency across files. `ReviewOutcome`, the metrics, the report sections
and the memory's observations are appended to per file and rendered in order;
making that safe *and* deterministic is its own level.

### Documented

- [ADR 0019](docs/adr/0019-threads-behind-a-port.md) — why threads, why order
  is by plan, why files stay sequential, why a timed-out task is abandoned
  rather than cancelled, and why the parent span is captured at submission.

---

## [2.10.0] — 2026-08-09

Level 16: one review, one trace.

### Added

- **`domain/trace.py`.** Spans, tree building, self time, the critical path.
  Tree building survives an orphan, a two-span cycle, a three-span cycle, a
  span that is its own parent and two roots — each recorded as an *anomaly*
  rather than hidden, and none of them able to make it fail to terminate.
- **`SpanRecorder`** with dotted-counter identifiers (`1.4.2`), so the tree's
  shape is visible in a flat log line and two spans can be compared by eye.
- **`Tracer` and `TraceExporter` ports**, plus a `NullTracer` that is the
  default everywhere — which is what lets the instrumentation be unconditional
  rather than wrapped in `if tracer is not None`.
- **Instrumentation** of the run, each file, static analysis, retrieval, memory
  recall, each agent, each model call and each tool call.
- **Trace context on every log record.** `trace_id` and `span_id` in both the
  human and the JSON format, added by a filter on the handler.
- **`render_trace_tree`** — indented, bounded by depth and node count, stating
  what it omitted, with self time per kind and the anomalies — and
  **`trace_to_json`** behind `JsonTraceExporter`.
- **`--trace-path`.** Recording is always on; writing the file is the flag.

### Changed

- The merge-request comment's footer names the trace id. The tree itself is
  not in the comment: it is only complete *after* the comment has been
  rendered. The spec said otherwise, and implementation disagreed — recorded
  in the ADR rather than quietly done.
- `application/tracing.py` exists because the architecture test refused the
  first attempt: `ReviewService` had imported the recorder from
  `infrastructure` directly.

### Not taken, deliberately

OpenTelemetry. It is the industry answer and this level does not take it: the
SDK plus an exporter is a large dependency tree in a process whose entire job
is to be trustworthy, and Level 7 already spent itself on what a framework in
the critical path costs. `TraceExporter` is a port precisely so this can be
reversed without the review path changing.

### Documented

- [ADR 0018](docs/adr/0018-a-trace-of-our-own.md) — why not OTel, why the model
  is in the domain, why identifiers are counters, and why attributes are a
  closed vocabulary enforced by a test rather than by advice.

---

## [2.9.0] — 2026-08-09

Level 15: one reviewer becomes four.

### ⚠️ Breaking

| Change | What to do |
|---|---|
| `Reviewer.review_diff` takes a `ReviewBrief`, not seven parameters | Read the fields off the brief. It had grown one parameter per level, and seven is past the threshold this project's own quality analyzer enforces. The next thing a reviewer needs is now a field rather than a signature change. |

### Added

- **Four specialists.** Architecture (the generalist, which owns the summary),
  security, performance and dependency — each with its own system prompt, its
  own tool catalogue and its own share of the budget.
- **`domain/orchestration.py`.** Routing from findings, a weighted budget split
  that sums exactly and gives nobody zero, a fixed composition order, and the
  handoff rule. All pure: the failure mode of a multi-agent system is that
  nobody can say what it will do, and every one of those questions is answered
  here by reading a page.
- **`ReviewOrchestrator`**, which *is* a `Reviewer`. The workflow never learns
  there is more than one agent.
- **A handoff protocol.** One specialist may ask for one other, once, with a
  written reason. The depth is structural — the second round runs at a depth
  where the domain refuses everything — so the invocation count for one file
  cannot exceed twice the number of specialisms whatever a model asks for.
  Refusals are recorded and reported.
- **Per-agent accounting.** `code_review_agent_runs`,
  `code_review_agent_failures` and `code_review_agent_tool_calls`, labelled by
  agent, plus a per-file footer naming who ran, on what budget, with what
  outcome.
- **`--single-agent`**, which reproduces the behaviour of every earlier level.
- `NarrationLoop` counts its tool calls; `ReviewAgent` accepts a narrowed
  catalogue, its own system template and an iteration cap.

### Not changed, deliberately

The verdict. The analyzers still run unconditionally before any agent and the
gate still decides from their findings: four narrators change what the report
says, not what the pipeline does.

And no framework, and no concurrency. Level 7 removed a framework from the
critical path for reasons that have not expired; concurrency belongs to Level
17, after Level 16 makes the whole thing traceable — introducing it here would
make every bug in this level a race.

### Documented

- [ADR 0017](docs/adr/0017-an-orchestrator-of-specialists-not-a-framework.md) —
  why the orchestrator is a `Reviewer`, why routing is not a model call, why
  handoff depth is structural, and why tools are narrowed rather than
  requested.

---

## [2.8.0] — 2026-08-09

Level 14: the agent stops starting from zero.

### Added

- **A memory of each project.** `.review-memory.json` in the checkout records
  what each rule has done in each file: how many times, since when, and — for a
  `review-ignore` — the reason somebody wrote. `--memory-path` moves it,
  `--no-memory` turns it off.
- **`domain/recollection.py`.** Identity (kind, path, rule — not line, not
  severity), consolidation, salience with a 30-day half-life, a forgetting
  floor, a capacity, and recall scoped to a file and then its directory.
- **`MemoryStore` port** and `JsonMemoryStore`: written to a temporary file and
  renamed, so a run killed mid-write leaves the previous memory rather than a
  truncated one. A corrupt file loads as empty, is logged, and is left on disk.
- **Recall in the prompt**, inside `<untrusted_project_memory>`, as a table of
  identifiers and counts.
- **Recurrence in the report**: findings this project has reported before, with
  the count and the date first seen.
- **`code_review_recurring_findings`** in the metrics export.

### Changed

- `Reviewer.review_diff` takes a `recollections` argument, defaulting to
  `None`.
- `ReviewService` takes an optional `memory`. It recalls before the review,
  observes after it, and persists once the comment has already been rendered.
- `render_review_comment` was split into one builder per block — the agent
  reported it at cyclomatic complexity 17 against its own source when the
  recurrence section was added, which was fair.

### Not changed, deliberately

The verdict. No recollection touches a severity, a gate result or an exit code,
and `TestMemoryNeverDecides` runs the same review twice — against a history of
99 sightings of exactly the finding it is about to report, and against none —
requiring both to be identical. The tempting feature is a tool learning to stop
complaining.

Nor is anything a contributor wrote ever stored. Rule ids, paths, severities,
dates and counts, plus a suppression's own source comment. An evidence line in
a memory file is a stored injection with a long half-life and a credential
store nobody declared.

### Documented

- [ADR 0016](docs/adr/0016-memory-informs-and-never-decides.md) — what the
  history may do, what it may contain, how it is found, and why it is a keyed
  store rather than a second index.

---

## [2.7.0] — 2026-08-09

Level 13: the reviewer stops seeing only the diff, and the Level 12 harness
gets spent on the two things it found.

### Added

- **Retrieval over the checkout.** The repository is chunked by syntax tree —
  every function, class and method, with overlapping line windows as the
  fallback — and indexed twice: BM25 over tokenised identifiers, and cosine
  over embeddings.
- **Rank fusion and diversification.** `domain/retrieval.py` holds
  `reciprocal_rank_fusion`, `maximal_marginal_relevance` and
  `cosine_similarity`. Fusion by rank rather than by score, because BM25's
  scale depends on the corpus and cosine's does not.
- **Four ports.** `EmbeddingModel`, `LexicalIndex`, `VectorIndex` and
  `CodeRetriever`. The shipped adapters — `HashingEmbedding`, `BM25Index`,
  `InMemoryVectorIndex`, `HybridRetriever` — need no weights, no network and
  no server.
- **Retrieved code in the prompt**, inside `<untrusted_repository_context>`
  with both tag forms escaped, each chunk under its `path:line-line` citation.
- **`search_related_code`**, so the agent can ask its own question. Without an
  index it says so rather than reporting no results.
- **A measurement of the retriever**, scored with the same `ConfusionMatrix`
  the findings harness uses: at a cutoff of two over eleven queries the
  lexical half answers 8, the dense half 8, and the fusion 9. Two paraphrase
  queries are missed by everything, and there is a test asserting that — it is
  what swapping in a trained embedding would buy.

### Fixed

- **`SAST.SQL_INJECTION` follows an assignment** (E-01). The pattern matched
  `execute(...+` on one line; nobody writes it there. An AST pass now reports a
  query built by concatenation, `%`, `.format()` or an f-string into a local
  and later executed — at the line where the string was built, which is the
  line someone has to change.
- **`SEMANTIC.UNREFERENCED_IN_FILE` narrowed to private names** (E-02). A
  public function is called from outside its module, so "not referenced in this
  file" was the normal state of every public API. A single leading underscore
  is the case where one file *is* the whole of the evidence.

### Changed

- `Reviewer.review_diff` takes a `related` argument, defaulting to `None`.
- `ReviewService` takes an optional `retriever`. Retrieval never blocks: an
  index that cannot be built costs the prompt its context and nothing else.
- The evaluation dataset grows to ten cases and the CI floors rise from
  0.95 / 0.85 / 0.90 to **0.95 / 0.95 / 0.95** — precision, recall and F1 are
  all 1.00.
- `search_related_code` lives in `tools/retrieval_tools.py`, not
  `tools/definitions.py`: adding it to that file took its quality score below
  the gate's threshold, and the agent reported it against its own source.

### Documented

- [ADR 0015](docs/adr/0015-retrieval-is-hybrid-local-and-untrusted.md) — rank
  fusion over score fusion, a hashed embedding behind a port, brute force over
  ANN, and why retrieved code is untrusted and best-effort.

---

## [2.6.0] — 2026-08-09

Level 12: the first level of a second roadmap, sourced from three published
role descriptions for agentic AI work in a regulated bank rather than from the
findings inventory, which is closed. It comes first because everything after it
changes what the agent *says*, and nothing measured that.

### Added

- **Evaluation harness.** `ai-code-review-eval` grades the analysis suite
  against annotated cases and reports precision, recall and F1 — overall and
  per rule — as markdown and as JSON.
- **`domain/evaluation.py`.** One-to-one matching of produced findings against
  expectations, a confusion matrix, per-rule aggregation and a threshold.
  A severity mismatch is a miss and consumes the finding; a rule fired outside
  the tolerance is charged both ways.
- **A dataset, not a fixture set.** `evaluation/cases/*.yaml` beside
  `evaluation/fixtures/`, loaded by `FileSystemDataset`. The loader refuses an
  unknown key, a missing line, an unparseable severity, a fixture outside the
  dataset root and two cases sharing a name.
- **Ungraded findings are counted.** A case may narrow its scope; what falls
  outside is reported with its rule ids rather than dropped, so narrowing
  cannot quietly improve a score.
- **`expect_absent`.** Where a fixed false positive is pinned. The `dict.get`
  N+1 and the `overrides(` DES match from Level 11 are both pinned.
- **A CI gate.** `evaluate` on GitLab and a step on GitHub, at precision 0.95,
  recall 0.85, F1 0.90 — the measured baseline minus a margin — publishing the
  JSON summary as an artefact.
- **`EvaluationDataset` port** and the `CaseFixture` value object.

### Documented

- [ADR 0014](docs/adr/0014-evaluation-is-a-dataset-not-a-fixture.md) — why the
  dataset is data on disk, why scope defaults to everything, and why the floors
  are measured rather than aspired to.
- [`docs/roadmap/capability-sources.md`](docs/roadmap/capability-sources.md) —
  twenty capabilities the role descriptions name, what this repository does
  about each, and which of levels 12–20 closes it.
- [`docs/roadmap/level-12/baseline.md`](docs/roadmap/level-12/baseline.md) —
  the measured baseline, and the two things the instrument found on its first
  run.

### Known

The dataset ships with one false negative recorded as ground truth:
`SAST.SQL_INJECTION` is a single-line pattern and misses a query concatenated
into a local before being executed. That is the whole of the recall gap, and
closing it is Level 13's work, not this level's.

---

## [2.5.0] — 2026-08-08

Level 11: what happens when the agent is wrong, and whether it holds against
real code rather than fixtures.

### ⚠️ Breaking

| Change | What to do |
|---|---|
| `StaticAnalysis.analyze` returns a `SuppressionResult`, not `list[Finding]` | Read `.findings`. The result also carries `.suppressed`, which is the point: a silenced rule and an inert rule looked identical before. |
| `StaticAnalysisSuite` and `ReviewAgent` now inherit their ports | Nothing. They always implemented them; nothing checked. |
| `configure_logging` — see 2.4.0 | — |

### Added

- **Suppression.** `# review-ignore: RULE - reason` on a line or the line
  after a standalone comment, `# review-ignore-file:` for a whole file,
  namespace globs (`SAST.*`). A bare `*` is refused. The report states how
  many findings were suppressed, where and why, naming any without a reason.
- **Dogfooding.** `tests/unit/test_dogfooding.py` runs the analyzers over
  this package on every push and asserts no CRITICAL and no HIGH, with a cap
  on suppressions and a reason required for each.
- **Property-based tests.** `hypothesis` generates diff-shaped input; triage,
  the semantic analyzer and the suppression parser must not raise on any of it.
- `mypy` now covers the whole package, and `ruff` selects the `S`
  (flake8-bandit) family.

### Fixed

Found by running the analyzers against this codebase for the first time —
none of these is specific to it:

- The N+1 rule matched `.get(` on the method name alone, so every
  `dict.get()` inside a loop was a database round trip. Ambiguous names now
  require a receiver that means I/O.
- A chained call (`session.query(M).filter(...).first()`) was reported once
  per AST node on the line.
- `DES\s*\(` matched case-insensitively with no word boundary, so
  `ast.iter_child_nodes(` was DES encryption.
- Eight `except ...: pass` handlers discarded the reason; each now logs it.
- Three functions at cyclomatic complexity 21, 17 and 16 are split.

Found by turning on `ruff`'s `S` family:

- `DependencyTracker` built its own `grep` command with no `--`, no `-F` and
  no exclusion of credential files — the same three defects Level 8 fixed in
  the tool module, in a second call site reachable from an agent tool whose
  symbol comes from the diff.

Found by widening `mypy`:

- An Optional `risk_score` used unconditionally, `end_lineno` guarded by
  `hasattr` (which does not narrow `Optional`), and a `DependencyType | None`
  used as a dict key.

## [2.4.0] — 2026-08-08

Level 10: nothing here changes what the agent decides; all of it changes
whether a team can live with the agent that decides it.

### ⚠️ Breaking

| Change | What to do |
|---|---|
| A crash now exits `3`, not `1` | `1` means the gate blocked, and nothing else. A pipeline treating `1` as "the agent broke" needs updating — the previous meaning was ambiguous, which is the finding. |
| A configuration error exits `2` | Already true for missing credentials; now also for an unloadable policy. |
| `configure_logging()` takes `level` as its first argument | It was `stream`. `configure_logging(stream=...)` still works by keyword. |
| `MissingCredentialsError` and `PolicyLoadError` are now `ConfigurationError` subclasses | Nothing, unless you caught them by their old base (`RuntimeError`, `Exception`). |
| Repeated runs update one comment instead of posting a new one | Nothing. The agent edits only a note carrying its own marker; human replies are untouched. |

### Added

- `--dry-run`: runs the whole review and prints the report instead of posting
  it, keeping the real exit code.
- `--no-llm`: static analysis only, with no model endpoint constructed at all.
  The verdict is unchanged — it has never come from the model.
- `--repo-root`, `--metrics-path`, `--log-level`, each with an environment
  fallback.
- `REVIEW_MAX_COMMENT_CHARS` (default 900 000): the report is truncated
  head-first with a notice rather than rejected by the platform.
- `code_reviewer.errors`: `ReviewError`, `ConfigurationError`, `ForgeError`,
  `ReviewAgentError`.
- `ReviewService.review(..., publish=False)`.

### Fixed

- Five pipeline runs left five reports, with the oldest at the top of the
  thread (G-12).
- A review of many files produced a body GitLab rejects, so the merge request
  showed nothing at all (G-19).
- `configure_logging("DEBUG")` would have passed the string as the output
  stream — found by replacing a mocked assertion with a real call.

## [2.3.0] — 2026-08-08

Level 9: four places where the code met something it did not understand and
answered "fine, then". All four pointed towards approval.

### ⚠️ Breaking

| Change | What to do |
|---|---|
| An unrecognised policy section, key, or wrongly typed value now raises `PolicyLoadError` at startup | Fix the key. The message names the file, the key and what would have worked. This is the point: `block_on_critcal: false` used to leave the rule on under a name you thought you had turned off. |
| `--policy` naming a file that does not exist now raises | It used to fall through to the packaged policy, running rules nobody asked for. |
| A policy file that does not parse now raises | Same reasoning. |
| A file whose static analysis could not run now **fails the pipeline** | Set `gate.fail_pipeline_on_analysis_error: false` to keep the old behaviour. The file is still reported as unanalysed either way. |
| Lock files (`uv.lock`, `package-lock.json`, `go.sum`, …) are no longer skipped, and reach `FULL_REVIEW` | Put them back in your own `skip_patterns` if the cost outweighs the coverage. A lock file is the only place a changed transitive dependency is visible. |
| `requirements*.txt` no longer matches the `.txt` documentation skip | Nothing; it is a dependency manifest. |
| Manifests and CI definitions reach `FULL_REVIEW` regardless of diff size | Nothing, unless you were relying on a one-line CI change being auto-approved. |
| `Finding` is frozen; `metrics` is an immutable mapping | Construct a new one instead of mutating. Reading is unchanged. |
| Rule ids are namespaced: `SAST.SQL_INJECTION`, not `sql_injection` | Update anything matching on them. |

### Added

- `gate.fail_pipeline_on_analysis_error` (default `true`).
- `triage.manifest_patterns`, and `DEFAULT_MANIFEST_PATTERNS` covering
  dependency manifests, lock files, container definitions and CI configuration.
- `ReviewOutcome.record_unanalysed`, and a **Not analysed** section in the
  published comment stating that absent findings there mean nothing was
  examined.
- `Finding.namespace`, and `StaticAnalysisSuite.deduplicate`.

### Fixed

- Two detectors reporting one problem at one line under one rule produced two
  findings, inflating the per-severity counts the metrics export and the
  quality score are computed from (G-08).
- A crashed analyzer produced an empty list, indistinguishable from a clean
  file (G-09).
- An unrecognised policy key was logged and ignored (G-10).
- A three-line change to a CI definition was auto-approved: the logic-change
  guard looks for `if`/`for`/`def`, which no YAML line contains (G-11).
- The last Turkish comments in `domain/triage.py`, which the language guard
  misses because they carry no Turkish-specific characters (ADR 0008).

## [2.2.0] — 2026-08-08

Level 8: the reviewed content is treated as hostile input, which is what it is.

### ⚠️ Breaking

| Change | What to do |
|---|---|
| Files named `.env`, `.env.*`, `.netrc`, `.npmrc`, `.pypirc`, `credentials`, `id_rsa`/`id_*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, and anything under `.git/`, are no longer readable by the agent | Nothing, unless a review legitimately needed one. `.env.example` is caught by the glob; that trade is deliberate. |
| `grep_search` refuses a pattern with a leading `-`, control characters, `..`, or shell metacharacters, and treats the pattern as a fixed string | Regular-expression searches no longer work. They never worked *correctly* — the pattern was a BRE by accident. |
| A refused file access fails the pipeline | It is a `CRITICAL` finding, so `gate.blocking_severity` governs it like any other. |
| `ReviewService` gained an `access_auditor` argument | Optional; omitting it keeps the previous behaviour. |

### Added

- A trust boundary: the diff and file content are delimited by
  `<untrusted_diff>` / `<untrusted_file_content>`, escaped so the content
  cannot close its own tag, with a trust-boundary section at the top of the
  system prompt.
- Secret redaction before publishing, in two layers: the values of the
  secret-bearing environment variables this process holds, then known secret
  shapes.
- A per-review read budget (`WORKSPACE_TOTAL_READ_BUDGET`, default 20 MB) and
  a settable per-file cap (`WORKSPACE_MAX_FILE_BYTES`).
- An audit log of every file-access attempt, and an `AccessAuditor` port that
  carries the refusals to the workflow.
- `code_reviewer.infrastructure.security` and
  `code_reviewer.infrastructure.tools.safe_search`.

### Fixed

- A path containing a NUL byte made `Path.resolve()` raise `ValueError`, which
  escaped the workspace's own error contract: the access was neither refused
  nor recorded (G-05).
- `list_files` and `find_file` walked the tree themselves, so the deny-list did
  not apply to discovery. Locating a credential file is the first half of
  reading one (G-05).

## [2.1.0] — 2026-08-08

Level 7: the agent's tool loop moved into this repository, which unblocked the
LangChain upgrade that had been deferred since Level 5, and the dependency
audit that measures it.

### ⚠️ Breaking

| Change | What to do |
|---|---|
| `HermesToolOutputParser` and `format_to_hermes_messages` removed from `infrastructure.llm.review_agent` | Use `infrastructure.llm.tool_calls.ToolCallParser`, which reads both protocols. The old parser matched one `<parameter=>` block and mangled two-argument calls. |
| `ReviewAgent.agent_executor` removed | The loop is `ReviewAgent.loop`, a `NarrationLoop`. |
| `ReviewAgent(verbose=...)` removed | Verbosity is a logging concern; set `LOG_LEVEL=DEBUG`. |
| `langchain-community` no longer a dependency | Nothing, unless you imported it through this package. LangChain 1.x does not require it. |
| LangChain `0.1.x` → `>=1.3.9`, `openai` `1.12` → `>=2.26`, `python-gitlab` `4.4` → `>=4.13,<6` | Nothing in this project's API changed. Exact pins became ranges; `uv.lock` is what pins CI. |

### Added

- `REVIEW_TOOL_PROTOCOL` — `auto` (default), `native`, `hermes` or `none`,
  deciding how tools are offered to the model. An unrecognised value raises at
  startup rather than silently producing a tool-less review.
- `REVIEW_MAX_ITERATIONS` and `REVIEW_MAX_SECONDS` — the loop's bounds. The time
  budget is **off by default**: an analysis cut off part-way produces an
  incomplete report that does not say so.
- `scripts/audit-deps.sh` and a CI step, distinguishing a real advisory from a
  network failure so the step can block without being a coin flip.
- `tests/unit/test_dependencies.py` — no banned distribution reappears, and
  every third-party import the package makes is declared.

### Fixed

- Tools are now bound natively, so a hosted endpoint (OpenAI, Groq) can actually
  call one. Previously the model was offered no tool schema and narrated as
  though it had run the scans (G-02).
- A multi-argument tool call keeps every argument. The old parser folded the
  second `<parameter=>` block's raw XML into the first argument's value (G-02).
- 59 known dependency advisories across 11 packages → **none**, with an empty
  ignore list (G-01, G-15).

## [2.0.0] — 2026-08-08

A staged rebuild of the imported prototype. Every file was read, 59 findings
were recorded in [`docs/roadmap/findings.md`](docs/roadmap/findings.md), and the
work was sequenced into seven levels, each with a spec written before its plan
and a plan written before its code.

The test suite went from 10 tests over 2 modules to 440 tests at 87 % coverage.

### ⚠️ Breaking

| Change | What to do |
|---|---|
| Import package renamed `openhands` → `code_reviewer` | Update imports. The console command, `ai-code-review`, is unchanged. |
| Licence changed GPL-3.0 → **MIT** | Nothing, unless you relied on copyleft. `LICENSE` shipped the GPL text while README called it MIT; MIT was the stated intent. |
| Entry point moved `openhands.agent.main:main` → `code_reviewer.__main__:main` | Nothing if you use the `ai-code-review` command. |
| Metric fields `security_score`, `performance_score`, `critical_issues`, `high_issues`, `medium_issues` removed | They only ever exported `0`. Use `code_review_findings{severity="..."}` instead. |
| `requires-python` `==3.12.12` → `>=3.12` | Nothing; strictly wider. |
| Default skip patterns no longer exclude `.yaml`, `.json`, `.toml` or `Dockerfile` | Expect deployment configuration to be reviewed. Lock files, documentation, binaries and vendored trees are still skipped. |
| `TriageConfig` removed | Use `ReviewPolicy`. `TriageConfig` was never wired up: passing one silently fell back to two hard-coded patterns. |
| `MemoryStrategy.get_memory_object()` removed | It returned a LangChain object through a port that existed to hide one. |

### Added

- **Static analysis on every reviewed file**, independent of whether the model
  calls a tool, producing the shared `Finding` type.
- **Findings-driven gate**: blocks on findings at or above
  `gate.blocking_severity`, computes the quality score from severity weights,
  and demotes the model's prose to warnings. Every reason names its source.
- **Workspace confinement** for all agent file access, refusing traversal and
  symlinks out of the checkout.
- **Structured logging** with `LOG_LEVEL` and an optional `LOG_FORMAT=json`.
- **Review-wide metrics** in valid OpenMetrics, with `# HELP` and `# TYPE`.
- **Per-file failure isolation**: a file the reviewer cannot process is reported
  as *not reviewed* rather than ending the run.
- **Model timeouts and retries** (`LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`).
- **TLS options** `GITLAB_CA_BUNDLE` and `GITLAB_SSL_VERIFY`.
- **Policy keys** `gate.blocking_severity` and `gate.fail_on_review_error`.
- **CI**: GitHub Actions, a GitLab pipeline that runs this agent on its own
  merge requests, and pre-commit hooks.
- **Documentation**: [ARCHITECTURE](docs/ARCHITECTURE.md), eight
  [decision records](docs/adr/README.md), [SECURITY](SECURITY.md),
  [CONTRIBUTING](CONTRIBUTING.md) and this changelog.

### Fixed

- **The review gate could not block a pipeline.** The orchestrator compared a
  `ReviewGateResult` enum against the string `"fail"`, so the comparison never
  matched and `sys.exit(1)` was dead code. (F-01)
- **The memory context never reached the model.** It was supplied to a prompt
  template that did not declare the variable, so LangChain dropped it. (F-02)
- **The agent's tool loop could not work.** Tools were never described to the
  model, and the scratchpad was formatted as OpenAI function calls while the
  parser read Hermes XML. (F-03)
- **The bundled policy file was never loaded.** Every candidate path was
  relative to the working directory. (F-04)
- **TLS verification was disabled** for every GitLab call, including the one
  carrying the API token. (F-20)
- **A failed SAST scan could not fail the gate.** The check looked for a string
  the prompt never asks the model to produce. (F-57)
- **Triage escalated on unchanged lines**, so a `password` in surrounding
  context forced an expensive review, and deleting an `eval()` call did too.
  (F-09)
- **A missing quality score counted as zero**, so any drift in the model's
  formatting blocked the merge request. (F-10)
- **Severity ordering was alphabetical** — `critical < high < info < low <
  medium` — so truncating a report dropped severe findings. (F-07)
- **String-concatenation-in-loop detection could never fire**: it tested
  membership of a string in a *list*. (F-05)
- **`yaml.load` detection matched safe calls**, because the negative lookahead
  sat after a greedy match. (F-06)
- **Policy thresholds were ignored** by the quality and performance analyzers,
  which read their own constants. (F-31)
- **Loading a policy file crashed the run**: an empty YAML section parses as
  `None`, and the shipped policy ended with one. (F-56)
- **A policy's `version` was never applied**, so every report claimed `1.0`.
  (F-55)
- **The memory strategy monkey-patched the shared chat model**, shadowing the
  tokenizer the agent used for its own budgeting. (F-11)
- **One file's exception discarded the whole run.** (F-58)
- **Four bare `except:` clauses** swallowed every exception including
  `KeyboardInterrupt`. (F-48)
- **A resource assigned to two names reported the same leak twice.** (F-48)
- Plus: implicit `Optional` across eleven signatures, an operator-precedence
  mistake that made a classification branch behave by accident (F-08), an empty
  diff classified as a style change (F-12), `BUGFIX` triggered by the substring
  `fix` inside `prefix` (F-13), and "defined but never called" claimed from
  single-file visibility (F-14).

### Changed

- Restructured into `domain` / `application` / `infrastructure` with a one-way
  dependency rule enforced by a test.
- One `Severity`, one `Finding`, one `AffectedCode` — replacing three severity
  enums and two duplicated models.
- The workflow moved behind a `CodeForge` port and now runs against in-memory
  fakes.
- The source is in English throughout; comments were re-derived against the
  code rather than translated, because several described pre-2.0 behaviour.
- README rewritten to describe the code that exists.

### Deferred

- **LangChain 0.1 → 0.3.** 0.2 relocated `AgentExecutor` and reworked the prompt
  APIs the Hermes tool loop is written against. It needs its own level and a run
  against a live model. See [ADR 0007](docs/adr/0007-langchain-pinned.md).

---

## [1.0.0]

The imported prototype. Retained for reference; see
[`docs/roadmap/findings.md`](docs/roadmap/findings.md) for what it shipped with.
