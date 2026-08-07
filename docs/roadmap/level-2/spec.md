# Level 2 — Domain-Driven Layering

## Problem statement

Levels 0 and 1 made the code honest and correct. It is still arranged by
technical role — `analyzers/`, `tools/`, `provider/`, `gate/` — with no boundary
between the rules of the domain and the machinery that talks to GitLab, vLLM,
`grep` and the filesystem.

The cost is concrete, not stylistic:

- **The orchestration cannot be tested.** `run_review` reaches into
  `project.mergerequests.get(...)` directly, so exercising the workflow requires
  a live GitLab. The one place where triage, the agent, the gate and metrics
  meet is also the one place with no tests (F-25, F-27).
- **One concept has three models.** `sast_analyzer.Severity`,
  `performance_analyzer.Severity` and `quality_analyzer.IssueSeverity` each
  describe the same thing. Nothing can aggregate findings across analyzers,
  which is exactly what the gate needs in Level 3 (F-28).
- **A port leaks its implementation.** `MemoryStrategy.get_memory_object()`
  returns "the underlying LangChain memory object", inverting the dependency the
  abstraction exists to protect (F-26).
- **The import package is called `openhands`**, the namespace of the unrelated
  All-Hands-AI/OpenHands project. Installing both shadows this one (F-33).

Findings addressed: **F-24, F-25, F-26, F-27, F-28, F-29, F-30, F-33, F-34,
F-38**.

## Goals

1. Three layers with a one-way dependency rule: `infrastructure → application →
   domain`. The domain imports nothing from the other two.
2. The review workflow runs against in-memory fakes, so the orchestration has
   tests for the first time.
3. One `Severity`, one `Finding`, one `AffectedCode`, one policy model.
4. An import package named after this project.
5. Test layout that mirrors the layers.

## Non-goals

- Changing analyzer rules or thresholds (Level 3).
- Making the policy reach the analyzers (Level 3, F-31).
- Replacing markdown parsing in the gate with structured findings (Level 3,
  F-32). The shared `Finding` model built here is the prerequisite.
- Replacing `print` with structured logging (Level 4, F-47).

## Target structure

```
code_reviewer/
├── domain/               pure rules — no I/O, no frameworks
│   ├── severity.py       one Severity, ordered
│   ├── finding.py        one Finding, plus AffectedCode
│   ├── change.py         FileChange value object
│   ├── policy.py         ReviewPolicy and its sections
│   ├── triage.py         ReviewDecision, TriageResult, ReviewTriage
│   └── gate.py           ReviewGate, GateEvaluation, ReviewOutcome
├── application/          orchestration and the ports it depends on
│   ├── ports.py          CodeForge, LLMProvider, MemoryStrategy, Reviewer
│   ├── review_service.py the use case
│   └── report.py         merge-request comment rendering
├── infrastructure/       everything that talks to the outside world
│   ├── analyzers/        AST/regex analyzers
│   ├── config/           YAML policy loader + review_policy.yaml
│   ├── forge/            GitLab adapter
│   ├── llm/              vLLM provider, review agent, token counting
│   ├── memory/           SmartMemoryStrategy
│   ├── metrics/          Prometheus / GitLab exporter
│   └── tools/            LangChain tool definitions
├── cli.py
└── __main__.py
```

Why analyzers sit in infrastructure: they parse files, shell out to `grep` and
read the disk. Their *vocabulary* — severity, finding, risk — belongs to the
domain and moves there; their *mechanics* do not.

## Behavioural contracts

### C-1 — The workflow runs without a network (F-25, F-27)
`ReviewService.review(project_id, merge_request_iid)` is driven by a
`CodeForge` port. A fake forge returning canned changes exercises triage, the
agent, the gate and metrics end to end, and asserts what was posted back.

### C-2 — GitLab is one adapter among possible others (F-27)
Nothing in `application/` or `domain/` imports `gitlab`. Swapping the adapter
requires no change above the infrastructure layer.

### C-3 — One severity (F-28)
`domain.severity.Severity` is the only severity type. It is ordered — comparison
operators work — so callers sort with `sorted(findings)` instead of remembering
a rank helper. Analyzer-specific aliases are removed, not re-exported.

### C-4 — One finding (F-28, F-29)
Analyzers produce `domain.finding.Finding`: category, severity, location,
description, remediation. `AffectedCode` is defined once and used by both the
dependency tracker and the memory strategy.

### C-5 — Ports declare no framework types (F-26)
`get_memory_object()` is gone. Every port method signature uses builtins or
domain types.

### C-6 — One policy model (F-30)
`TriageConfig` is deleted. `ReviewPolicy` and its sections are the only
representation, and `triage_changes()` takes the same type `ReviewTriage` does.

### C-7 — The package is named after this project (F-33, F-34)
`import code_reviewer`. The console script and every test import the new name.
No `sys.path` manipulation anywhere.

### C-8 — Tests mirror the layers (F-38)
```
tests/unit/domain/          tests/unit/application/
tests/unit/infrastructure/  tests/integration/
```

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | `uv run pytest` is green throughout; the move itself changes no behaviour | Suite runs after each step |
| AC-2 | No module under `domain/` imports from `application/`, `infrastructure/`, `langchain`, `gitlab`, `subprocess` or `yaml` | An architecture test asserts this |
| AC-3 | No module under `application/` imports `gitlab` or `langchain` | Same architecture test |
| AC-4 | `ReviewService` has tests that run offline | `tests/unit/application/test_review_service.py` |
| AC-5 | `grep -r "openhands" --include="*.py"` returns nothing | Command output |
| AC-6 | Exactly one `class Severity` and one `class Finding` in the tree | `grep -c` |
| AC-7 | Coverage of `application/` is above 85 % | `uv run pytest --cov` |

## Decisions taken

**D-1 — Package name `code_reviewer`.** It matches the repository
(`code-reviewer`) and the distribution's purpose. `openhands` is another
project's namespace; keeping it invites a silent shadowing bug that is very hard
to diagnose. The distribution name on PyPI stays
`enterprise-ai-code-reviewer`.

**D-2 — Analyzers stay concrete, behind no interface for now.** Introducing an
`Analyzer` protocol would be speculative: the only consumer is the tool layer,
which calls them by name. Level 3 introduces the protocol when the gate starts
consuming structured findings and a second implementation becomes plausible.

**D-3 — `Severity` becomes an ordered enum rather than an enum with a `rank`
property.** Level 1 added `rank` to three enums as the minimal fix. With one
type, ordering belongs on the type itself: `Severity.CRITICAL < Severity.HIGH`
reads correctly and makes `sorted()` and `max()` work without a key function.

**D-4 — The move is mechanical first, behavioural second.** Files are relocated
with `git mv` and imports rewritten in one commit with the suite green, then
`ReviewService` is written test-first in a separate commit. Mixing the two would
make it impossible to tell a move from a regression.

**D-5 — Quality/performance analyzer thresholds keep their class constants.**
Wiring policy into them is Level 3 (F-31); doing it here would blur the line
between "moved" and "changed".
