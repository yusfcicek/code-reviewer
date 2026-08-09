# 0023 — The prose is graded by code, not by a model

Status: Accepted
Date: 2026-08-09
Level: [21](../roadmap/level-21/spec.md)

## Context

Level 12 built an evaluation harness and every number this repository quotes
about review quality comes from it: precision, recall, F1 over the shipped
cases. All of them are about the **analyzers**.

Level 12 said so, in its own non-goals: *"Evaluating the model's prose. The
reviewer's narration is unstructured."* The roadmap then recorded C-02 ("LLM
application evaluation, monitoring, continuous optimisation") and C-03
("regression detection across model or prompt change") as closed by that level.

Half of a claim about measurement is the shape of claim this repository exists
to refuse, and this one was in the roadmap rather than in the README — which
made it harder to see and no less wrong.

Meanwhile Level 20 records *which* prompt produced a review, down to a digest.
Nothing said whether the review that prompt produced was any good.

## Decision

### The grader is code

An LLM judge is the industry answer and it is not the one taken.

It would need a model endpoint in CI — the thing Level 12 refused, for the
reason that a measurement whose instrument is a network call is a measurement
that fails on a bad afternoon. It would make the score depend on a second,
unmeasured model. And it would produce a number nobody can recompute: "the
judge said 7/10" is not evidence, it is a citation of an oracle.

Every check here is a function over the case and the text. Every failure names
the substring that caused it. A reader who disagrees with a score can find the
exact sentence and argue about that instead.

### Groundedness, not quality

"Is this a good review" needs a human panel. What is answerable without one:

- does the prose cite a file the review was not looking at, or a line past the
  end of the file it was;
- does it claim a verdict, when [ADR 0004](0004-findings-drive-the-gate.md) says
  findings decide and prose warns;
- does it write CRITICAL with nothing critical behind it;
- does it stay silent about a critical finding that is;
- does it carry the sections the prompt asks for.

Those are the failure modes a language model actually has. Eloquence is not
measured, and a number invented for it would be worse than no number.

### The corpus holds recorded output

A harness that calls the model grades different text every run, which measures
the model's variance and reports it as review quality. Recording once and
grading every time is what makes a *regression* detectable: the text is fixed
and the checks are fixed, so a change in the score is a change in a check or in
what somebody recorded.

The shipped fourteen are **authored rather than captured**, and
[the corpus README](../../evaluation/narration/README.md) says so in its first
paragraph. They exercise each check; they are not evidence about how often a
real model hallucinates. Every one of them carries no prompt fingerprint, so the
report counts all fourteen as stale — which is the column doing its job rather
than a defect.

### A case may declare the check it is built to break

Five of the fourteen are deliberately bad reviews, and each names the check it
should fail. What is scored is **agreement with the declaration**, not the raw
pass rate.

Without that, a corpus of clean reviews cannot tell a working check from a check
that returns `True` unconditionally — and the second one scores better.

### The instrument is not in the review path

`tests/unit/test_architecture.py` asserts that nothing which runs during a
review imports the grader, and that the evaluation entry point does. A check
that could influence what gets published would be measuring a system that knows
it is being watched.

## Consequences

`ai-code-review-eval --narration` grades the corpus, holds a floor, and exits
`1` for a low score and `2` for a corpus it could not read — the same three
codes, meaning the same three things, as the analyzer harness.

A prompt edit now has a number attached to it. Not a good one yet: with an
authored corpus the honest claim is "the checks work and the format is pinned",
and it becomes a claim about the model on the day somebody records real output
under a known fingerprint. The recording procedure is documented rather than
folklore.

C-02 and C-03 are now genuinely closed, and `capability-sources.md` names both
levels instead of one.
