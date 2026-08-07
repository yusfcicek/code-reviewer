# 4. The gate decides from findings; prose warns

- **Status**: Accepted
- **Level**: [3](../roadmap/level-3/spec.md)

## Context

The gate recovered a quality score and a risk level by running regular
expressions over the model's prose — numbers the analyzers had already computed.
The pipeline decision therefore rested on the model's formatting.

That is not theoretical. Finding F-57: the gate looked for the literal string
`SAST Scan Result: FAIL` while the prompt asks the model for
`- **SAST Scan Result**: FAIL - <level>`. The emphasis markers meant a failed
security scan could not fail the gate on its own, and it went unnoticed because
failing reports usually also carry a critical risk assessment.

Separately, the analyzers only ran when the model chose to call them as tools. A
model that answered from the diff alone produced a review with no security scan
behind it, and nothing said so.

## Decision

1. `StaticAnalysisSuite` runs over every reviewed file, unconditionally.
2. `ReviewGate.evaluate(review_markdown, findings)` blocks on findings at or
   above `policy.gate.blocking_severity`, and computes the quality score from
   severity weights.
3. The model's prose contributes warnings, not blocks, whenever analysis ran.
4. Each reason names its source: `[analysis]` or `[review]`.
5. `None` means no analysis ran; `[]` means it ran and found nothing. Only the
   first leaves prose its blocking power.

## Consequences

- A pipeline verdict is reproducible: the same diff produces the same findings.
- The model's architectural judgement is kept — no analyzer produces it — but it
  can no longer fail a build by rephrasing.
- `blocking_severity` defaults to `critical`, so adopting this does not silently
  start failing pipelines that used to pass.
- A caller with no analyzer configured behaves exactly as before.
