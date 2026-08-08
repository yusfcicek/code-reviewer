# Level 10 — Operability

## Problem statement

Nothing in this level changes what the agent decides. All of it changes
whether a team can live with the agent that decides it.

- **Every run posts a new comment.** `GitLabForge.publish_comment` calls
  `notes.create` unconditionally. Five pipeline runs on one merge request leave
  five reports, and the one at the top of the thread is the oldest and the most
  wrong. On a branch that lives a week, the review section becomes something
  people scroll past (G-12).
- **A large review cannot be posted at all.** `render_review_comment`
  assembles per-file sections with no overall bound. A merge request touching
  forty files with findings produces a body GitLab rejects — and the failure
  mode is the worst available: the review ran, the verdict is correct, and the
  merge request shows nothing (G-19).
- **"Blocked" and "broken" exit the same way.** `__main__` exits `2` when
  credentials are missing and `1` for everything else, so a pipeline cannot
  tell a gate that did its job from an agent that crashed. That distinction is
  the precondition for ever setting `allow_failure: false` (G-13).
- **There are three flags.** `--project-id`, `--mr-iid`, `--policy`. There is
  no way to try the agent on a real merge request without posting to it, and no
  way to run the deterministic half without an LLM endpoint — even though the
  verdict has never depended on the model (G-13).
- **There is one typed error.** `MissingCredentialsError`. Everything else is a
  bare `Exception` caught at the top, which is why "connection refused" and
  "the analyzer crashed" cannot be told apart at the exit point (G-13).

Gaps addressed: **G-12, G-13, G-19**.

## Goals

1. One merge request, one review comment, however many times the pipeline runs.
2. A review that is too large to post is truncated and says so, rather than
   not being posted.
3. A pipeline can distinguish a blocked gate from a broken agent.
4. Someone can run the agent against a real merge request without posting, and
   without an LLM.

## Non-goals

- **Per-line review comments.** The single-comment report is the format this
  project has chosen; threading findings onto diff lines is a different product
  decision with its own failure modes.
- **Retrying a failed publish.** The forge adapter reports failure; deciding
  whether a transient GitLab error is worth a second attempt belongs with the
  pipeline that knows its own SLA.
- **A second forge.** `CodeForge` already isolates GitLab. Adding GitHub is
  work this level makes no harder and does not do.

## Behavioural contracts

### C-1 — The review comment is idempotent (G-12)
The rendered comment begins with a marker — an HTML comment, invisible in the
rendered view. `publish_comment` looks for a note carrying that marker and
edits it; only when none exists does it create one. A merge request reviewed
five times carries one review, showing the latest verdict.

The marker identifies *this agent's* comment, not a particular run. Two
different tools posting to the same merge request must not collide, and a
human's reply must never be overwritten.

### C-2 — Failing to update falls back to creating (G-12)
If the marked note cannot be edited — deleted between the read and the write,
or edited by someone without permission — a new comment is posted. Losing the
idempotency is a cosmetic failure; losing the review is not.

### C-3 — An oversized comment is truncated with a notice (G-19)
The body is bounded by `REVIEW_MAX_COMMENT_CHARS` (default 900 000, under
GitLab's 1 000 000). When it exceeds that, the tail is dropped and replaced by
a line stating that the report was truncated and how many characters went. The
*head* survives, because the verdict, the blocking reasons and the severity
summary are at the top: the part that must never be lost is the part that
decides.

### C-4 — Exit codes distinguish what happened (G-13)

| Code | Meaning |
|---|---|
| `0` | The review ran; the gate did not block |
| `1` | The review ran; the gate blocked |
| `2` | Configuration error — missing credentials, an unloadable policy |
| `3` | Runtime error — the agent could not complete the review |

`1` is a *successful* run with a negative verdict. `3` is a run that did not
happen. A pipeline that cannot separate them cannot make the review blocking.

### C-5 — Errors are typed (G-13)
`ReviewError` is the root, with `ConfigurationError`, `ForgeError` and
`ReviewAgentError` beneath it. `MissingCredentialsError` becomes a
`ConfigurationError`. The point is not taxonomy for its own sake: it is that
the exit point can map a category to a code without inspecting messages.

### C-6 — `--dry-run` publishes nothing (G-13)
The review runs in full — triage, analysis, narration, gate — and the report is
printed to stdout instead of posted. The exit code is unchanged, so a dry run
answers "what would this do" including "would it block".

### C-7 — `--no-llm` runs the deterministic half (G-13)
No model is constructed and no narration is attempted. Analyzers run, findings
are produced, the gate decides. The verdict is identical to a run with a model,
because the verdict has never come from the model
([ADR 0004](../../adr/0004-findings-drive-the-gate.md)).

### C-8 — The remaining operational knobs are flags (G-13)
`--repo-root` sets the workspace root. `--metrics-path` sets where OpenMetrics
is written. `--log-level` sets verbosity. Each has an environment fallback so a
pipeline can set it once.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | The rendered comment carries a marker | Unit test on the renderer |
| AC-2 | A second publish edits the marked note instead of creating one | Unit test on the forge, with a fake client |
| AC-3 | A note without the marker is never touched | Unit test |
| AC-4 | An unpublishable edit falls back to creating | Unit test |
| AC-5 | An oversized body is truncated, head-first, with a notice | Unit test on the renderer |
| AC-6 | The truncation notice states how much was dropped | Unit test |
| AC-7 | A body under the limit is untouched | Unit test |
| AC-8 | A blocked gate exits `1`; a clean run exits `0` | Unit test on the entry point |
| AC-9 | A configuration error exits `2` | Unit test |
| AC-10 | A runtime error exits `3` | Unit test |
| AC-11 | `--dry-run` prints and publishes nothing | Unit test |
| AC-12 | `--no-llm` produces a verdict without constructing a model | Unit test |
| AC-13 | `--repo-root`, `--metrics-path`, `--log-level` are honoured | Unit test on the CLI |
| AC-14 | The five checks stay green and coverage holds at its floor | `ruff`, `mypy`, `pytest --cov`, audit |

## Decisions taken

**D-1 — The marker is an HTML comment in the body, not a stored id.** The
alternative is keeping the note id somewhere between runs, which means state —
a file, a label, a pipeline variable — that can drift out of sync with the
thread it describes. The body is the one place that is guaranteed to travel
with the comment, and an HTML comment is invisible to a reader.

**D-2 — Truncation keeps the head.** The verdict, the blocking reasons and the
severity counts are at the top of the report; the per-file prose is at the
bottom. Dropping the tail loses detail. Dropping the head would lose the
decision — and a truncated report that opens mid-sentence about the fourth file
is worse than no report, because it looks complete.

**D-3 — `--dry-run` still exits with the real code.** A dry run whose exit code
is always `0` answers a different question from the one being asked. "What
would this do" includes "would it stop the merge".

**D-4 — `--no-llm` is not a degraded mode.** The gate reads findings, so a
run without a model reaches the same verdict as a run with one. The report is
shorter — no architectural narrative — and that is the entire difference. It is
worth stating plainly, because a flag that looks like it weakens the check will
not be used by the people who most need it.

**D-5 — Exit code `1` means blocked, not failed.** The naming matters at the
pipeline boundary: `allow_failure: false` becomes safe only when `1` cannot
also mean "the agent fell over". Every other failure moves to `2` or `3`.

**D-6 — The error hierarchy is introduced at the boundary, not everywhere.**
`ReviewError` and its three subclasses exist so that `main()` can map a
category to an exit code. Rewriting every internal `raise` to use them would be
a large change for no behavioural gain; the boundary is where the distinction
is consumed, so it is where the types are needed.
