# ADR 0032 — A key that is gone is not a key that lied

**Status** Accepted · **Level** 30

## Context

Level 24 sealed the decision record and wrote the rule the whole module rests
on: **`unverifiable` is not `tampered`.** A deployment with no key is in a state,
not under attack, and a verifier that cries wolf there is one somebody turns off
before it ever sees a real tamper.

Its own key handling did not carry the rule. `Signer.accepts` returned a
boolean, so it said the same thing about a signature it had checked and found
wrong as about a key id it had never heard of. The consequence was not
theoretical:

```
with the key that signed it:  intact
after rotating the key:       tampered
                              "the signature is not one this key could have produced"
```

Rotating a signing key is the most routine operation in key management. Doing it
turned every record written beforehand into an accusation of forgery — and the
operator's only ways out were to keep one key forever or to re-sign history under
the new one, which erases the record of which key attested to what.

## Decision

**Three answers where there were two.** `accepts` returns `True`, `False` or
`None`, and `None` means *the verifier holds no key with that name*. The chain
verifier reads it as unverifiable, keeps going, and names the key ids it could
not check — an operator's next move is to find that key or accept that it is
gone, and both need the name.

**A keyring: one key signs, several verify.** A retired key never signs.
Otherwise "retired" is a label rather than a property, and the key id a record
carries stops meaning what it says.

**Retired keys come from the environment, one variable each**, with the key id in
the variable's own name. Nothing is parsed out of secret material — a separator
inside a key is a key that silently becomes two.

**History is never re-signed under a new key.** The key id is the only record of
which key attested to what; re-signing erases it and calls the result an
improvement.

## Consequences

A deployment can rotate a key and keep reading its history. One that has stopped
signing altogether can still verify what it signed before, which the plumbing got
wrong on the first attempt: it asked whether the signer was *signing* and used
the answer to decide whether it could *check* anything.

An erasure now refuses a store it cannot verify **at all**, not only one it has
caught. Re-sealing records signed by a key nobody holds would destroy the only
evidence of who attested to them, using the tool built to detect that.

Three of Level 24's four remaining non-goals stay refused, each with the thing
that was missing underneath it:

| non-goal | Level 30 |
|---|---|
| Holding a key | **Built.** The keyring above; still no key this repository can generate. |
| Choosing a store | **Refused**, and what a store must *do* is an executable conformance suite. |
| An attestation | **Refused.** Every fact one would contain is already machine-readable; what a document adds is the cover page, and the cover page is where a claim gets made that this repository cannot support. |
| Encrypting the record | **Refused**, and the premise — identifiers, never content — is now a test over every field rather than a habit. |

What none of this buys is unchanged and worth restating: an operator holding the
key and the store can forge anything. What a chain plus a signature buys is that
an edit, a removal and a reordering stop being invisible.
