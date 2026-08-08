# 12. One comment per merge request, and an exit code that says which failure

- **Status**: Accepted
- **Level**: [10](../roadmap/level-10/spec.md)

## Context

Three things made the agent unpleasant to live with, none of which changed what
it decided.

Every run called `notes.create`, so a branch reviewed five times carried five
reports and the one at the top of the thread was the oldest and the most wrong.
A review of forty files produced a body GitLab rejects, and that failure mode
is the worst available — the review ran, the verdict was correct, and the merge
request showed nothing at all. And a blocked gate and a crashed agent both
exited `1`, so a pipeline had no way to treat them differently, which is the
precondition nobody had for setting `allow_failure: false`.

## Decision

**The comment carries a marker and the agent edits its own.** The marker is an
HTML comment at the top of the body. Before posting, the forge lists the notes,
finds the one carrying the marker, and edits it; only when none exists does it
create one.

**An oversized body is truncated head-first.** The bound is
`REVIEW_MAX_COMMENT_CHARS`, defaulting under GitLab's ceiling, and the cut is
followed by a line saying how much was dropped.

**Exit codes distinguish four outcomes**: `0` clean, `1` blocked, `2`
configuration error, `3` runtime error. A small error hierarchy —
`ReviewError` with `ConfigurationError`, `ForgeError` and `ReviewAgentError`
beneath it — exists so the entry point can map a category to a code.

## Consequences

- **The marker lives in the body, not in stored state.** A note id kept in a
  file, a label or a pipeline variable is a second place that can disagree with
  the thread it describes. The body is the one thing guaranteed to travel with
  the comment, and an HTML comment is invisible to a reader.
- **Only the agent's own comment is ever edited.** The marker names the tool,
  so another bot's report is not matched; a note without it — a human reply —
  is never touched. Every failure in the find-or-edit path falls back to
  creating a comment: losing idempotency is cosmetic, losing the review is not.
- **Truncation keeps the head.** The verdict, the blocking reasons and the
  severity counts are at the top; the per-file prose is at the bottom. Dropping
  the tail loses detail. Dropping the head would lose the decision, and a
  report that opens mid-sentence about the fourth file is worse than no report
  because it looks complete.
- **`1` now means blocked and nothing else.** This is a breaking change for a
  pipeline that treated `1` as "the agent broke"; the previous meaning was
  ambiguous, which is the finding.
- **The hierarchy is introduced at the boundary, not everywhere.** The types
  exist because `main()` consumes the distinction. Rewriting every internal
  `raise` would be a large change for no behavioural gain.
- **`--no-llm` is not a degraded mode**, and saying so plainly matters. The
  gate reads findings ([ADR 0004](0004-findings-drive-the-gate.md)), so a run
  without a model reaches the same verdict; the report is shorter, and that is
  the whole difference. A flag that looks like it weakens the check will not be
  used by the people who most need it.
