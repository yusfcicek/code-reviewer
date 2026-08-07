# 6. A file the reviewer cannot process is reported, not fatal

- **Status**: Accepted
- **Level**: [4](../roadmap/level-4/spec.md)

## Context

An exception from the reviewer or an analyzer on one file propagated out of the
workflow. The composition root caught it at the top and exited 1, discarding
every review completed so far and posting nothing. One flaky model call cost the
whole run.

## Decision

Failures are caught per file. The file is recorded on the outcome and rendered
in the comment as *could not be reviewed*, with the reason. That is a warning:
"the reviewer crashed here" is not evidence that the file is fine.

`gate.fail_on_review_error` decides whether it fails the pipeline. It defaults
to `false`.

## Consequences

- A flaky endpoint costs one file's review, not the merge request's.
- The failure is always visible; the default only decides whether it blocks.
- A crashing analyzer degrades that file's review to prose, because the gate
  falls back to its prose path when no findings are available.
- Exceptions are logged at ERROR with a traceback. They are handled, not
  swallowed.
