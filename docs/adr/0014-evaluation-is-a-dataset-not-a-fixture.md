# 0014 — Review quality is measured against a dataset, not asserted in fixtures

Status: Accepted
Date: 2026-08-09
Level: [12](../roadmap/level-12/spec.md)

## Context

Every analyzer test in this repository asserts that one fixture produces one
finding. That verifies a rule. It does not measure a suite, and it cannot
answer the question a team asks before turning the gate on: when this reports a
vulnerability is one there, and when it stays quiet is the file clean.

The gap is not academic. Two false positives were fixed in Level 11 — the N+1
rule firing on `dict.get`, an unbounded DES pattern that matched `overrides(` —
and both were found by a person reading a report. Nothing stopped either from
returning. In the other direction, Level 7 replaced the agent loop and Level 8
rewrote the system prompt; both were verified by asserting on the *shape* of
the output, and neither could have detected a change that made reviews worse.

Coverage does not help. It proves the code ran.

## Decision

Review quality is measured against an annotated dataset held as data on disk —
`evaluation/cases/*.yaml` beside `evaluation/fixtures/` — graded by a scoring
rule that lives in the domain, and gated in CI by a floor on precision, recall
and F1.

Four properties make it a dataset rather than a second fixture set.

**It is data, not Python.** A case written as a test function can only be run
by the test runner and can only be extended by someone editing this repository.
Cases on disk can be generated, contributed, and eventually exported from a
real review.

**Scope defaults to grading everything.** A case that says nothing takes
responsibility for every finding the suite produces on its fixture. Narrowing
that scope is possible and is *counted*: the report states how many findings
were ungraded and which rules they came from. This is the same bargain
suppression makes at Level 11, made the same way — the narrow answer is
available, and it costs a number in the report.

**The floors are the measured baseline minus a margin, not an aspiration.** A
floor the suite does not meet leaves CI red on day one and trains everyone to
skip the job. Raising the floor is work; lowering it to make a build green is
the thing this exists to prevent.

**A case that cannot be graded is not a case that scored zero.** An analyzer
that raises exits 2 — "the measurement could not be taken" — rather than 1,
which means "the measurement came out low". Conflating them makes the gate
unusable, because a pipeline cannot tell a bad score from a broken harness.

## Consequences

The dataset ships with a known false negative. `find_by_name` in the SQL
injection fixture builds its query into a local and executes the local, and the
SAST rule is a single-line pattern that misses it. The case states the defect
anyway, so the committed baseline is recall 0.89 rather than 1.00. A dataset
that only states what the suite already finds measures nothing, and the first
thing the instrument did was find something.

Adding a rule to an analyzer now has a cost it did not have before: on the
`clean-module` case, which grades everything and expects nothing, a rule that
fires on ordinary code is a false positive and moves the number.

The harness grades static analysis only. It drives the `StaticAnalysis` port,
so it is model-free, network-free, and fast enough to run on every push.
Scoring the model's prose needs a judge and is deliberately not attempted here.
When Level 15 introduces specialist agents they arrive behind a port too, and
the same harness grades them without changing shape.
