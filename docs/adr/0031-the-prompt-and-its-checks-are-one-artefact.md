# ADR 0031 — The prompt and the checks over its output are one artefact

**Status** Accepted · **Level** 29

## Context

Level 21 built five checks over the reviewer's prose: citations are grounded,
the prose claims no verdict, severity claims are backed, severe findings are
mentioned, required sections are present. Level 25 measured them against
twenty-four recorded reviews. They score 1.00, and a floor holds them.

Nobody had asked whether the prompt tells the model to do any of it. Read by
substring search over the shipped template, the answer for three of the five was
no — `cite`, `citation`, `path:line`, `verdict` and `approved` did not appear in
it anywhere.

Two failure modes, one shape:

> An **unbacked check** grades the model on a rule it was never given. An
> **ungoverned demand** asks for output nobody ever looks at.

The second was there too: the output format demands seven headings and
`REQUIRED_SECTIONS` names five, so a review that dropped the Architectural
Review Summary and the entire Refactoring Roadmap passed every check this
repository had.

The first is the one that costs something practically. When a narration score
falls, the fix is assumed to be in the prompt — and for three of these five
there was nothing in the prompt to fix.

## Decision

**The prompt and the checks over its output are measured against each other, and
the measurement gates the build.**

- Each check declares, in code beside it, the literal phrases the prompt must
  contain for grading against it to be fair.
- Each heading the output format demands is either graded by a check or carries
  a written reason it is not, in the shape `fix_recipes.DECLINED` established.
- And the reverse: a heading the code names, graded or declined, that the prompt
  does not demand is reported too. It is the more damaging direction — a graded
  heading nothing demands fails every review there will ever be — and it is the
  one the level shipped without checking (self-review 29, S-01).
- The comparison is two texts and a substring search. Anything cleverer — a
  model asked whether the prompt implies the rule, a similarity over embeddings
  — would put an unmeasured judgement inside a measurement, which is precisely
  why Level 21 refused an LLM judge.

**No interval and no floor.** Every other measurement here carries a Wilson
interval because it is a sample of a larger population. This one is not a
sample: it is a fact about two texts that ship together. "Three of five checks
are unbacked" is a list of three things to write; `0.40` would be a number
pretending to be a measurement, and ADR 0027 would be borrowed authority.

**The prompt is edited to match the checks, not the other way round.** Every one
of the five earns its place from a real failure mode a model has. A check
deleted to reach alignment would be alignment bought by measuring less.

## Consequences

The three unbacked checks are closed by a section of the prompt that states what
is graded. `ai-code-review-eval --alignment` exits 1 if a future edit removes
one, or if a name in the code has no section behind it. Exit 2 is reserved for
the code contradicting itself rather than the prompt: a decline with no reason,
or a heading that is both graded and deliberately ungraded. A declined heading
the prompt stopped demanding is a gap and not an unmeasurable state — the
measurement was taken and the answer is known.

**What the comparison is, exactly.** It asks whether the sentence is *there*. A
rewrite that means the same thing in other words reports unbacked, and the fix
is to add the wording beside the check. That is the price of refusing an
unmeasured judgement in the middle of a measurement, and the alternative — a
model asked whether a paraphrase counts — is the thing this ADR exists to
avoid. Whitespace is flattened before comparing, because a phrase that wraps
across two lines is still the phrase.

**What still needs a served model, named rather than approximated:**

| question | why the prompt cannot answer it |
|---|---|
| Does the model *obey* an instruction that is present? | Requires generating reviews and grading them. That is prompt tuning, and it needs an endpoint on every iteration. |
| Does a recorded review still describe what this prompt produces? | The corpus reports every one of its twenty-four cases as stale against the current fingerprint. Re-recording needs an endpoint. |

Both are printed by the report on every run, in the same words, so the result is
never read as a verdict on the prose. This measurement says the prompt *asks*
for what is graded. It says nothing about whether the answer is any good.
