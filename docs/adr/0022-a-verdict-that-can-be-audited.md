# 0022 — A verdict that can be audited

Status: Accepted
Date: 2026-08-09
Level: [20](../roadmap/level-20/spec.md)

## Context

Nineteen levels produced a system that decides whether a merge may proceed.
None of them could answer, six months later, *why*.

A finding names its rule and its location. It does not name what produced it,
under which rule set, with which model, from which prompt. The merge-request
comment carries some of that in prose, and a comment can be edited, deleted, or
lost with the project.

The sharper problem is that the strongest claim this architecture makes was
unproven. [ADR 0004](0004-findings-drive-the-gate.md) says the gate decides
from findings and never from the model's prose. That has been true by
construction and by review since Level 4, and *nothing checked it*. In a
regulated setting the claim that a language model cannot block a merge is
precisely the claim somebody will ask to see evidence for, and "we were careful"
is not evidence.

## Decision

### The central claim becomes an invariant

`DecisionRecord.__post_init__` refuses a record whose verdict is blocking and
whose blocking findings name a non-deterministic producer. The message names the
finding, the producer and the ADR.

That is the whole level in one paragraph. Everything else here is vocabulary or
plumbing; this is the line that turns a design principle into a control, and the
difference between the two is exactly what an auditor is asking about.

`ProducerKind.is_deterministic` is a property on the enum rather than a
convention somebody has to remember, because the comparison it encodes is the
one thing in this module worth getting right.

### Attribution is fail-closed

A finding's producer comes from its rule namespace: `SAST.*` is an analyzer,
`SANDBOX.*` is the tool that refused the read. Anything unregistered is an
**agent** — non-deterministic, and therefore unable to block. An unattributable
claim is an opinion until somebody says otherwise.

A test asserts that every namespace the analysis suite can emit is registered,
and that no finding it emits carries an empty rule id, so the default never
fires in practice: adding an analyzer is a red test rather than a silent
misattribution. When it *does* fire, the review is unaffected and the record
says it is incomplete and why — the record follows the verdict, never the other
way round.

### A prompt is a fingerprint, not a text

`fingerprint(*prompts)` is a 12-character `blake2b` digest of the generalist's
template and each specialism's, in composition order. Recording the text would
put the system's instructions into a file read more widely than the repository,
for no gain. Recording nothing would make "the prompt changed between these two
reviews" unprovable. A digest answers the question that is actually asked.

`blake2b` rather than the builtin `hash` for the reason the embeddings use it: a
value that changes per process is not an identity. A test pins the digest of a
known string, so changing the hashing is a change somebody has to make
deliberately.

### The record carries identifiers, never content

Rule ids, locations, severities, counts, versions, CWE citations, a trace id.
Never a diff, a file's contents, a finding's evidence line or a model's prose. A
test builds a record from a review whose finding carries a credential-shaped
string in its description, its remediation *and* its evidence, serialises the
whole record, and asserts the string is absent.

Fourth level with this rule, and the same two reasons: an audit file is read by
more people than a merge request, and a diff may contain a secret. It is also
what makes a retention policy simple to write — there is nothing here to redact.

### No signing, and the sink is a port

A record whose integrity has to survive a hostile operator needs a key nobody in
this repository holds and a store nobody has chosen. Saying that is more honest
than a hash chain anyone with write access can rebuild. `AuditSink` is a port,
so a deployment that needs an append-only store has somewhere to put it; the
shipped implementation appends newline-delimited JSON to a file.

Appending, not overwriting: the HTTP service reviews many merge requests, and
one file per process would keep only the last.

### Writing the record cannot fail the review

A sink that raises is logged and the review returns normally. A record that
cannot be *built* is written as an incomplete one, with the reason, rather than
as nothing — a missing file is indistinguishable from a review nobody ran.

Fifth level with the rule that observability may not fail the thing it observes.

### It is off unless asked for

`--audit-path`, or `REVIEW_AUDIT_PATH`. A file appearing beside a checkout
because a tool was run is a surprise, and this one names merge requests. The
environment variable matters because the HTTP service builds its review from the
command line's *defaults*: a container is configured with variables, not with a
command line it never sees.

## Consequences

An auditor can be handed a file. Each line says what was decided, under which
package, policy, rule set, model and prompt digest, on the strength of which
rules, what was suppressed and why, what each specialism cost, and which trace
holds the timing. The merge-request comment repeats the accountable half of it,
so a reader who never opens the file is still told what decided.

A blocking record that cites a model is now unrepresentable. If a future level
lets an agent produce findings directly, this test suite goes red — which is the
point.

The record cites the trace by id rather than embedding it. Two artefacts, one
identifier between them; copying a forty-span tree into every record would make
both harder to read and neither more true.

What this does not do: attest to compliance with any framework, sign anything,
guarantee the file survives a determined operator, or explain the model's
reasoning. The last one is deliberate — "why did the model conclude that" is not
answerable, and a system that produces a plausible-sounding answer to it has
manufactured evidence.
