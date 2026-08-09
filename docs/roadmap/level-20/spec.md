# Level 20 — Governance, explainability & compliance

## Problem statement

Nineteen levels have produced a system that decides whether a merge may
proceed. Nothing in it can answer, six months later, *why*.

A finding names its rule and its location. It does not name what produced it,
under which rule set, with which model, from which prompt, on the strength of
which retrieved evidence. The merge-request comment carries some of that in
prose, and a comment can be edited, deleted, or lost with the project.

- **The verdict has no record.** The pipeline blocked, someone overrode it, and
  the only artefact is a comment thread. In a bank that is the question an
  auditor asks first and the one this system currently cannot answer (C-18).
- **The strongest claim this architecture makes is unproven.**
  [ADR 0004](../../adr/0004-findings-drive-the-gate.md) says the gate decides
  from findings and never from the model's prose. Nineteen levels have kept
  that true by construction and by review. Nothing *checks* it — and a claim
  that matters to a regulator should be machine-checkable rather than
  argued (C-19).
- **Nothing is versioned.** Level 12 measures review quality; Level 16 records
  what ran. Neither records *which prompt* or *which model* produced a given
  review, so a change in behaviour cannot be attributed to the change that
  caused it (C-20).
- **Cost is counted per run and then discarded.** Level 15 exports per-agent
  tokens and tool calls to a metrics file that is overwritten by the next
  review.

Capabilities addressed: **C-18, C-19, C-20**.

## Goals

1. Every review produces one immutable record: what was decided, by what, under
   which versions, and on the strength of which evidence.
2. A finding carries provenance — the producer that made the claim.
3. The claim that a verdict is never a model's opinion is **enforced**, not
   asserted: a record whose blocking findings were produced by anything but a
   deterministic analyzer is refused at construction.
4. The identity of the run — model, prompt fingerprint, policy version, package
   version, rule set — is recorded with the decision.
5. The record is written where an auditor can read it, and contains nothing
   from the code under review.

## Non-goals

- **A compliance framework.** No control catalogue, no SOC 2 mapping, no
  attestation format. Those are an organisation's, and inventing one here would
  be guessing at somebody else's obligations.
- **Signing or an append-only store.** A record whose integrity has to survive
  a hostile operator needs a key nobody in this repository holds and a store
  nobody has chosen. The record is written; where it is kept, and how its
  integrity is protected, is a deployment decision — the sink is a port so it
  has somewhere to go.
- **A second copy of the trace.** Level 16 records *how long, in what order*.
  This records *what claim came from where, under which versions*. Where they
  overlap, the record cites the trace by id rather than reproducing it.
- **Explaining the model's reasoning.** "Why did the model say that" is not
  answerable, and a system that pretends otherwise is worse than one that does
  not try. What is answerable — which agent said it, on what budget, with which
  retrieved evidence in front of it, and whether it influenced the verdict
  (it did not) — is what gets recorded.
- **Retention, redaction requests, or a deletion path.** Data lifecycle is an
  organisation's policy. The record holds identifiers only, which is what makes
  that policy simple to write.

## Behavioural contracts

### C-1 — Every claim names its producer (C-18)
A `Producer` is a kind (`ANALYZER`, `AGENT`, `TOOL`), a name and a version. A
finding's provenance is its producer plus the evidence it cited.

### C-2 — A blocking verdict may cite only deterministic producers (C-19)
A `DecisionRecord` whose verdict is blocking and whose blocking findings name a
producer of kind `AGENT` is **refused at construction**. This is
[ADR 0004](../../adr/0004-findings-drive-the-gate.md) turned from a design rule
into an invariant: the one claim a regulator would care about most is the one
the type system now enforces.

### C-3 — A record names the run's identity (C-20)
Package version, policy version, model identity, prompt fingerprint, analyzer
rule-set version, and the evaluation baseline the analyzers last scored
against. Enough that two reviews that disagree can be attributed to the change
between them.

### C-4 — A prompt is identified by a fingerprint, not by its text (C-20)
A short digest of the system prompts actually in use. Recording the text would
put instructions in an audit file for no gain; recording nothing would make
"the prompt changed" unprovable.

### C-5 — A record carries identifiers, never content (C-18)
Rule ids, paths, line numbers, severities, counts, citations, span ids,
versions. Never a diff, a file's contents, a finding's evidence line or a
model's prose. Third level with this rule and the same two reasons: an audit
file is read by more people than a merge request, and a diff may contain a
secret.

### C-6 — Suppressions are part of the record (C-19)
Which rules were silenced, where, and the reason written in the source. A
governance record that omits what was turned off is a governance record that
can be gamed by turning things off.

### C-7 — Cost is recorded per agent (C-20)
Tokens allowed, tool calls, duration and failures per specialism, alongside the
decision they contributed to — so "what did this review cost" survives the next
review overwriting the metrics file.

### C-8 — The record is immutable and complete or refused (C-18)
No partial record. A review that failed produces a record saying so, with the
reason; a review that could not be recorded at all is a logged failure and not
a silently missing file.

### C-9 — Writing the record cannot fail the review (C-18)
A sink that cannot write is a warning. Fourth level with this rule: an
accountability feature that can break the thing it accounts for is a liability.

### C-10 — The comment states the accountable facts (C-18)
The merge-request comment gains a short block: the policy version, the model,
the prompt fingerprint, the trace id, and the sentence that matters — that the
verdict came from static analysis. A reader who never opens the audit file
should still be told what decided.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A producer carries kind, name and version, and refuses an empty name | Unit test |
| AC-2 | Provenance carries a producer and the evidence cited | Unit test |
| AC-3 | A blocking record citing an agent-produced finding is refused | Unit test |
| AC-4 | A blocking record citing analyzer findings is accepted | Unit test |
| AC-5 | A non-blocking record may cite anything | Unit test |
| AC-6 | A record with a blocking verdict and no findings is refused | Unit test |
| AC-7 | The run identity records package, policy, model, prompt and rule set | Unit test |
| AC-8 | Two different system prompts produce different fingerprints | Unit test |
| AC-9 | The same prompts produce the same fingerprint across processes | Unit test |
| AC-10 | No field of a real review's record contains the diff | Unit test over the whole path |
| AC-11 | Suppressions appear with their reasons | Unit test |
| AC-12 | Per-agent cost appears | Unit test |
| AC-13 | The record round-trips through JSON | Unit test |
| AC-14 | A sink that raises is logged and the review still exits normally | Unit test |
| AC-15 | The comment carries the accountability block and names the decider | Unit test on the renderer |
| AC-16 | `--audit-path` writes the record; without it nothing is written | Unit test on the CLI |
| AC-17 | The six checks stay green, coverage holds, the eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — The central claim becomes an invariant.** Nineteen levels have kept
"the gate decides from findings, never from prose" true by construction. This
level makes a record that violates it impossible to build. It is the difference
between a design principle and a control, and the difference is exactly what an
auditor is asking about.

**D-2 — Provenance is recorded, reasoning is not.** "Which agent said this, on
what budget, with what in front of it" is answerable and useful. "Why did the
model conclude that" is not, and a system that produces a plausible-sounding
answer to it has manufactured evidence.

**D-3 — A prompt is a fingerprint.** Recording the text would put the system's
instructions into an audit file that is read more widely than the repository,
for no gain; recording nothing would make "the prompt changed between these two
reviews" unprovable. A digest answers the question that is actually asked.

**D-4 — The record cites the trace rather than embedding it.** Two artefacts,
one identifier between them. Copying a forty-span tree into every audit record
would make both harder to read and neither more true.

**D-5 — No signing, and the sink is a port.** Integrity against a hostile
operator needs a key nobody here holds. Saying so is more honest than a
hash-chain that anyone with write access can rebuild, and the port means a
deployment that needs more has somewhere to put it.

**D-6 — The record is built from what the review already produced.** No second
pass, no re-analysis, no extra model call. Anything the record cannot get from
the outcome, the orchestrator's totals and the tracer is a thing this level
does not claim.
