# 13. Suppression is narrow, reasoned and counted

- **Status**: Accepted
- **Level**: [11](../roadmap/level-11/spec.md)

## Context

Every static analyzer produces false positives. One that does not is not
looking hard enough — precision and recall trade against each other, and a
tool tuned to never misfire has been tuned to miss things.

Before Level 11 there was no way to say "this one is wrong". A team facing a
single rule that misfired on a single line had two options: turn the rule off
in the policy, or set `gate.blocking_severity` so the gate stopped blocking.
Both are far wider than the problem, and both are reached by someone who would
have accepted a narrower answer if one existed.

So the absence of suppression does not produce a stricter tool. It produces a
tool that gets switched off.

## Decision

`# review-ignore: RULE_ID - reason`, scoped to the line it sits on — or, when
it is a comment of its own, to the line below it. `# review-ignore-file:` for a
whole file. `RULE_ID` names a rule or a namespace (`SAST.*`).

Four constraints, each of which exists to stop this becoming the second
off-switch:

1. **One line, or one file.** No ranges, no severity thresholds, no path globs
   in policy.
2. **A named rule.** A bare `*` is not accepted.
3. **A written reason**, captured and shown.
4. **A count.** Suppressed findings come back alongside kept ones, and the
   report states how many, where, and why — naming any written without a
   reason.

## Consequences

- **`StaticAnalysis.analyze` returns a result, not a list.** The port's honest
  contract is "what I found *and* what I was told to ignore". A second method
  would have left two ways to call it with one of them lossy.
- **A directive with no reason still suppresses.** Refusing to honour it would
  turn a typo into a blocking finding at the exact moment someone is trying to
  unblock themselves. The pressure to explain lives in the report and in the
  dogfooding test, where a person sees it, rather than in a parser.
- **The dogfooding test caps them.** Without a cap, "the package passes its own
  gate" could be reached by writing `review-ignore` until the findings stopped
  — the failure mode this design guards against, achieved through the test
  meant to prevent it. The cap is 6, and the comment above it says what the
  five in the tree are.
- **It lives in the domain.** Whether a directive covers a finding is a rule of
  code review, testable without a filesystem or a model. This mirrors
  `domain/triage.py`: the syntax is not incidental to the rule, it is the
  rule's interface.
- **Running the agent on itself found more defects than suppression hid.** The
  first dogfooding run reported 4 CRITICAL and 29 HIGH. Twenty-eight were
  *fixed* — two analyzer precision bugs that would have misfired on any Python
  codebase, eight handlers that genuinely discarded their error, three
  over-complex functions. Five were suppressed. That ratio is the argument for
  the mechanism and for the test that bounds it.
