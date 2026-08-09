# Level 21 — Grading the reviewer's prose

## Problem statement

Level 12 built an evaluation harness and this repository has quoted its numbers
ever since: precision 1.00, recall 1.00, F1 1.00 over eleven cases. Every one of
those numbers is about the **analyzers**.

The model's output — the thing an LLM is actually for, and the thing a prompt
edit changes — is measured by nothing. Level 12 said so in its own non-goals:
*"Evaluating the model's prose. The reviewer's narration is unstructured."* Then
[`capability-sources.md`](../capability-sources.md) recorded C-02 ("LLM
application evaluation, monitoring, continuous optimisation") and C-03
("regression detection across model or prompt change") as closed by Level 12.

Both claims are half true, and half of a claim about measurement is the shape of
claim this repository exists to refuse. The self-review of levels 12–20 found
three documentation-overstates-code defects; this is a fourth, and it is in the
roadmap rather than in the README.

Concretely, today:

- **A prompt edit ships unmeasured.** Level 20 records *which* prompt produced a
  review — the fingerprint. Nothing says whether the review got better or worse.
- **A model swap ships unmeasured.** Same fingerprint, different model, no
  signal at all.
- **The prose is unchecked against the facts it is written about.** A review
  that names `src/auth.py:412` when the diff touched forty lines of
  `src/app.py` is wrong in a way no test would notice, and it is the failure
  mode a language model actually has.

Capabilities addressed: **C-02** and **C-03**, completed. **C-21** (new): the
narration is graded against the brief it was written about.

## Goals

1. A review's prose is graded — deterministically, offline, in CI — against the
   facts of the brief it was written about.
2. The grading measures *groundedness and discipline*, not eloquence.
3. A corpus of recorded reviews, on disk beside the analyzer cases, extendable
   by anyone who can write a YAML file.
4. A floor in CI, the way Level 12's floors work: below it the command exits
   non-zero, and lowering one is a deliberate act.
5. A score is tied to the prompt fingerprint that produced it, so "measured
   under a different prompt" is a fact the report states rather than a thing a
   reader has to remember.

## Non-goals

- **An LLM judge.** Grading generated text with generated text puts an
  unmeasured model in the position of measuring one. It also needs a model
  endpoint in CI, which Level 12 refused for the same reason. Every check here
  is code, and every check's verdict can be recomputed by hand from the case
  file (decision D-1).
- **Scoring style, fluency or helpfulness.** Not measurable without a human
  panel, and a number invented for them would be worse than no number.
- **Calling the model in CI.** The corpus holds *recorded* outputs. A live mode
  exists behind a flag, for a developer with an endpoint, and CI never uses it
  (decision D-2).
- **Changing what the reviewer says.** This level builds the instrument. Tuning
  the prompt with it is the next level's argument, exactly as Level 12 built the
  analyzer scoreboard without tuning a rule.
- **Grading the committee's routing or budget.** Level 15 owns those and they
  are already deterministic.
- **A statistically meaningful corpus.** Twelve recorded reviews is not a
  sample. It is enough to catch a prompt change that breaks the output format,
  which is the regression that actually happens, and the honest word for it
  stays "corpus" rather than "benchmark".

## Behavioural contracts

### C-1 — Every check is deterministic and offline (C-02)
Given a case file and a recorded review, the grade is a pure function. No
network, no model, no clock, no randomness. Two runs of the harness on one
corpus produce byte-identical reports.

### C-2 — The prose is graded against the brief, not against an ideal (C-21)
A case carries the facts the review was written about: the file path, the lines
the diff touched, the findings the analyzers produced. A check asks whether the
prose is consistent with *those*, which is answerable, rather than whether it is
a good review, which is not.

### C-3 — A citation that does not exist is the headline defect (C-21)
Every `path:line` reference in the prose must name a file in the brief and a
line that exists in it. This is the hallucination that matters for a code
review: a reader who checks one citation and finds nothing there stops
believing the whole report, correctly.

### C-4 — The prose may not claim a verdict (C-19)
[ADR 0004](../../adr/0004-findings-drive-the-gate.md) says findings decide and
prose warns. A review that writes "this pipeline will be blocked" or "approved"
is claiming an authority it does not have, and Level 20 made that unrepresentable
in the *record*. Here it becomes measurable in the *text*.

### C-5 — A severity in the prose must be backed by a finding (C-19)
"CRITICAL" in the narration with no critical finding in the brief is the
narration inventing evidence. The reverse — a critical finding the prose does
not mention — is a separate check, because it is a different failure.

### C-6 — Structure is checked because a consumer parses it (C-03)
The gate no longer reads the prose, but the report renderer and a human both
expect the sections the prompt asks for. A prompt edit that drops a section is
the single most likely regression, and it is trivially detectable.

### C-7 — Nothing secret-shaped survives grading (C-18)
The corpus holds recorded model output, which is text produced from real files.
A case whose recorded review contains a credential-shaped string fails to load,
so the corpus cannot become the thing this project spent four levels keeping out
of its other artefacts.

### C-8 — A score names the prompt it was measured under (C-20)
Each case records the prompt fingerprint its review was produced under. The
report states how many cases were recorded under the *current* fingerprint and
how many were not: a floor held by stale recordings is a floor holding nothing.

### C-9 — The measurement cannot be taken quietly (C-01)
A case that cannot be read, a fixture that is missing, a check that raises —
each exits `2`, distinct from "the score was below the floor", which exits `1`.
Level 12's rule, applied to the second harness.

### C-10 — The instrument never touches a review
Nothing in this level is imported by `ReviewService`. A grader that can change
a verdict is not an instrument.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A `path:line` citation absent from the brief is a failed check | Unit test |
| AC-2 | A citation present in the brief passes | Unit test |
| AC-3 | A line number past the end of the cited file fails | Unit test |
| AC-4 | "will be blocked"/"approved" in the prose fails the verdict check | Unit test |
| AC-5 | A severity word with no matching finding fails | Unit test |
| AC-6 | A critical finding the prose never mentions fails its own check | Unit test |
| AC-7 | A missing required section fails, and the report names which | Unit test |
| AC-8 | Two runs over one corpus produce identical reports | Property test |
| AC-9 | A case whose review contains a credential-shaped string refuses to load | Unit test |
| AC-10 | The report states how many cases are stale against the current fingerprint | Unit test |
| AC-11 | `--narration` grades the shipped corpus and holds its floors | CLI test |
| AC-12 | A broken corpus exits `2`; a low score exits `1` | CLI test |
| AC-13 | The shipped corpus scores at or above the committed floor | Test over the real corpus |
| AC-14 | No module in this level is imported by the review path | Architecture test |
| AC-15 | The six checks stay green, coverage holds | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — The grader is code, not a model.** An LLM judge is the industry answer
and it is not the one taken. It would need an endpoint in CI, it would make the
score depend on a second unmeasured model, and it would produce a number nobody
can recompute by hand. Every check here is a function over the case and the
text, and every failure names the exact substring that caused it.

**D-2 — The corpus holds recorded output.** A harness that calls the model
grades a different text every run, which measures the model's variance and calls
it review quality. Recording the output once and grading it every time is what
makes a *regression* detectable: the text is fixed, the checks are fixed, so a
change in the score is a change in the checks or in what somebody recorded.

**D-3 — Groundedness over quality.** "Is this review well written" is not
answerable here. "Does this review cite a file the brief does not contain",
"does it claim a severity nothing supports", "does it claim to have blocked the
pipeline" — all answerable, all exactly the failure modes a language model has,
and all recomputable by a reader.

**D-4 — Stale is reported, not hidden.** A case recorded under an old prompt is
still worth grading — the checks are about groundedness, not about the prompt —
but a floor held entirely by old recordings is a floor holding nothing. The
count is in the report, and re-recording is a documented command rather than a
folk process.

**D-5 — A second dataset, not a second column on the first.** Level 12's cases
are `(fixture, expected findings)`. These are `(brief, recorded prose)`. Forcing
one loader to serve both would make each read the other's optional keys, which
is the same argument Level 14 made for not reusing Level 13's index — and the
same conclusion.
