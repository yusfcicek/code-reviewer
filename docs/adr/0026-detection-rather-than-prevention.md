# ADR 0026 — Detection rather than prevention, and saying so

**Status** Accepted · **Level** 24 · **Supersedes** nothing ·
**Depends on** [0022](0022-a-verdict-that-can-be-audited.md)

## Context

[Level 20](../roadmap/level-20/spec.md) built the decision record and refused
three things in the same document: signing, a control mapping, and a retention
path. Each refusal was correct about the thing it named and wrong about the
thing beside it.

> *"A record whose integrity has to survive a hostile operator needs a key
> nobody in this repository holds and a store nobody has chosen."*

True. It is not a reason for the record to be **unsignable**, and "we did not
sign it" and "nothing here can verify a signature" are different states.

> *"No control catalogue, no SOC 2 mapping. Those are an organisation's, and
> inventing one here would be guessing at somebody else's obligations."*

True of the obligations. Not of the mapping: without one, every organisation
re-derives "which rule is evidence of which control" from source code, by hand,
and gets a different answer.

> *"Retention, redaction requests, or a deletion path. Data lifecycle is an
> organisation's policy."*

True of the policy. But a store with no deletion path makes every policy
unimplementable, so the honest answer to an erasure request becomes *"we would
edit the file by hand"* — the exact operation the rest of this level exists to
make detectable.

## Decision

**Build detection, not prevention, and write down which one it is.**

The store gains a chain and a signature. Each record names the digest of the one
before it and, when the deployment supplied a key, carries a signature over its
own digest. A verifier reads a store and answers with a **position and a
reason**, in one of three states.

The claim that comes with it is deliberately small:

> An operator holding the key **and** the store can forge anything, and no
> arrangement of software changes that. What this buys is that three tampers
> stop being invisible: an edited line, a line removed from the middle, two
> lines swapped.

Those are what an ordinary mistake and an ordinary insider produce. Two things
it does **not** buy, and the self-review of this level found both because the
first draft of this paragraph did not say them:

**Truncation is undetectable from the file alone.** A prefix of a valid chain is
a valid chain, and an anchor kept inside a file can be truncated with it. Each
record therefore carries its position, verification reports where the store
ends, and `--expect-at-least` compares against a count the operator kept
elsewhere. That is a comparison, not a detection, and it is described as one.

**An unsigned chain catches corruption, not attackers.** The digest takes no
key, so anybody who can edit the file can recompute the chain. The verifier says
so on every unsigned answer rather than leaving a deployment to infer it.

Claiming more would put a false assurance in front of the person who most needs
a true one.

Three consequences follow directly.

**No key is ever generated here.** A key this repository could produce is a key
an attacker who has this repository can produce. The signer is a port; the
default adapter reads a key the deployment supplies and refuses to construct
without one. A deployment with no key writes a chained, unsigned store — and
`unverifiable` is a first-class verdict rather than a failure, because that is
the state every deployment is in on its first day.

**The catalogue is data and names itself.** One publicly documented, versioned
catalogue ships as a YAML file an organisation replaces. The rendering says what
a run is *evidence of* and never that anybody is compliant — a test asserts the
words "compliant" and "certified" do not appear in the output.

**Erasure rewrites and tombstones.** A deletion that leaves a hole is
indistinguishable from an attack, which would make the verifier useless in
exactly the deployments with a legal reason to delete. So the chain is rewritten
under the key and each removed position keeps a marker naming when and under
which policy. And a store that did not verify **before** the erasure is not
rewritten: re-sealing somebody else's edit would destroy the only evidence it
happened, using the tool built to detect it.

## Consequences

**A three-valued answer, everywhere.** `intact`, `tampered`, `unverifiable` —
in the domain type, in the command's exit code, and in the sentence an operator
reads. Collapsing the third into either of the others is how a verifier gets
turned off before it ever sees a real tamper.

**HMAC, and its limitation stated.** Symmetric, so verification needs the key
signing needed. That is honest about what ships: a public-key scheme would let a
third party verify without the signing key, and that is a key-distribution
problem this repository cannot solve on somebody's behalf. The port makes an
Ed25519 adapter a sibling module.

**A fourth entry point.** Verifying, erasing and redacting are an operator's
actions, run where the records are rather than where the reviews happen. None of
them is reachable from a review: a test parses the review path and asserts it
does not import the erasure module at all.

**Nothing here can fail a review.** Signing, chaining, verifying, mapping and
erasing all sit outside the verdict. A signer that raises writes the record
unsigned; a store that cannot be written loses the record and logs it. Level 20
already ruled that recording a verdict may not cost one, and everything in this
level is further from the verdict than recording is.

## Alternatives considered

**Generate a key when none is configured.** Rejected outright. It would let a
deployment believe it had integrity it does not, which is worse than the honest
unsigned state — and the key would be derivable by anybody with the source.

**Promise an append-only store.** Storage guarantees vary by deployment and
cannot be tested here. A digest in the line is testable in this repository, on
every store, today.

**Refuse to start without a key.** Considered, and rejected for the same reason
Level 20 gave about the sink: one mistyped environment variable would cost every
review. The misconfiguration is logged and the reviews continue.

**Ship no catalogue and document the shape instead.** Honest, and useless: the
work an organisation avoids is exactly the mapping, and a shape with no entries
saves nobody an afternoon.

**Delete by rewriting without tombstones.** Smaller output, and it makes
erasure indistinguishable from tampering at the one moment when telling them
apart matters most.
