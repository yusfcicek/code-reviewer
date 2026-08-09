# Level 23 — Documentation that cannot quietly lie

## Problem statement

The roadmap's own working agreements have carried this line since Level 0:

> **Docs** — Documentation may never claim behaviour the code does not have.

It is enforced by nobody. Every level since has been reviewed by a suite that
reads Python and treats Markdown as a file to skip, and the agreement has held
only because somebody happened to notice. Three times it did not: the
self-review of levels 12–20 found three documentation-overstates-code defects,
one of them a docstring in `governance/identity.py` claiming a drift test that
did not exist. Nothing in the pipeline that reviews this repository could have
found any of them.

The reason it matters more than a stale sentence normally would:

**Prose outranks code in the reader's head, and outranks it completely in a
model's.** A language model reading this repository to answer a question about
the gate will read `README.md` before it reads `gate.py`, and will believe the
README. A human skims the same way. So a README that describes an old signature
is not a cosmetic defect — it is a wrong answer, served with confidence, to
every future reader including the agent that reviews the next merge request.

Concretely, today:

- **A function's signature changes and the document describing it does not.**
  The diff is reviewed, the review passes, and `README.md` keeps naming
  parameters that no longer exist.
- **A symbol is renamed or deleted and the documents that name it survive.** The
  reference is now dead. Nothing resolves it, so nothing notices.
- **A document explains behaviour without naming a single symbol.** This is the
  common case and the one no token match reaches: a paragraph about how
  suppression works, three levels after suppression changed.

Capability addressed: **C-23** (new). Its source is not one of the three role
descriptions — it is this project's own Level 0 agreement, and the three defects
that proved the agreement was decorative.

## Goals

1. Two new rule namespaces whose subject is **the repository's prose measured
   against its code** — `DOCS` for what resolves, `DRIFT` for what a model
   selected. They are two namespaces rather than two flags on one because
   Level 20's attribution table is keyed by namespace: split this way, "a
   retrieved candidate can never block" is a row in a table rather than a rule
   somebody has to remember.
2. **Deterministic checks** that resolve a documented claim against the source
   tree and report it when it does not resolve.
3. **Retrieved candidates** for the relationships no token match reaches: the
   documents semantically tied to the changed code, which the change did not
   touch.
4. The two are **separated everywhere they appear** — in the finding, in the
   record, in the report — because one is verified and the other is not.
5. Both namespaces enter the evaluation dataset, and the retrieved tier is
   measured on its own terms rather than against a precision floor it cannot
   hold.

## Non-goals

- **Blocking a merge on any finding from either namespace.** Not in this
  level. The rules are unmeasured, and this repository's rule is that a floor is earned by a level
  that measured it (Level 12's D-4). Every one of them is a warning until a
  later level has the data to argue otherwise.
- **Writing the documentation.** No suggested prose, no generated paragraph, no
  Level 22 recipe for English. A model-authored sentence in a README is a claim
  nobody reviewed, in the exact position this level exists to distrust.
- **Proving a document wrong.** The retrieved tier claims a section is **worth
  re-reading**, never that it is false. That distinction is the level's entire
  safety argument, and it is enforced by attribution rather than by wording:
  the producer is an `AGENT`, and [ADR 0022](../../adr/0022-a-verdict-that-can-be-audited.md)
  already makes a blocking verdict citing one impossible to construct.
- **Grading writing.** Not a style linter. Tone, length, grammar and heading
  structure are somebody's taste; a dead symbol reference is a fact.
- **Auditing the whole repository on every run.** The trigger is a change. A
  document unrelated to the diff is not scanned, for the same reason a file
  unrelated to the diff is not analyzed.
- **A second index.** Levels 13 and 16 built chunking, BM25, embeddings, rank
  fusion and MMR. Documents become chunks in that corpus or this level does not
  ship.
- **Non-Python symbol resolution.** The symbol index is built from the Python
  tree. A document naming a shell function is out of scope and says so rather
  than guessing.

## Behavioural contracts

### C-1 — The trigger is a change, and the scan runs both ways
A code change is checked against the documents that describe it. A document
changed in the same diff is checked against the code it describes. A run with
neither produces nothing.

### C-2 — A deterministic finding is proved by the change, or it is not reported
Every Tier A rule ends in a lookup that succeeds or fails against the parsed
source tree, **and in a name the change is responsible for**. A name the
repository never defined — a library call, a Kubernetes noun, another tool's
flag — is not a defect however unresolvable it is; the diff is the only
available evidence that a name was this project's to keep. A rule that cannot complete its lookup — an unparseable file, a
symbol index that did not build — reports nothing rather than guessing, and the
inability is recorded as a degradation (the pattern self-review finding 12–20
S-02 established).

### C-3 — Nothing here blocks
Every `DOCS` and `DRIFT` finding carries a severity at or below the gate's
warning threshold in this level. Neither namespace ever appears in
`blocking_issues`, and a test asserts it.

### C-4 — A retrieved candidate can never decide anything
Tier B findings carry the `DRIFT` namespace, which the attribution table
registers as `ProducerKind.AGENT`. Level 20's `DecisionRecord` then makes the
rest true by construction — it already refuses a blocking verdict that cites a
non-deterministic producer. This level adds the row and the test that pins it.

### C-5 — Identifiers, never content
A finding from either namespace names a path, a line, a heading anchor and a
symbol. It does not quote the sentence, the paragraph or the code around it. Sixth level with
that rule, and the first where the quoted material would be prose a person
wrote.

### C-6 — A document the diff already updated is not reported
Updating the README in the same merge request is the behaviour this level wants.
Reporting it would train people out of it.

### C-7 — Retrieval failure costs the candidates and nothing else
No index, no embedding backend, no budget: Tier B contributes nothing, the
review publishes, and the report says the tier did not run. Observability may
never fail the review it observes.

### C-8 — The model is asked one bounded question per candidate, and capped
One candidate, one question, one of three answers. The number of candidates that
reach the model in a run is bounded by a constant, and what the bound dropped is
stated in the report rather than silently truncated.

### C-9 — The tiers are separated in the report
Two sections, two headings, and the unverified one is labelled unverified. A
reader who skims must not be able to mistake a retrieved candidate for a
resolved fact.

### C-10 — Recorded
The decision record gains both namespaces' findings by rule, location and
namespace. The retrieved tier's entries carry the model and prompt fingerprint that produced
them, which Level 20 already records for the run.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A document naming a symbol **the change removed** yields `DOCS.DEAD_REFERENCE`, and one it never owned yields nothing | Domain test |
| AC-2 | A backtick token that is not a symbol shape (`async`, `false`) yields nothing | Analyzer test |
| AC-3 | A document showing `f(a, b)` when the source defines `f(a, b, c)` yields `DOCS.SIGNATURE_MISMATCH`, for a symbol the change touched or in a document the change edited | Domain test |
| AC-4 | A document naming a `--flag` or environment variable **the change removed** yields `DOCS.UNKNOWN_OPTION`; another tool's flag yields nothing | Domain test |
| AC-5 | A fenced Python block that does not parse yields `DOCS.BROKEN_EXAMPLE` in an edited document, and nothing in an untouched one | Domain test |
| AC-6 | A docstring documenting a parameter the signature does not have yields `DOCS.DOCSTRING_DRIFT` | Analyzer test |
| AC-7 | A docstring documenting `Raises:` for an exception never raised yields `DOCS.DOCSTRING_DRIFT` | Analyzer test |
| AC-8 | A correct document over the same code yields nothing | Analyzer test |
| AC-9 | A document updated in the same diff is not reported | Service test |
| AC-10 | Markdown chunks by heading, and a document with no heading still chunks | Chunker test |
| AC-11 | A changed function retrieves the document section describing it without naming it | Retrieval test |
| AC-12 | Every `DRIFT` finding is attributed to an `AGENT`, and `DOCS` to an analyzer | Unit test |
| AC-13 | No `DOCS` or `DRIFT` finding reaches `blocking_issues` | Gate test |
| AC-14 | No finding from either namespace contains a sentence from the document it is about | Unit test |
| AC-15 | With the retriever unavailable, the review publishes and the report says Tier B did not run | Service test |
| AC-16 | The candidate cap is applied and what it dropped is stated | Service test |
| AC-17 | The report renders the tiers under separate headings, the second labelled unverified | Renderer test |
| AC-18 | The record carries rule, location and tier, and no prose | Unit test |
| AC-19 | `DOCS` is in `REQUIRED_NAMESPACES` and the dataset exercises it | Dataset test |
| AC-20 | The six checks stay green, coverage holds, both existing eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval ×2 |

## Decisions taken

**D-1 — Two tiers, and the separation is the level.** Everything a token match
can resolve is a fact and is reported as one. Everything else is a candidate
produced by a model and is reported as a place to look. Merging them would give
the whole namespace the weaker tier's credibility, which is how a reviewer
learns to skim past a section.

**D-2 — Reuse the retrieval stack.** Documents are chunks. `chunk_markdown` is
the sibling of `chunk_source`, and the fusion, diversification and index built
in Levels 13 and 16 are the parts that make "any relationship, deeply scanned"
achievable at all. A second retrieval path would be a second thing to keep
correct.

**D-3 — Warn-only in this level.** A rule nobody has measured does not get to
break a build. Level 12 built the harness that turns a measurement into a floor;
this level supplies cases to it and leaves the floor to whoever reads them.

**D-4 — Diff-driven, both directions.** Scanning the whole documentation tree on
every merge request would report the same twenty findings forever, and a report
that repeats is a report nobody opens. The change is what makes a document worth
re-reading now.

**D-5 — The model answers, it never authors.** One narrow question per
candidate, three possible answers, no free prose entering the report as a
finding's body. What the model contributes is a selection, and Level 20's
attribution already prices a selection correctly.

**D-6 — Identifiers, never content — including English.** Five levels have kept
source text out of memory, traces, records and comments. A README paragraph is
somebody's writing, quoted back to them in a machine's report; the reason is now
better than it was.
