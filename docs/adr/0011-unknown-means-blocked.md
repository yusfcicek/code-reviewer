# 11. "Unknown" is not "pass"

- **Status**: Accepted
- **Level**: [9](../roadmap/level-9/spec.md)

## Context

Four places in the code met something they did not understand and answered
*"fine, then"*. Each of them pointed the same way.

A crashed analyzer returned an empty list, and an empty list is what a clean
file returns. An unrecognised policy key was logged at WARNING and skipped, so
`block_on_critcal: false` left the rule enabled under a name its author
believed they had disabled. A three-line change to a CI definition fell through
to the auto-approve threshold. And a lock file — the only artefact where a
changed *transitive* dependency is visible — was skipped outright as
"generated".

None of these is a bug in the ordinary sense. Every one of them was a
deliberate choice to be forgiving, and every one of them produced the
permissive answer to a question that had not actually been answered. That is
the same shape as F-01 and F-32 in this repository's own findings inventory.

## Decision

A review distinguishes three states, and only the middle one passes:

| State | Meaning | Effect |
|---|---|---|
| findings | analysis ran and found things | blocks per `gate.blocking_severity` |
| no findings | analysis ran and found nothing | passes |
| **analysis error** | analysis could not run | **blocks** |

And configuration fails closed **on content, not on absence**: a policy file
that says something unrecognised stops the run; no policy file at all falls
back to the shipped default.

## Consequences

- **A narration failure still only warns.** The asymmetry is the load-bearing
  part. Static analysis is the evidence; when it could not be gathered, the
  honest answer is "unknown", and a gate must not read that as "pass". Prose is
  not evidence, so its absence costs the decision nothing — and a model that
  has run out of credit must not be able to stop a clean merge request, because
  that is how teams end up disabling the gate entirely
  ([ADR 0004](0004-findings-drive-the-gate.md)).
- **Silence is not a claim; a typo is.** Finding no policy file is a deployment
  that has not configured one. A file containing `block_on_critcal` is a
  deployment that believes something false about itself. Only the second is
  worth stopping for, and treating them alike in either direction would be
  wrong — failing on absence would break every default install, and forgiving
  content is what produced this ADR.
- **This breaks existing deployments whose policy files carry stale keys.**
  Intentionally: the file was not doing what its author thought. The error
  names the file, the key, and what would have worked.
- **Lock files are now reviewed, and lock file diffs are long.** The cost is
  real and the trade is deliberate; `skip_patterns` is policy, so a team that
  weighs it differently can put them back.
- **Every knob has an off switch, and turning it off does not turn off the
  knowledge.** `fail_pipeline_on_analysis_error: false` stops the block; the
  file is still listed as unanalysed, in the warnings and in the report.
