# Level 24 — A record somebody else can check

## Problem statement

[Level 20](../level-20/spec.md) built the decision record and, in the same
document, refused three things:

> **Signing or an append-only store.** A record whose integrity has to survive a
> hostile operator needs a key nobody in this repository holds and a store
> nobody has chosen.

> **A compliance framework.** No control catalogue, no SOC 2 mapping, no
> attestation format. Those are an organisation's, and inventing one here would
> be guessing at somebody else's obligations.

> **Retention, redaction requests, or a deletion path.** Data lifecycle is an
> organisation's policy.

Each refusal was right about the thing it named and wrong about the thing next
to it. The record cannot hold a key — but it can be *signable*, and the
difference between "we did not sign it" and "nothing here can verify a
signature" is the whole of this level. This repository cannot decide an
organisation's control catalogue — but a record that cannot be *mapped* to one
forces every organisation to re-derive the mapping from source code. And the
retention policy is somebody else's — but a store with no deletion path makes
every policy they might choose unimplementable.

Concretely, today:

- **A record can be edited and nothing notices.** `REVIEW_AUDIT_PATH` names a
  file an operator can open in an editor. The claim "this review blocked on
  `SAST.SQL_INJECTION`" is exactly as trustworthy as the person holding the
  filesystem, and there is no artefact that says otherwise.
- **A record can be deleted and nothing notices.** Newline-delimited JSON has no
  sequence, so removing a line leaves a file that reads as complete. An
  inconvenient verdict is one `sed` away from never having happened.
- **Nothing says what a rule is evidence of.** An auditor asking "show me that
  code changes are reviewed for injection flaws" is handed rule ids and left to
  map them.
- **Nothing can be deleted on purpose either.** A subject-access or erasure
  request has no mechanism, so the honest answer is "we would edit the file by
  hand", which is the same operation this level is trying to make detectable.

Capabilities addressed: **C-24** (integrity of the audit trail), **C-25** (an
evidence mapping an organisation can adopt), **C-26** (a lifecycle a policy can
be written against). All three are sourced from Level 20's own non-goals rather
than from a role description, and the inventory says so.

## Goals

1. A record is **signed**, by a key the deployment supplies and this repository
   never generates, stores or defaults.
2. Records form a **chain**: each carries the digest of the one before it and
   its own position, so an edited, removed or reordered line is detectable.
   **Truncation is not** detectable from the file alone — a prefix of a valid
   chain is a valid chain — so verification reports where the store ends and
   accepts a count from outside it (self-review S-01).
3. A **verifier** that reads a store and says what it found — intact, broken at
   line N, or unverifiable because no key was given.
4. A **control mapping** from rule namespace to a named catalogue, shipped as
   data rather than code, with the catalogue's identity and version stated.
5. A **retention and erasure path**: a documented operation that removes or
   redacts records by age or by subject, and that **leaves the chain
   verifiable** rather than silently broken.

## Non-goals

- **Generating or holding a key.** A key this repository could produce is a key
  an attacker who has the repository can produce. The signer is a port; the
  default adapter reads a key the operator supplies and **refuses to run
  without one** rather than falling back to something weaker.
- **Defeating an operator who controls the store *and* the key.** Nothing in
  software can. What this level buys is *detection* — a tamper that requires the
  key is a different event from one that requires only write access, and only
  the second is what an ordinary mistake or an ordinary insider produces. The
  spec says this plainly rather than implying more.
- **Choosing a store.** No database, no object store, no managed service. The
  sink is already a port; this level adds a verifiable *format*, which any store
  can hold.
- **Authoring a control catalogue.** The mapping ships for one named,
  publicly-documented catalogue and is a data file an organisation replaces. The
  repository does not claim the mapping is complete or that using it makes
  anybody compliant — a claim like that is the documentation defect Level 23
  exists to catch, in the one place where it would be expensive.
- **Attestations, certifications or evidence bundles.** Producing a document
  addressed to an auditor is an organisation's work product.
- **Deciding a retention period.** The mechanism takes a policy; it does not
  contain one. A default that silently deletes anything is the wrong default.
- **Encrypting the record.** It holds identifiers only — five levels of that
  rule — so confidentiality is the store's problem and not the format's.

## Behavioural contracts

### C-1 — A record is signed or plainly unsigned
Every written record carries a signature and the identifier of the key that made
it, or carries neither. A record with a signature field that nothing produced is
worse than an unsigned one: it reads as verified.

### C-2 — No key, no signature, and the run says so
A deployment that supplies no key writes unsigned records and logs it once. The
review still runs: an accountability feature may not fail the thing it accounts
for — the rule since Level 20's C-9.

### C-3 — Each record names its predecessor
A record carries the digest of the previous record in the same store. The first
carries a stated genesis value rather than an empty string, so "this is the
first" and "somebody removed the field" are distinguishable.

### C-4 — Verification answers with a position, not a boolean
The verifier reports the first line that fails and why: signature invalid, chain
broken, or malformed. A yes/no answer over a thousand records is not actionable.

### C-5 — An unverifiable store is not a failed one
No key, an unknown key id, an unsigned tail: each is reported as *unverifiable*
and distinguished from *tampered*. Conflating them makes the tool cry wolf on
its first day in a deployment that has not configured a key.

### C-6 — The mapping is data, and it names its catalogue
Rule namespace to control identifier, in a file that states the catalogue, its
version and its publisher. An unmapped namespace is reported as unmapped rather
than silently omitted.

### C-7 — The mapping claims coverage, never compliance
Rendering says which controls have evidence in this run and which have none. It
never says an organisation is compliant, and a test asserts the word does not
appear in the rendered output.

### C-8 — Erasure rewrites the chain rather than breaking it
Removing or redacting records produces a store that still verifies, and a
**tombstone** at each removed position saying that something was removed, when,
and under which policy — so erasure and tampering stay distinguishable.

### C-9 — Erasure is explicit and never automatic
No record is removed by a review, by a timer, or by a default. It happens when
an operator runs the command and names what to remove.

### C-10 — Nothing here reaches the verdict
Signing, verification, mapping and erasure are all outside the review path. A
signer that fails costs the signature; it never costs the review.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A signed record carries a signature and a key id | Unit test |
| AC-2 | With no key, records are written unsigned and the omission is logged | Unit test |
| AC-3 | A signer that raises costs the signature, not the record | Unit test |
| AC-4 | Each record carries the previous record's digest; the first carries the genesis value | Unit test |
| AC-5 | Editing any field of any record makes verification report that line | Verifier test |
| AC-6 | Deleting a line makes verification report the break at the following line | Verifier test |
| AC-7 | Reordering two lines is detected | Verifier test |
| AC-8 | Appending a validly-signed record from a different key id is reported | Verifier test |
| AC-9 | A store with no signatures is reported unverifiable, not tampered | Verifier test |
| AC-10 | Verification of an intact store of 1 000 records reports intact | Verifier test |
| AC-11 | The mapping resolves every namespace the suite and Levels 22–23 emit | Data test |
| AC-12 | An unmapped namespace is rendered as unmapped | Renderer test |
| AC-13 | The rendered coverage never contains the word "compliant" | Renderer test |
| AC-14 | Erasure by age removes the intended records and the store still verifies | Erasure test |
| AC-15 | Erasure leaves a tombstone naming when and under which policy | Erasure test |
| AC-16 | Redaction of a subject leaves the record's structure and verifiability intact | Erasure test |
| AC-17 | Nothing erases without an explicit command; a review never does | Service test |
| AC-18 | A failing signer, verifier or mapper never changes an exit code | Service test |
| AC-19 | The key is never written to a log, a record, or the rendered output | Unit test |
| AC-20 | The six checks stay green, coverage holds, all three eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval ×3 |

## Decisions taken

**D-1 — Detection, not prevention, and the difference is written down.** An
operator with the key and the store can forge anything. What a chain plus a
signature buys is that the cheap attacks — edit a line, delete a line, reorder
two — stop being invisible. Overclaiming here would be worse than not signing:
it would put a false assurance in front of the person who most needs a true one.

**D-2 — The key comes from the deployment or there is no signature.** No
generated key, no bundled key, no derived-from-the-hostname key. Each of those
is a key an attacker with the repository already has, and shipping one would let
a deployment believe it had integrity it did not.

**D-3 — A chain in the format, not a store that promises append-only.** Storage
guarantees vary by deployment and cannot be tested here. A digest in the line is
testable in this repository, on every store, today.

**D-4 — The mapping is data and its catalogue is named.** Someone else's
obligations belong in someone else's file. Shipping one named catalogue as a
starting point is useful; shipping it as *the* answer is the overclaim Level 20
was right to refuse.

**D-5 — Erasure rewrites and tombstones.** A deletion that leaves a hole is
indistinguishable from an attack, which would make the verifier useless in
exactly the deployments that have a legal reason to delete. Rewriting under the
key, and leaving a marked gap, keeps both operations legible.

**D-6 — Every one of these runs outside the review.** Level 20 established that
recording a verdict may not cost one. Signing, verifying, mapping and erasing
are further from the verdict than recording is, and they inherit the rule.
