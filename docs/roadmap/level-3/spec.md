# Level 3 — Analyzer Accuracy and Policy Enforcement

## Problem statement

The analyzers work and are tested. What they produce, however, reaches almost
nothing:

- **The gate re-derives numbers the analyzers already computed.** It runs
  regular expressions over the model's prose to recover a quality score and a
  risk level. If the model phrases its report differently — as it eventually
  will — the gate reads nothing and the pipeline decision rests on
  formatting (F-32). Level 2's F-57 was one instance of that fragility; the
  design invites more.
- **The analyzers only run if the model chooses to call them.** They are
  registered as agent tools. A model that decides to answer from the diff alone
  produces a review with no SAST scan behind it, and nothing says so.
- **Configuring the analyzers has no effect.** `QualityPolicy.max_class_methods`
  and the rest exist, are loaded from YAML, and are then ignored in favour of
  class constants (F-31).
- **The agent's file tools accept any path the model asks for.** A diff that
  contains instructions — a prompt injection — can make the agent read a file
  outside the repository and echo it into a public merge-request comment
  (F-21).
- **Configuration files are skipped wholesale.** `.*\.yaml$`, `.*\.json$` and
  `Dockerfile` are on the default skip list, which is where privilege changes,
  pipeline definitions and image bases live (F-22).

Findings addressed: **F-21, F-22, F-31, F-32**.

## Goals

1. Every reviewed file is analysed deterministically, whether or not the model
   calls a tool.
2. The gate decides from findings, not from prose. Prose becomes one input among
   several, not the source of truth.
3. Policy thresholds change behaviour.
4. The agent cannot read outside the workspace.
5. Files that carry deployment and dependency risk are reviewed.

## Non-goals

- Structured logging and complete metrics (Level 4, F-16, F-17).
- Adding new analyzer rule families. This level makes the existing ones
  configurable, reachable and comparable.
- Replacing the LLM review. The model's architectural judgement is the point of
  the product; this level stops it being the *only* evidence.

## Behavioural contracts

### C-1 — Deterministic analysis on every reviewed file (F-32)
`ReviewService` runs a static analysis suite over each file it sends to the
model. The suite returns `list[Finding]` — the shared domain type from Level 2 —
covering security, quality and performance. The result is attached to the
review, independent of whether the agent called any tool.

### C-2 — The gate reads findings first (F-32)
`ReviewGate.evaluate(review_markdown, findings)` decides from the findings when
they are present:

- any finding at or above the policy's blocking severity blocks;
- the quality score is computed from findings, not parsed;
- prose parsing remains as a fallback for the model's own observations, and
  contributes warnings rather than blocks.

A report whose prose is unparseable but whose findings are clean passes. A
report whose prose is glowing but whose findings contain a CRITICAL blocks.

### C-3 — Policy reaches the analyzers (F-31)
`QualityAnalyzer(policy=...)` and `PerformanceAnalyzer(policy=...)` take their
thresholds from the policy, falling back to the current constants when none is
supplied. Changing `max_class_methods` in the YAML changes what is reported.

### C-4 — Tools are confined to the workspace (F-21)
Every filesystem tool resolves its argument against a workspace root and refuses
anything outside it, including through symlinks and `..`. Refusal is an
explanatory message to the model, not an exception that ends the review.
Oversized files are truncated with a notice rather than pasted whole into the
prompt.

### C-5 — Deployment-shaped configuration is reviewed (F-22)
The default skip list covers documentation and lock files. Pipeline definitions,
container definitions, Kubernetes manifests, Terraform and dependency manifests
are reviewed. A `Dockerfile` that switches to `USER root` is exactly the kind of
change this product exists to catch.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A review with clean prose and a CRITICAL finding is blocked | `tests/unit/domain/test_gate.py` |
| AC-2 | A review with unparseable prose and no findings passes | Same |
| AC-3 | The suite runs for every file sent to the model | `tests/unit/application/test_review_service.py` |
| AC-4 | Raising `max_class_methods` in the policy silences an SRP finding | `tests/unit/infrastructure/test_quality.py` |
| AC-5 | `read_file("/etc/passwd")` is refused, as is `../../etc/passwd` and a symlink pointing outside | `tests/unit/infrastructure/test_tools.py` |
| AC-6 | `Dockerfile` and `.gitlab-ci.yml` are not skipped by the default policy | `tests/unit/domain/test_triage.py` |
| AC-7 | `uv run pytest` green; architecture test still passes | Suite |

## Decisions taken

**D-1 — Findings and prose both feed the gate; findings win.** Removing the
prose path entirely would discard the model's architectural judgement, which no
static analyzer produces. Removing the findings path leaves the pipeline
decision resting on text formatting. The gate therefore blocks on findings and
warns on prose, and says which source produced each reason.

**D-2 — Analyzers are adapted to `Finding`, not rewritten.** Each analyzer keeps
its internal report type and gains a translation into the shared `Finding`.
Rewriting five analyzers to emit the domain type directly would be a large
change with no behavioural gain, and their tests pin the current output.

**D-3 — The workspace root is the current working directory by default.** Under
GitLab CI that is the cloned repository. It is injectable so that a caller can
narrow it further, and the confinement is enforced with `Path.resolve()`, which
also collapses symlinks.

**D-4 — Lock files stay skipped, manifests do not.** `uv.lock` and
`package-lock.json` are machine-generated and enormous; reviewing them costs
tokens and finds nothing a human would act on. `pyproject.toml` and
`package.json` declare what gets installed and are reviewed.

**D-5 — The suite is a port.** `ReviewService` depends on a `StaticAnalysis`
protocol, so the workflow tests keep running without invoking real analyzers,
and a future language-specific suite can be substituted.
