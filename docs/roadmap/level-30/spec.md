# Level 30 — Key custody, and three refusals with reasons

## Problem statement

Level 24 sealed the decision record and listed four things it would not do: hold
a key, choose a store, produce an attestation, encrypt the record. Each was a
sound refusal at the time. This level takes them one at a time and either builds
the thing or refuses it again in writing — and the first of them turns out not to
be a refusal at all but a defect.

**Rotating the signing key makes an intact chain report as forged.**

```
with the key that signed it:  intact
after rotating the key:       tampered
                              "the signature is not one this key could have produced"
```

`HmacSigner.accepts` answers `False` for any key id other than its own, and the
domain reads `False` as *this signature is wrong*. So the single most routine
operation in key management — replacing a key — turns every record written
before it into an accusation of tampering.

Level 24's own discipline is the one thing that would have caught it:

> **`unverifiable` is not `tampered`.** A store with no key is what it is.

A store signed under a key nobody holds any more is exactly that state, and the
code had no way to say it. Two things are being conflated by one boolean: *I
checked this signature and it is wrong* and *I hold no key with that name*.

Capability addressed: **C-37** — the record survives the key management a real
deployment does. Sourced from Level 24's non-goals, read one at a time.

## Goals

1. A deployment can rotate its signing key without its history becoming
   unverifiable, and without a retired key ever signing anything again.
2. Three answers where there were two: valid, invalid, and *no key of that name*.
   The third is `UNVERIFIABLE`, never `TAMPERED`.
3. The store choice is refused again — and what a store must *do* is made
   executable, so refusing to pick one stops meaning "and you are on your own".
4. Attestation and encryption are refused again, each with a reason that is
   better than the one Level 24 gave, because there is more evidence now.
5. Encryption's premise — a record holds identifiers, never content — stops
   being an agreement and becomes a test.

## Non-goals

- **Choosing a store.** Still no database, no object store, no managed service.
  See the refusal below; it is the same refusal with an executable contract
  attached.
- **Generating, deriving or storing a key.** Unchanged from Level 24, and the
  keyring inherits every one of its refusals: too short, no name, no fallback.
- **A public-key scheme.** Worth having and still a key-distribution problem this
  repository cannot solve for somebody. The port takes an adapter.
- **Automatic rotation, expiry dates or a key schedule.** When a key is retired
  is an operator's decision and a clock, and this module has neither.
- **Re-signing history under the new key.** It would erase the evidence of which
  key attested to what, which is the only thing a key id is for.
- **An attestation document.** Refused again, below.
- **Encrypting the record.** Refused again, below, with the premise enforced.

## The four, one at a time

### 1. Key custody — **built**

A keyring: one signing key, any number of retired verify-only keys, each named.
Signing uses the current key alone. Verification tries the key the record names
and answers in three ways rather than two. A retired key that is later removed
from the deployment makes its records *unverifiable*, which is the truth.

### 2. Choosing a store — **refused, and the contract shipped**

Still not chosen, for Level 24's reason: the sink is a port and a format any
store can hold is worth more than a binding to one. What was missing is that
"any store can hold it" was an assertion — nothing said what a store must *do*.

So: an executable conformance suite. Any `AuditStore` adapter is run against it,
the shipped file adapter passes it, and an adapter that loses ordering, forgets
a record or reports a truncated store as intact fails it. Refusing to choose is
honest; refusing to say what the choice must satisfy is not.

### 3. Attestation — **refused**

Level 24 said: *producing a document addressed to an auditor is an
organisation's work product.* That holds, and there is now a sharper way to put
it. Everything an attestation would contain already exists and is
machine-readable: the chain verdict, the count, the key ids, the run identity,
the control mapping. What a document would add is the cover page — the sentence
that says what those facts *mean* — and the cover page is exactly where a claim
gets made that this repository cannot support.

A bundle with a cover page is the documentation defect Level 23 exists to catch,
in the one place where it would be expensive to be wrong.

### 4. Encrypting the record — **refused, and the premise made checkable**

Level 24: *it holds identifiers only, so confidentiality is the store's problem
and not the format's.* Still right, and it was resting on a habit. Five levels
have said "identifiers, never content" and nothing enforced it on the record
itself.

A test now reads every field a `DecisionRecord` can carry and refuses a value
that looks like source text. The refusal to encrypt is only honest while its
premise is true, so the premise becomes a test rather than a sentence.

## Behavioural contracts

### C-1 — A retired key verifies and never signs
The keyring signs with the current key only. A retired key can confirm what it
signed and can do nothing else.

### C-2 — A signature naming a key nobody holds is unverifiable
Not tampered. The distinction is the level, and it is the same distinction Level
24 wrote and did not carry into its own key handling.

### C-3 — A wrong signature under a key we hold is still tampered
The keyring does not soften anything. Where the answer is known, it is given.

### C-4 — A record naming no key id at all is unsigned
Unchanged: a signature field nothing produced is worse than no signature.

### C-5 — The verdict says which keys it could not check
Named, not counted. An operator's next action is to find that key or to accept
that it is gone, and both need the name.

### C-6 — A retired key is subject to every refusal a signing key is
Too short, unnamed: refused, and the deployment is told once. A weak key does
not become acceptable by being old.

### C-7 — Any store adapter passes one suite or is not an adapter
Ordering, sequence, read-back, and a truncated store reported as truncated.

### C-8 — A decision record cannot carry source text
Enforced by a test over every field the record has, so the encryption refusal
keeps its premise.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A chain signed under a retired key verifies as intact | Unit test |
| AC-2 | A chain signed under an unknown key id is `UNVERIFIABLE` | Unit test |
| AC-3 | A wrong signature under a held key is `TAMPERED` | Unit test |
| AC-4 | The keyring signs only with the current key | Unit test |
| AC-5 | The verdict names the key ids it could not check | Unit test |
| AC-6 | A retired key that is too short or unnamed is refused and logged | Unit test |
| AC-7 | Retired keys are read from the environment, never from the repository | Unit test |
| AC-8 | The key never reaches `repr`, a log, a signature or a key id — retired ones too | Unit test |
| AC-9 | `FileAuditStore` passes the store conformance suite | Conformance test |
| AC-10 | An adapter that loses order or a record fails the suite | Conformance test |
| AC-11 | No `DecisionRecord` field can carry source text | Unit test |
| AC-12 | `ai-code-review-audit` names an unverifiable key rather than reporting a tamper | CLI test |
| AC-13 | The six checks stay green, coverage holds, all five harnesses hold | `ruff`, `mypy`, `pytest --cov`, audit, eval ×5 |

## Decisions taken

**D-1 — Three answers, not two.** `accepts` returns `None` for a key id the
verifier does not hold. A boolean cannot carry the difference between *wrong* and
*unknown*, and this repository has spent two levels on exactly that distinction
in other places.

**D-2 — A retired key never signs.** Otherwise "retired" is a label rather than a
property, and the key id in a record stops meaning what it says.

**D-3 — History is never re-signed under a new key.** The key id is the only
record of which key attested to what; re-signing erases it and calls the result
an improvement.

**D-4 — One environment variable per retired key, named by its id.** No separator
to parse inside secret material, and a key id that cannot collide with a value.

**D-5 — Refuse three of four, and say why each is still a refusal.** A level that
turned every non-goal into a feature would be a level that had stopped reading
its own reasons.
