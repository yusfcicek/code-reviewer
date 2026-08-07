# Level 1 — Correctness

## Problem statement

Level 0 established that the repository's documentation over-claims. Level 1
addresses *why*: several features are fully written, plausibly structured, and
have **no effect at runtime**. They do not raise errors, so nothing in the logs
suggests they are inert.

Three of them are load-bearing:

- The **review gate** compares an enum against a string, so the branch that
  fails a pipeline is unreachable. The tool cannot block anything (F-01).
- The **memory context** is passed to a prompt template that does not declare
  it, so the model never receives a single collected insight (F-02).
- The **bundled policy file** is never found, so every deployment silently runs
  on the narrow dataclass defaults instead of the shipped rules (F-04).

Refactoring on top of this would preserve the bugs inside a nicer structure.
Level 1 therefore fixes behaviour first, pinning each fix with a test that fails
on the current code.

Findings addressed: **F-01, F-02, F-03, F-04, F-05, F-06, F-07, F-08, F-09,
F-10, F-11, F-12, F-13, F-14, F-15, F-19, F-20, F-36, F-37**.

## Goals

1. Every capability README lists as working is demonstrably exercised by a test.
2. No security-relevant default is unsafe.
3. Analyzer rules that cannot match anything are either fixed or removed — a
   rule that never fires is worse than no rule, because it reads as coverage.
4. The test suite becomes the place where these guarantees live: 19 findings,
   19 or more regression tests, each failing on the baseline.

## Non-goals

- Moving modules or renaming packages (Level 2).
- Feeding analyzer output into the gate as structured data instead of prose
  (Level 3). Level 1 makes the existing prose path work correctly.
- Making the policy's quality and performance thresholds reach the analyzers
  (Level 3, F-31).

## Behavioural contracts

Each contract is stated as an observable outcome, not as an implementation.

### C-1 — A failing gate fails the run (F-01)
Given a review report that the gate evaluates as `FAIL`, the orchestration
marks the overall outcome as blocked, lists the blocking issues in the merge
request comment, and exits non-zero when the policy says
`fail_pipeline_on_critical`. Comparing a `ReviewGateResult` to a `str` must be
impossible to get wrong silently: the aggregate is computed from enum values.

### C-2 — A missing score is not a zero score (F-10)
Given a report with no `SOLID Compliance: [n/100]` line, the gate reports the
quality score as *unknown* and does not raise a threshold violation. A parser
that cannot find a number must not invent the worst possible one.

### C-3 — TLS verification is on by default (F-20)
The GitLab client verifies certificates. Verification can be disabled only by
setting `GITLAB_SSL_VERIFY=false` explicitly, and doing so emits a warning that
names the risk. A custom CA bundle can be supplied instead.

### C-4 — The shipped policy is the default policy (F-04)
Calling `load_policy()` with no argument loads
`openhands/agent/config/review_policy.yaml` from the installed package,
regardless of the working directory. Explicit `--policy`, then working-directory
files, then the bundled file, then dataclass defaults.

### C-5 — The model sees the memory context (F-02)
The prompt template declares every variable the runnable supplies, and the
rendered prompt contains the memory context. A variable supplied but not
declared must fail loudly rather than be dropped.

### C-6 — The model is told which tools exist (F-03)
The rendered system prompt names every registered tool with its description, and
the scratchpad is formatted in the same dialect the output parser reads. The
agent's tool loop is exercised end to end against a stub model that emits a
Hermes tool call.

### C-7 — Token counting does not mutate the model (F-11)
Constructing a memory strategy leaves the chat model object unchanged. Token
estimation lives behind an explicit, injectable counter.

### C-8 — Severity ordering is severity ordering (F-07)
Sorting findings by severity puts `critical` before `high` before `medium`
before `low` before `info`, in all three analyzers. Truncating to the first N
findings keeps the most severe ones.

### C-9 — Triage escalates on what changed (F-09)
Security-pattern matching considers added lines only. A `password` in an
unchanged context line, or in a line the change *removes*, does not escalate the
file to `CRITICAL`.

### C-10 — Rules that cannot fire are fixed (F-05, F-06, F-08)
- String concatenation inside a loop is reported (F-05).
- `yaml.load(data)` is reported; `yaml.safe_load(data)` and
  `yaml.load(data, Loader=yaml.SafeLoader)` are not (F-06).
- Usage classification in the dependency tracker is expressed so that each
  branch is reachable and its intent is testable (F-08).

### C-11 — Semantic classification does not guess (F-12, F-13, F-14)
- An empty diff is `UNKNOWN`, not `STYLE` (F-12).
- `BUGFIX` requires a whole-word marker (`fix`, `bug`, `hotfix`), not a
  substring of `prefix` or `debug` (F-13).
- "Defined but never called" is only claimed when the analyzer has whole-project
  visibility; from a single file it is reported as *not referenced in this file*
  (F-14).

### C-12 — CLI arguments have the declared type (F-15)
`--project-id` and `--mr-iid` are integers whether they arrive from the command
line or from `CI_PROJECT_ID` / `CI_MERGE_REQUEST_IID`. A non-numeric environment
value is a clear error, not a downstream type surprise.

### C-13 — The test suite tests (F-36, F-37)
`test_summarization_trigger` asserts an outcome. No test replaces modules in
`sys.modules`; the agent is constructible in a test process without stubbing
its framework, and test results do not depend on collection order.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | Every contract C-1…C-13 has at least one test that fails on commit `51a7492` | Tests are written first and observed failing |
| AC-2 | `uv run pytest` is green | CI-equivalent local run |
| AC-3 | No test mutates `sys.modules` | `grep -r "sys.modules\[" tests/` returns nothing |
| AC-4 | Coverage of the modules touched in this level is above 70 % | `uv run pytest --cov` |
| AC-5 | README's status table no longer lists any capability as ❌ Broken | Manual diff against `findings.md` |

## Decisions taken

**D-1 — Extract collaborators from `main.py` only where a test needs them.**
Level 2 owns the layering. Level 1 pulls out the smallest testable units — the
outcome aggregator, the GitLab client factory, the argument parser — and leaves
the rest of the orchestration in place. Extracting more now would mean doing the
same work twice with different boundaries.

**D-2 — Keep the prose-parsing gate, fix its failure mode.** Replacing markdown
parsing with structured analyzer output is a design change (Level 3, F-32). In
Level 1 the parser must merely stop inventing data it did not find.

**D-3 — Tool descriptions are rendered into the system prompt.** The target
model is served by vLLM in a Hermes dialect, which is why a Hermes XML parser
exists. `bind_tools` would emit OpenAI-style function-calling payloads that the
parser cannot read. Rendering the tool catalogue into the prompt and formatting
the scratchpad in the same dialect keeps one convention end to end.

**D-4 — `random.*` and similar noisy SAST rules stay until Level 3.** They fire
correctly; they are simply over-eager. Tuning precision is analyzer-accuracy
work and needs the policy plumbing that Level 3 introduces.
