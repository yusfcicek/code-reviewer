# Level 2 — Implementation Plan

Branch: `feature/level-2-ddd-layering` (off `development`)

Ordered so that a green suite separates every mechanical step from every
behavioural one (decision D-4). If a step turns the suite red, the cause is in
that step alone.

## Step 1 — Shared kernel: one severity, one finding

Test-first, because this is new behaviour rather than a move.

- `tests/unit/domain/test_severity.py`: ordering, comparison, parsing from a
  string, and that the most severe of a mixed list is `CRITICAL`.
- `tests/unit/domain/test_finding.py`: construction, rendering of a location,
  sorting a mixed list.
- `code_reviewer/domain/severity.py`: one ordered `Severity`.
- `code_reviewer/domain/finding.py`: `Finding`, `FindingCategory`,
  `AffectedCode`.

**Done when:** the domain package exists with tests and no imports outside the
standard library.

## Step 2 — Architecture test

- `tests/unit/test_architecture.py`: walks the tree, parses each module's
  imports with `ast`, and asserts the dependency rule. It fails now — the
  package it inspects does not exist yet — and stays as the guard that stops the
  layering from eroding.

## Step 3 — Move the tree

Mechanical. `git mv` per module, then rewrite imports.

| From | To |
|---|---|
| `openhands/agent/triage/review_triage.py` | `code_reviewer/domain/triage.py` |
| `openhands/agent/gate/review_gate.py`, `gate/outcome.py` | `code_reviewer/domain/gate.py` |
| `openhands/agent/config/config_loader.py` (dataclasses) | `code_reviewer/domain/policy.py` |
| `openhands/agent/config/config_loader.py` (loader) | `code_reviewer/infrastructure/config/loader.py` |
| `openhands/agent/config/review_policy.yaml` | `code_reviewer/infrastructure/config/review_policy.yaml` |
| `openhands/agent/analyzers/*` | `code_reviewer/infrastructure/analyzers/*` |
| `openhands/agent/core/agent.py`, `token_counter.py` | `code_reviewer/infrastructure/llm/` |
| `openhands/agent/provider/vllm_provider.py` | `code_reviewer/infrastructure/llm/vllm.py` |
| `openhands/agent/provider/gitlab_client.py` | `code_reviewer/infrastructure/forge/gitlab.py` |
| `openhands/agent/memory/strategies.py` | `code_reviewer/infrastructure/memory/smart_memory.py` |
| `openhands/agent/metrics/collector.py` | `code_reviewer/infrastructure/metrics/collector.py` |
| `openhands/agent/tools/definitions.py` | `code_reviewer/infrastructure/tools/definitions.py` |
| `openhands/agent/core/interfaces.py` | `code_reviewer/application/ports.py` |
| `openhands/agent/report.py` | `code_reviewer/application/report.py` |
| `openhands/agent/cli.py` | `code_reviewer/cli.py` |
| `openhands/agent/main.py` | `code_reviewer/__main__.py` (thin) |

Tests move to `tests/unit/{domain,application,infrastructure}/` to match.

`pyproject.toml`: package name, wheel target and console script updated.

**Done when:** `uv run pytest` is green, `grep -r openhands --include=*.py`
finds nothing, and the architecture test passes.

## Step 4 — Analyzers speak the shared vocabulary

- Replace the three local severity enums with `domain.severity.Severity`.
- Keep each analyzer's own issue-category enum for now; mapping them onto a
  single `FindingCategory` is Level 3 work, and the tests that assert category
  names would otherwise churn twice.
- Delete the `rank` properties added in Level 1: ordering lives on the type.

**Done when:** exactly one `class Severity` exists and the analyzer tests pass
against it.

## Step 5 — Ports and the GitLab adapter

Test-first.

- `tests/unit/application/test_ports.py`: an in-memory `FakeForge` satisfies
  `CodeForge`.
- `code_reviewer/application/ports.py`: `CodeForge` with `fetch_changes`,
  `fetch_file`, `publish_comment`; `LLMProvider`; `MemoryStrategy` without
  `get_memory_object`; `Reviewer`.
- `code_reviewer/infrastructure/forge/gitlab.py`: `GitLabForge` implementing
  `CodeForge` on top of `python-gitlab`, including the client factory from
  Level 1.

## Step 6 — `ReviewService`

Test-first, and the point of the level.

- `tests/unit/application/test_review_service.py` asserts, against fakes:
  skipped files never reach the agent; auto-approved files appear in the comment
  but not in the gate; a failing gate produces a blocking outcome and exit
  code 1; deleted files are ignored; an empty change set posts nothing; metrics
  are recorded per analysed file.
- `code_reviewer/application/review_service.py` receives its collaborators
  through the constructor.
- `__main__.py` shrinks to composition root: build adapters, call the service,
  exit with its code.

## Step 7 — Delete the duplicates

- `TriageConfig` (F-30) — `ReviewPolicy` is the only policy model.
- `AffectedCodeEntry` in the memory strategy (F-29) — use the domain type.
- `get_memory_object()` (F-26).

## Step 8 — Close the level

Update README structure section, roadmap statuses, findings table. Merge into
`development` with `--no-ff`.

## Risks

| Risk | Mitigation |
|---|---|
| A large move hides a regression | Move and behaviour change are separate commits; the suite runs between them |
| Import rewriting misses a call site | The architecture test plus a `grep` for the old package name; the suite covers 190 cases |
| `ReviewService` reproduces the orchestration's bugs | It is written test-first from the contracts, not copied line by line |
