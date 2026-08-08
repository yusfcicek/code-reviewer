# Work Report — Prototype to 2.0.0

What was done, in what order, and why. The detail lives in
[`roadmap/findings.md`](roadmap/findings.md) (59 findings), the per-level specs
and plans under [`roadmap/`](roadmap/README.md), and the
[decision records](adr/README.md).

---

## Starting point

A repository with **no commits**. 31 files, ~4 900 lines, 10 tests over 2 of 13
modules. README described an "enterprise-grade" agent.

Every file was read line by line before any code was written. The result was an
inventory of **59 findings** with `file:line` references, a severity, and the
level that would own each fix.

---

## Method

Each level followed the same rhythm, on its own branch off `development`:

```
spec  →  plan  →  failing test  →  fix  →  green  →  commit  →  merge --no-ff
```

- **Spec before plan, plan before code.** Both committed before implementation.
- **TDD.** Every behaviour change began with a test observed failing for the
  right reason.
- **DDD.** Domain rules kept free of I/O and frameworks; an architecture test
  enforces it.
- **Conventional Commits**, body explaining the defect rather than the diff.

---

## The seven levels

| L | Theme | Key outcome |
|---|---|---|
| **0** | Foundation & documentation truth | Baseline commit, MIT licence resolved, installable package, pytest configured, README rewritten to describe the code that exists |
| **1** | Correctness | 21 findings where code ran with no effect and no error |
| **2** | DDD layering | Three layers, one-way dependencies, `CodeForge` port, one `Severity`/`Finding`, package renamed |
| **3** | Analyzer accuracy & policy | Analysis on every file, findings drive the gate, workspace confinement, policy thresholds enforced |
| **4** | Observability & resilience | Structured logging, review-wide OpenMetrics, per-file failure isolation, model timeouts |
| **5** | CI/CD & quality gates | ruff, mypy, coverage floor, GitHub + GitLab pipelines, pre-commit |
| **6** | Documentation & productisation | One language, ARCHITECTURE, 8 ADRs, SECURITY, CHANGELOG |

---

## The defects that mattered

These produced no error and no log line. They simply did nothing.

| ID | Defect |
|---|---|
| **F-01** | **The gate could not block a pipeline.** The orchestrator compared a `ReviewGateResult` enum against the string `"fail"`. Never matched. The product's headline feature was dead and `sys.exit(1)` was unreachable. |
| **F-02** | **No collected insight reached the model.** `memory_context` was supplied to a prompt template that never declared the variable; LangChain dropped it silently. |
| **F-03** | **The tool loop could not work.** Tools were never described to the model, and the scratchpad was formatted as OpenAI function calls while the parser read Hermes XML. |
| **F-04** | **The bundled policy file was never loaded.** Every candidate path was relative to the working directory. |
| **F-57** | **A failed SAST scan could not fail the gate.** The check looked for `SAST Scan Result: FAIL` while the prompt asks for `- **SAST Scan Result**: FAIL`. It looked like it worked only because failing reports usually also carry a critical risk. |
| **F-20** | **TLS verification disabled** on every call carrying the GitLab token — flagged CWE-295 HIGH by the project's own analyzer. |
| **F-21** | **Unconfined file access.** The agent read any path the model asked for, and those paths come from the diff: anyone who can open a merge request could attempt a prompt injection with a public output channel. |
| **F-09** | **Triage escalated on unchanged lines.** A `password` in surrounding context forced an expensive review; deleting an `eval()` call did too. |
| **F-07** | **Severity sorting was alphabetical** — `critical < high < info < low < medium` — so truncating a report dropped severe findings. |
| **F-05/F-06** | Two rules that could never fire: a membership test against a list, and a lookahead that always succeeded. |

---

## Findings found *while fixing others*

Five of the 59 appeared only because an earlier fix made them reachable. This is
the argument for sequencing rather than attacking the list.

| ID | Surfaced by |
|---|---|
| F-55 | Loading the policy file: `version` was never merged, so every report claimed `1.0` |
| F-56 | Same: an empty YAML section parses as `None`, and the shipped policy ended with one — **loading the project's own policy crashed the run** |
| F-57 | Writing the workflow's first tests |
| F-58 | Specifying observability: one file's exception discarded every completed review |
| F-59 | Same: nothing bounded a call to the model |

---

## What the product does now

- **Static analysis on every reviewed file**, whether or not the model calls a
  tool. Findings block; the model's prose warns. Every reason names its source.
- **Three layers** — `domain` → `application` → `infrastructure` — with the
  direction enforced by a test that parses imports.
- **Workspace confinement**: paths resolved before comparison, so `..`,
  symlinks and prefix-sharing siblings are refused. Refusals reach the model as
  text, so the review continues.
- **Observability**: `LOG_LEVEL`, optional JSON logs, valid OpenMetrics for the
  whole review, model timeout and retry budget.
- **Resilience**: a file the reviewer cannot process is reported as *not
  reviewed* — a warning, not an approval.
- **CI on GitHub and GitLab**, the GitLab pipeline running this agent against
  its own merge requests.

---

## Numbers

| | Before | After |
|---|---|---|
| Tests | 10 (2 modules) | **433** |
| Coverage | unmeasured | **87 %**, floor of 85 % enforced |
| Lint | none | ruff clean (1 574 findings on the first pass) |
| Types | none | mypy over domain + application |
| Pipelines | none | GitHub Actions + GitLab |
| Commits | none | 30, on 7 feature branches |
| Findings | — | 59 recorded, 58 fixed, 1 deferred |

---

## Deliberately left open

**LangChain 0.1 → 0.3.** 0.2 relocated `AgentExecutor` and reworked the prompt
APIs the Hermes tool loop is written against. It needs its own level, its own
contracts and a run against a live model — the integration test uses a scripted
model, which would keep passing while the real dialect broke. Recorded in
`pyproject.toml`, [ADR 0007](adr/0007-langchain-pinned.md) and the roadmap.

**One decision worth confirming.** `LICENSE` shipped GPL-3.0 while README
called it MIT. MIT was chosen — README stated the intent, nothing had been
published, and a permissive licence suits a CI component.
[ADR 0001](adr/0001-mit-licence.md) records how to reverse it: one file.

---

## Where to read next

`README.md` → [`ARCHITECTURE.md`](ARCHITECTURE.md) →
[`adr/`](adr/README.md) → [`roadmap/findings.md`](roadmap/findings.md) →
[`SECURITY.md`](../SECURITY.md) → [`CHANGELOG.md`](../CHANGELOG.md)
