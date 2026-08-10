# ADR 0025 — Two tiers, and the weaker one is a separate namespace

**Status** Accepted · **Level** 23 · **Supersedes** nothing ·
**Depends on** [0004](0004-findings-drive-the-gate.md),
[0022](0022-a-verdict-that-can-be-audited.md)

## Context

The roadmap has carried this line since Level 0: *documentation may never claim
behaviour the code does not have.* Nothing enforced it. The analysis suite reads
Python and skips Markdown, so the agreement held only when somebody noticed —
and three times nobody did, including a docstring in `governance/identity.py`
that claimed a drift test which did not exist.

It matters more than a stale sentence normally would because **prose outranks
code in the reader's head, and outranks it completely in a model's.** An agent
answering a question about this repository reads the README before it reads the
module, and believes the README. A stale sentence is a wrong answer served with
confidence to every future reader, including the reviewer of the next merge
request.

Checking it well needs two capabilities that do not sit together:

1. **Resolution.** A document names `create_app`; the tree either defines it or
   does not. Arithmetic, and provable.
2. **Relation.** A document explains how suppression works without naming a
   single symbol, and suppression just changed. This is the common case, the one
   the request for this level actually described, and no parser reaches it.

The second needs retrieval and a model. The first must not.

## Decision

**Two tiers, in two rule namespaces, registered separately in Level 20's
attribution table.**

- `DOCS.*` — produced by resolution against the parsed tree. Registered as
  `ProducerKind.ANALYZER`.
- `DRIFT.*` — produced by retrieving document sections related to the change and
  asking a model one narrow question about each. Registered as
  `ProducerKind.AGENT`.

The split is not cosmetic and it is not primarily about presentation. Because
[ADR 0022](0022-a-verdict-that-can-be-audited.md) makes a `DecisionRecord`
refuse a blocking verdict that cites a non-deterministic producer, registering
`DRIFT` as an agent is the *entire* implementation of "a retrieved candidate can
never block". No new rule, no gate exception, no reviewer discipline. One row in
a table, and a test that pins it.

Two further decisions follow from the first tier's own failure mode.

**Every rule is scoped to what the change proves.** The first implementation
resolved every backtick in every document against the tree and produced
twenty-five findings in this repository's README, of which nearly all were
wrong: `hashlib.md5` and `yaml.safe_load` are library calls, `ConfigMap` is a
Kubernetes noun, `--cov` is pytest's flag, `id_rsa` is a filename. In text,
none of those is distinguishable from a symbol this project once had and lost.
The **diff** distinguishes them — a name it removed is a name the repository was
responsible for. So `ChangeScope` is not an optimisation; it is what makes each
rule a fact rather than a resemblance.

**Nothing in this level blocks, in this level.** Both tiers emit at or below
`Severity.LOW`. The rules are newly measured and Level 12's D-4 says a floor is
earned by the level that measured one; a later level with data may argue
otherwise.

## Consequences

**A finding is either checkable or labelled unverified, and the report never
mixes them.** Two blocks, the second saying so in words, because a reader who
cannot tell them apart will either over-trust the second or stop reading the
first.

**`DOCS` gets a corpus; `DRIFT` cannot have one.** Thirteen cases, graded by
Level 12's scoring, floored at 0.95 — seven of them expecting nothing, because
this tier's failure mode is enthusiasm rather than blindness. `DRIFT` is
deliberately ungraded: its answer comes from a model, and a corpus that pinned a
model's answers would measure the recording. It is bounded by attribution and by
stated caps instead, and a test asserts no case grades it.

**A model is used here for judgement and for nothing else.** One question, one
of three words back, and everything else discarded. `unsure` is a first-class
answer rather than a failure, because a model forced to choose between "stale"
and "current" will choose, and the choice it makes when it does not know is
noise wearing a verdict's clothes.

**The findings name locations, never sentences.** Sixth level with that rule and
the first where the quoted material would be prose a person wrote.

## Alternatives considered

**One namespace with a `verified` flag.** Rejected because the safety property
would then depend on every consumer reading the flag. As two namespaces it
depends on a table that already exists and is already tested.

**Deterministic only.** Cheaper, and it would have missed the case the level was
asked for: the document that describes behaviour without naming it.

**A manually maintained map of module to document section.** The most precise
answer available, and the map goes stale exactly the way the documentation does
— with nothing to check it.

**Reporting every unresolvable reference.** Measured, and it produced
twenty-five findings in one README. A namespace that does that once is a
namespace people mute.
