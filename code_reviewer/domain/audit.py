"""What makes a decision record checkable by somebody who does not trust you.

Level 24. [Level 20](../../docs/roadmap/level-20/spec.md) wrote the record and
refused to sign it, for a reason that was correct: *"a record whose integrity
has to survive a hostile operator needs a key nobody in this repository holds
and a store nobody has chosen."* Both halves of that are still true. Neither is
a reason for the record to be **unsignable**, and the gap between "we did not
sign it" and "nothing here can verify a signature" is what this module closes.

**What a seal buys, stated plainly** — and the first version of this paragraph
claimed more than it should have, which the self-review caught.

An operator holding the key *and* the store can forge anything, and no
arrangement of software changes that. What a chain plus a signature buys is
that three tampers stop being invisible: an edited line, a line removed from the
middle, two lines swapped. Those are what an ordinary mistake and an ordinary
insider produce.

Two things it does **not** buy. **Truncation** is undetectable from the file
alone, because a prefix of a valid chain is a valid chain and any anchor kept
inside a file can be truncated with it; verification therefore reports where the
store ends and accepts a count from outside (S-01). And an **unsigned** chain
catches corruption and carelessness only — the digest takes no key, so anybody
who can edit the file can recompute the chain (S-02).

Claiming more would put a false assurance in front of the person who most needs
a true one, which is worse than not signing at all (decision D-1).

Everything here is arithmetic over already-serialised data: no filesystem, no
key material, no clock. The key lives behind a port in the application layer,
and the store is somebody's deployment.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

#: What the first record in a store names as its predecessor.
#:
#: A stated value rather than an empty string, because "this is the first
#: record" and "somebody removed the field" are different facts and an empty
#: string is both. Sixty-four zeros: the shape of a digest, obviously not one.
GENESIS = "0" * 64

#: Hex characters, for the shape check. Cheaper and clearer than a regular
#: expression for a fixed-width lowercase digest.
_HEX = frozenset("0123456789abcdef")

#: A digest's width, in hex characters. `blake2b` at 32 bytes, matching the
#: fingerprint Level 20 already computes with the same primitive.
DIGEST_WIDTH = 64


@dataclass(frozen=True)
class Seal:
    """One record's position in the chain, and its signature if it has one.

    A signature without a key id is refused at construction. A field that says
    *signed* while naming nothing that could have signed it is worse than an
    absent one: a reader takes it for verification that happened.
    """

    #: The digest of the record before this one, or :data:`GENESIS`.
    previous: str
    #: The digest of this record, over its payload and its predecessor.
    digest: str
    #: Hex signature over :attr:`digest`, empty when unsigned.
    signature: str = ""
    #: Which key produced :attr:`signature`. Never the key itself.
    key_id: str = ""
    #: This record's position, from one.
    #:
    #: Carried and hashed so that renumbering to hide a removal breaks the
    #: digests. It does not make truncation *detectable* — a prefix of a valid
    #: chain is a valid chain, and any anchor inside a file can be truncated
    #: along with it (self-review S-01). What it buys is that verification can
    #: say where the store ends, so an operator holding any anchor from outside
    #: can compare.
    sequence: int = 0

    def __post_init__(self) -> None:
        if not self.previous:
            raise ValueError("A seal must name its predecessor; the first names GENESIS.")
        if not self.digest:
            raise ValueError("A seal must carry a digest.")
        if bool(self.signature) != bool(self.key_id):
            raise ValueError(
                "A signature and a key id travel together. A signature nothing can "
                "attribute reads as verification and names nothing that could have "
                "performed it."
            )

    @property
    def is_signed(self) -> bool:
        return bool(self.signature)


def digest_of(payload: Mapping[str, Any], previous: str = GENESIS, sequence: int = 0) -> str:
    """The digest of one record, bound to the record before it.

    The predecessor is part of what is hashed rather than merely stored beside
    it. Without that, two records with identical payloads could be swapped and
    every digest would still be correct — the reordering this is meant to catch
    would be invisible.

    Serialised with sorted keys, which is what the sink writes, so the digest
    agrees with the bytes on disk rather than with insertion order.
    """
    if not payload:
        raise ValueError("An empty payload is not a record.")
    try:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        # Refused rather than coerced. A digest over a best-effort rendering of
        # an unserialisable value would differ between processes, and a chain
        # that breaks by itself teaches an operator to ignore the verifier.
        raise ValueError(
            f"A record that will not serialise cannot be sealed: {type(error).__name__}"
        ) from error

    return hashlib.blake2b(
        f"{previous}\n{sequence}\n{body}".encode(), digest_size=DIGEST_WIDTH // 2
    ).hexdigest()


def is_digest(value: str) -> bool:
    """Whether a string has the shape of one of our digests."""
    return len(value) == DIGEST_WIDTH and all(character in _HEX for character in value)


class ChainStatus(Enum):
    """What a verification found.

    Three, and the third is the point. A deployment that has not configured a
    key has an unsigned store, and calling that *tampered* is how a verifier
    gets turned off before it ever sees a real tamper (contract C-5).
    """

    #: Every link holds and every signature that could be checked was valid.
    INTACT = "intact"
    #: Something does not add up, at a stated position.
    TAMPERED = "tampered"
    #: The links hold, but the signatures could not be established — no key, no
    #: signatures, or only some of them.
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class ChainVerdict:
    """What was found, and where.

    A position and a reason rather than a boolean. "Something is wrong somewhere
    in twelve hundred records" is not actionable, and a tool that answers that
    way gets run once (contract C-4).

    Carries no record content. Whoever reads this output is not necessarily
    somebody allowed to read the records.
    """

    status: ChainStatus
    #: 1-based position of the first failure; zero when there is none.
    position: int = 0
    reason: str = ""
    #: How many records were examined.
    checked: int = 0
    #: How many carried a signature.
    signed: int = 0
    #: The sequence of the last record. Nought for an empty store.
    #:
    #: Reported because truncation cannot be detected from the file alone: a
    #: prefix of a valid chain is a valid chain. An operator holding an anchor
    #: from outside — a monitoring counter, a previous run's output — compares
    #: against this (self-review S-01).
    last_sequence: int = 0


#: Signs a digest, returning the signature and the key that made it.
Signature = tuple[str, str]


def sealed(
    payload: Mapping[str, Any],
    previous: str = GENESIS,
    sign: "Callable[[str], Signature] | None" = None,
    sequence: int = 1,
) -> Seal:
    """The seal for one record, signed if a signer was given.

    A signer that raises is the caller's problem, not this function's: the
    decision about whether an unsignable record is still written belongs where
    the key does (contract C-2, and the sink makes it).
    """
    digest = digest_of(payload, previous, sequence)
    if sign is None:
        return Seal(previous=previous, digest=digest, sequence=sequence)
    signature, key_id = sign(digest)
    return Seal(previous=previous, digest=digest, signature=signature, key_id=key_id, sequence=sequence)


def verify(
    entries: "Sequence[tuple[Seal, Mapping[str, Any]]]",
    accepts: "Callable[[str, str, str], bool | None] | None" = None,
    expect_at_least: int = 0,
) -> ChainVerdict:
    """Checks a store, and reports the first thing that does not hold.

    Args:
        entries: Seals with the payloads they sealed, in stored order.
        accepts: Whether a signature is valid for a digest and key id. Passing
            ``None`` means no key is available at all, which makes signatures
            *unverifiable* rather than wrong. The callable itself answers three
            ways; see below.
        expect_at_least: How many records an anchor **outside this file** says
            the store should hold. Zero means no anchor was given, and then
            truncation is not detectable at all: a prefix of a valid chain is a
            valid chain, and an anchor kept inside a file can be truncated with
            it (self-review S-01).

    Two failures are distinguished on purpose. A **digest** that disagrees with
    its payload means that record was edited. A **link** that does not point at
    the record before it means one was removed, inserted or moved. An operator
    needs to know which, and the reason says so.

    So is a third thing, since Level 30. ``accepts`` answers ``True``,
    ``False`` or ``None``, and ``None`` means **the verifier holds no key with
    that name** — which is the state of anybody who has rotated a key. Reading
    that as ``False`` turned the most routine operation in key management into
    an accusation of forgery, against this module's own rule that unverifiable
    is not tampered.
    """
    previous = GENESIS
    signed = 0
    unheld: list[str] = []

    for position, (seal, payload) in enumerate(entries, start=1):
        if seal.previous != previous:
            return ChainVerdict(
                ChainStatus.TAMPERED,
                position,
                "the chain does not link here: a record was removed, inserted or moved",
                position - 1,
                signed,
                position - 1,
            )

        if seal.sequence != position:
            return ChainVerdict(
                ChainStatus.TAMPERED,
                position,
                "the record's own position disagrees with where it is stored",
                position - 1,
                signed,
                position - 1,
            )

        if seal.digest != digest_of(payload, seal.previous, seal.sequence):
            return ChainVerdict(
                ChainStatus.TAMPERED,
                position,
                "the digest disagrees with the record: this line was edited",
                position - 1,
                signed,
                position - 1,
            )

        if seal.is_signed:
            signed += 1
            if accepts is not None:
                answer = accepts(seal.digest, seal.signature, seal.key_id)
                if answer is None:
                    # A key the verifier does not hold. The link still holds and
                    # the digest still matches: nothing here is evidence of a
                    # tamper, and saying so would be the cry-wolf this module
                    # was written to avoid. Collected and reported at the end,
                    # because a real tamper further on is the more serious
                    # finding and must be the one an operator sees.
                    if seal.key_id not in unheld:
                        unheld.append(seal.key_id)
                elif not answer:
                    return ChainVerdict(
                        ChainStatus.TAMPERED,
                        position,
                        "the signature is not one this key could have produced",
                        position - 1,
                        signed - 1,
                        position - 1,
                    )

        previous = seal.digest

    if expect_at_least and len(entries) < expect_at_least:
        return ChainVerdict(
            ChainStatus.TAMPERED,
            len(entries),
            f"the store holds {len(entries)} record(s); it was expected to hold at least "
            f"{expect_at_least}, so it has been truncated",
            len(entries),
            signed,
            len(entries),
        )

    return _signature_verdict(len(entries), signed, accepts, tuple(unheld))


def _signature_verdict(
    checked: int, signed: int, accepts: object, unheld: tuple[str, ...] = ()
) -> ChainVerdict:
    """Every link held. Whether that is the whole story depends on the keys."""
    if checked == 0:
        return ChainVerdict(ChainStatus.INTACT, checked=0, last_sequence=0)
    if unheld:
        # Named rather than counted: the operator's next move is to find that
        # key or to accept that it is gone, and both need the name (C-5).
        #
        # And said *beside* the unsigned count rather than instead of it. This
        # branch used to replace it, so a store with an unheld key and an
        # unsigned record reported only the first — and an operator who found
        # the key would come back to a store that still did not verify
        # (self-review 30, S-04).
        also = (
            f"; {checked - signed} of {checked} record(s) are unsigned and attest to nothing"
            if signed < checked
            else ""
        )
        return ChainVerdict(
            ChainStatus.UNVERIFIABLE,
            reason=(
                "the links hold; no key was given for "
                f"{', '.join(unheld)}, so what those records attest to cannot be checked{also}"
            ),
            checked=checked,
            signed=signed,
            last_sequence=checked,
        )
    if accepts is None:
        if signed == 0:
            return ChainVerdict(
                ChainStatus.INTACT,
                checked=checked,
                reason="no signatures were expected",
                last_sequence=checked,
            )
        return ChainVerdict(
            ChainStatus.UNVERIFIABLE,
            reason="the records are signed and no key was given to check them",
            checked=checked,
            signed=signed,
            last_sequence=checked,
        )
    if signed == 0:
        return ChainVerdict(
            ChainStatus.UNVERIFIABLE,
            reason="the links hold; the records are unsigned, so nothing attests to them",
            checked=checked,
            last_sequence=checked,
        )
    if signed < checked:
        return ChainVerdict(
            ChainStatus.UNVERIFIABLE,
            reason=f"the links hold; {checked - signed} of {checked} record(s) are unsigned",
            checked=checked,
            signed=signed,
            last_sequence=checked,
        )
    return ChainVerdict(ChainStatus.INTACT, checked=checked, signed=signed, last_sequence=checked)
