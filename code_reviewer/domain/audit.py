"""What makes a decision record checkable by somebody who does not trust you.

Level 24. [Level 20](../../docs/roadmap/level-20/spec.md) wrote the record and
refused to sign it, for a reason that was correct: *"a record whose integrity
has to survive a hostile operator needs a key nobody in this repository holds
and a store nobody has chosen."* Both halves of that are still true. Neither is
a reason for the record to be **unsignable**, and the gap between "we did not
sign it" and "nothing here can verify a signature" is what this module closes.

**What a seal buys, stated plainly.** An operator holding the key *and* the
store can forge anything, and no arrangement of software changes that. What a
chain plus a signature buys is that the cheap tampers — edit one line, delete
one line, swap two — stop being invisible. Those are the tampers an ordinary
mistake and an ordinary insider actually produce. Claiming more would put a
false assurance in front of the person who most needs a true one, which is
worse than not signing at all (decision D-1).

Everything here is arithmetic over already-serialised data: no filesystem, no
key material, no clock. The key lives behind a port in the application layer,
and the store is somebody's deployment.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
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


def digest_of(payload: Mapping[str, Any], previous: str = GENESIS) -> str:
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

    return hashlib.blake2b(f"{previous}\n{body}".encode(), digest_size=DIGEST_WIDTH // 2).hexdigest()


def is_digest(value: str) -> bool:
    """Whether a string has the shape of one of our digests."""
    return len(value) == DIGEST_WIDTH and all(character in _HEX for character in value)
