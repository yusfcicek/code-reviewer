# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
