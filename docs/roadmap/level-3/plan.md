# Level 3 — Implementation Plan

Branch: `feature/level-3-analyzer-accuracy` (off `development`)

Security first, then the plumbing that makes the analyzers matter.

## Step 1 — Confine the tools to the workspace (F-21)

Test-first: `tests/unit/infrastructure/test_tools.py`.

- `/etc/passwd` is refused.
- `../../etc/passwd` is refused after resolution.
- A symlink inside the workspace pointing outside is refused.
- A path inside the workspace is allowed.
- Refusal is a message the model can act on, not an exception.
- A file larger than the limit is truncated with a notice.

Implementation: `code_reviewer/infrastructure/tools/workspace.py` holding a
`Workspace` value object with `resolve(path)` and `read(path)`. Every tool in
`definitions.py` goes through it. `grep` and `find` invocations get their root
from the workspace rather than a literal `"."`.

## Step 2 — Review deployment configuration (F-22)

Test-first: `tests/unit/domain/test_triage.py`.

- `Dockerfile`, `.gitlab-ci.yml`, `k8s/deploy.yaml` and `pyproject.toml` are not
  skipped.
- `uv.lock`, `package-lock.json` and `docs/guide.md` are still skipped.

Implementation: rewrite the skip lists in `domain/policy.py` and
`infrastructure/config/review_policy.yaml`, with a comment explaining the
distinction between generated files and declarations.

## Step 3 — Policy reaches the analyzers (F-31)

Test-first: `tests/unit/infrastructure/test_quality.py`,
`test_performance.py`.

- A class with 12 public methods is reported under the default policy and
  silent when `max_class_methods` is raised to 20.
- `max_function_lines`, `max_cyclomatic_complexity` and `min_duplicate_lines`
  behave the same way.
- `max_nested_loops` changes what the performance analyzer reports.

Implementation: both analyzers take an optional `policy` in the constructor and
read thresholds from it, keeping the class constants as defaults.

## Step 4 — Analyzers speak `Finding` (F-32, part one)

Test-first: `tests/unit/infrastructure/test_analysis_suite.py`.

- Each analyzer's report translates into `Finding` objects with the right
  category, severity, location and remediation.
- The suite over a file with an `eval()` call returns a CRITICAL security
  finding.
- The suite over a clean file returns nothing.
- A file the analyzers cannot parse yields no findings rather than an error.

Implementation: `infrastructure/analyzers/suite.py` with a
`StaticAnalysisSuite` and per-analyzer `to_findings` adapters (decision D-2).

## Step 5 — The gate decides from findings (F-32, part two)

Test-first: `tests/unit/domain/test_gate.py`.

- Clean prose plus a CRITICAL finding blocks.
- Unparseable prose plus no findings passes.
- The quality score comes from findings when they are present.
- Each reason names its source, so a reader can tell an analyzer's verdict from
  the model's opinion.
- Prose-only evaluation still works, for callers that have no findings.

Implementation: `ReviewGate.evaluate(review_markdown, findings=None)`; a
`GatePolicy.blocking_severity` field; scoring from `Severity.weight`.

## Step 6 — Wire the suite into the workflow

Test-first: `tests/unit/application/test_review_service.py`.

- The suite runs for every file that reaches the model.
- It does not run for skipped or auto-approved files.
- Its findings reach the gate.
- A finding-driven block appears in the merge-request comment with its location.

Implementation: `StaticAnalysis` protocol in `application/ports.py`;
`ReviewService` takes one; `__main__.py` supplies `StaticAnalysisSuite`; the
report renders a findings table.

## Step 7 — Close the level

README status table, roadmap and findings statuses, merge into `development`.

## Risks

| Risk | Mitigation |
|---|---|
| Confining tools breaks legitimate reads in CI | The workspace defaults to the working directory, which under GitLab CI is the clone; the refusal message names the root so misconfiguration is obvious |
| Reviewing configuration files raises cost | Only the skip list changes; triage still sizes the review, and lock files stay excluded |
| Findings-driven gating changes verdicts for existing users | The blocking severity is a policy field, defaulting to CRITICAL only, so the change is opt-in for anything less severe |
| Adapters drift from analyzer output | The suite tests assert on real analyzer runs, not on fixtures |
