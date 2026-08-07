# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

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
