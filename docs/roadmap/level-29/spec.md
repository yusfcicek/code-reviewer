# Level 29 — Does the prompt ask for what the checks enforce?

## Problem statement

Level 21 built five checks over the reviewer's prose and Level 25 made them
measurable on a corpus of twenty-four recorded reviews. The corpus scores 1.00
on every check.

Nobody has ever asked the other half of the question: **does the prompt tell the
model to do the things the checks grade it on?**

The answer, taken from the shipped `SYSTEM_TEMPLATE` by substring search, is no
for three of the five:

| check | what it enforces | in the prompt |
|---|---|---|
| `citations_are_grounded` | every `path:line` names this file and a line that exists | nothing: `cite`, `citation`, `path:line` and `line number` are all absent |
| `the_prose_claims_no_verdict` | the prose does not say the change is approved or blocked | nothing: `verdict`, `approved`, `decide` are all absent |
| `severity_claims_are_backed` | a CRITICAL in the prose has a finding behind it | partial: severity words are demanded, backing is never mentioned |
| `severe_findings_are_mentioned` | every critical finding is named | partial: "List specific findings or 'None'" |
| `required_sections_are_present` | five headings appear | yes: the output format demands them |

And the reverse direction is unmeasured too. The prompt's output format demands
**seven** headings; `REQUIRED_SECTIONS` names five. A model that drops the
Architectural Review Summary and the whole Refactoring Roadmap passes every
check this repository has.

Two failure modes, one shape:

> **An unbacked check grades the model on a rule it was never given. An
> ungoverned demand asks for output nobody ever looks at.**

The first is unfair in a way that matters practically: when the narration score
falls, the fix is assumed to be in the prompt, and for three of these five
checks there is nothing in the prompt to fix.

Capability addressed: **C-36** — the prompt and the checks over its output are
one artefact and are kept consistent. Sourced from Level 21's non-goals
(*"tuning the prompt against the checks"*), read as far as it can be read
without a model.

## Goals

1. Every narration check states, in code, the instruction the prompt must carry
   for grading against it to be fair.
2. The alignment between prompt and checks is **measured deterministically** —
   two texts in, a report out — and gates the build.
3. Every heading the prompt's output format demands is either checked or
   carries a written reason it is not.
4. The gaps this measurement finds are closed: the prompt is made to say what
   the checks enforce.
5. What cannot be answered without a model endpoint is named plainly, and not
   approximated.

## Non-goals

- **Tuning the prompt.** Changing wording and measuring what the model then
  writes needs an endpoint on every iteration. This level makes the prompt
  *state* what is graded; whether the model then obeys is a different
  measurement and it is named as one.
- **Judging prompt quality.** Whether an instruction is well phrased is not
  arithmetic. Whether it is *present* is.
- **A sixth narration check**, unless the ungoverned-headings answer is that one
  is owed — and then it is owed with a demonstration, like every other check.
- **Grading the specialists' prompts against the generalist's checks.** A
  specialist writes a section, not a review; the checks are about a review.
- **Re-recording the corpus.** Every case is already stale against the current
  fingerprint and says so. Adding instructions does not make that worse, and
  re-recording needs an endpoint.

## Behavioural contracts

### C-1 — A check declares the instruction it needs
Beside each check, the phrases the prompt must contain for that check to be
fair. Declared as data, not prose, so a test can read it.

### C-2 — A check whose instruction is absent is reported as unbacked
By name, with what was looked for. Not counted, not averaged: three unbacked
checks is a list of three things to write, and an aggregate would hide which.

### C-3 — A demanded heading with no check is reported as ungoverned
Unless it carries a written reason, in the same place, in the same shape as
`fix_recipes.DECLINED`: this project's answer to "we decided not to" is a
constant with the reason in it.

### C-4 — The measurement takes no model and no network
Prompt text in, report out. It is exactly as reproducible as the two files it
reads, and it runs in the same second as the unit tests.

### C-5 — The gate is exact, not statistical
Every other measurement here carries a Wilson interval because it is a sample.
This one is not a sample: it is a fact about two texts. A floor and an interval
would be borrowed authority (ADR 0027 applies to samples and this is not one).

### C-6 — What needs an endpoint is printed
Whether the model *obeys* an instruction is not decidable from the prompt. The
report says so in the same words every time, so the number is never read as
"the prose is good".

### C-7 — A prompt edit that drops an instruction fails the build
The reason this is a level rather than a note: the prompt is edited far more
often than the checks are.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | Every check in `CHECKS` has a declared expectation | Unit test |
| AC-2 | An expectation absent from the prompt is reported unbacked, by name | Unit test |
| AC-3 | Every heading the prompt demands is checked or declined with a reason | Unit test |
| AC-4 | A declined heading with an empty reason is refused | Unit test |
| AC-5 | The report names what needs an endpoint | Unit test |
| AC-6 | The measurement runs with no model, no network and no clock | Architecture + unit test |
| AC-7 | `ai-code-review-eval --alignment` exits 0 / 1 / 2 on the three outcomes | CLI test |
| AC-8 | Both pipelines run it, pinned like the other four | `test_ci_gates.py` |
| AC-9 | The shipped prompt has no unbacked check and no ungoverned heading | Baseline test |
| AC-10 | The three unbacked checks are closed by editing the prompt | The level's report |
| AC-11 | The six checks stay green, coverage holds, all four floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval ×5 |

## Decisions taken

**D-1 — The expectation is a list of phrases, not a sentence.** A check declares
literal strings the prompt must contain. Anything cleverer — a model asked
whether the prompt implies the rule, an embedding similarity — puts an
unmeasured judgement in the middle of a measurement, which is the thing Level 21
refused an LLM judge for.

**D-2 — Absent instructions are listed, never scored.** There is no honest
denominator. "Three of five checks are unbacked" is a fact; "alignment is 0.40"
is a number pretending to be one.

**D-3 — The prompt is edited to match the checks, not the other way round.**
Every one of these five checks earns its place from a real failure mode. A check
deleted to reach alignment would be alignment bought by measuring less.

**D-4 — No interval.** Stated as a decision because every other measurement here
has one, and the absence would otherwise read as an oversight.

**D-5 — What an endpoint would buy is written down, once.** Two questions need
one: whether an added instruction changes what the model writes, and whether the
recorded corpus still describes the current prompt. Both are named in the report
and neither is guessed at.
