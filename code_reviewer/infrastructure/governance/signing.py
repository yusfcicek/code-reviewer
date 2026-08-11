"""Signing a decision record with a key this repository never produces.

Level 24, and the decision the whole module exists to enforce (D-2): **a key
this repository could generate is a key an attacker who has this repository can
generate.** So there is no generated key, no bundled key, no
derived-from-the-hostname key, and no fallback to a weaker scheme. The key comes
from the deployment or nothing is signed.

Two refusals sit either side of that.

A key that is present but unusable — empty, too short — does not produce a
signer, because a signer holding a guessable key would let a deployment believe
it had integrity it does not. And an unusable key does not stop the process
either: refusing to start would make one mistyped environment variable cost
every review, which is the failure mode Level 20's contract C-9 already ruled
out for the record itself.

HMAC rather than a public-key signature, deliberately. It is symmetric, so the
verifier needs the same key the signer had — which is honest about what this
buys. A public-key scheme would let a third party verify without the signing
key, and that is worth having; it is also a key-distribution problem this
repository cannot solve on somebody's behalf. The port is here, and an Ed25519
adapter is a sibling module.
"""

import hashlib
import hmac
import logging
from collections.abc import Mapping

from code_reviewer.application.ports import NullSigner, Signer

#: Re-exported: the null object lives beside the port it implements, and this
#: module is where a caller looks for signers.
__all__ = [
    "DEFAULT_KEY_ID",
    "MINIMUM_KEY_BYTES",
    "HmacSigner",
    "Keyring",
    "NullSigner",
    "signer_from_environment",
]

logger = logging.getLogger(__name__)

#: Shortest key accepted, in characters. Below this the signature is a
#: formality: a key somebody can guess makes every record it signs look
#: attested when nothing attests to it.
MINIMUM_KEY_BYTES = 16

#: What a key is called when the deployment did not say. Stated rather than
#: empty, because the domain refuses a signature whose key id names nothing.
DEFAULT_KEY_ID = "unnamed-key"

#: Where the key and its name are read from.
KEY_VARIABLE = "REVIEW_AUDIT_KEY"
KEY_ID_VARIABLE = "REVIEW_AUDIT_KEY_ID"

#: Where a **retired** key is read from: one variable per key, the key id in
#: the variable's own name.
#:
#: One variable rather than a list, so nothing has to be parsed out of secret
#: material — a separator inside a key is a key that silently becomes two
#: (Level 30, decision D-4). The id is taken from the name exactly as written,
#: because it is compared against what a record wrote and a record wrote a
#: case-sensitive string.
RETIRED_PREFIX = "REVIEW_AUDIT_KEY_RETIRED_"


class HmacSigner(Signer):
    """Signs with a key the deployment supplied.

    The key is held in a private attribute and never reaches ``repr``, a log
    record, a signature or a key id. That is asserted by tests rather than
    asserted by this sentence — it is the one piece of real credential material
    in the repository.
    """

    __slots__ = ("_key", "_key_id")

    def __init__(self, key: str, key_id: str = DEFAULT_KEY_ID):
        if len(key) < MINIMUM_KEY_BYTES:
            # The reason never quotes the key. A refusal that prints what it
            # refused is a refusal that puts the secret in a log.
            raise ValueError(
                f"The audit signing key is too short: at least {MINIMUM_KEY_BYTES} characters are needed."
            )
        if not key_id:
            raise ValueError("A signing key needs a name; an unattributable signature attests to nothing.")
        self._key = key.encode("utf-8")
        self._key_id = key_id

    def __repr__(self) -> str:
        return f"HmacSigner(key_id={self._key_id!r})"

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def is_signing(self) -> bool:
        return True

    def sign(self, digest: str) -> tuple[str, str]:
        return hmac.new(self._key, digest.encode("utf-8"), hashlib.sha256).hexdigest(), self._key_id

    def accepts(self, digest: str, signature: str, key_id: str) -> bool | None:
        """Whether this key produced that signature for that digest.

        Three answers since Level 30, and the third is what a rotation needs:
        ``None`` means *this is not my key*, which is not the same as *this
        signature is wrong*. Reading the two as one boolean made replacing a
        key turn every earlier record into an accusation of forgery.

        Compared in constant time when the key does match.
        """
        if key_id != self._key_id:
            return None
        expected, _ = self.sign(digest)
        return hmac.compare_digest(expected, signature)


class Keyring(Signer):
    """One key that signs, several that can still verify.

    Level 30. Rotation is the most routine operation in key management and this
    repository could not survive it: with one signer holding one key, every
    record written under the previous key verified as `tampered`. The keyring
    is what makes "we changed the key" and "somebody forged this" different
    events again.

    A retired key **never signs** (contract C-1). Otherwise "retired" is a
    label rather than a property, and the key id a record carries stops meaning
    what it says.
    """

    __slots__ = ("_by_id", "_signing")

    def __init__(self, signing: Signer, retired: "tuple[Signer, ...]" = ()):
        self._signing = signing
        self._by_id: dict[str, Signer] = {}
        for key in (*retired, signing):
            if not key.is_signing:
                continue
            if key.key_id in self._by_id:
                # A key id is what a record names. Two keys answering to one
                # name make a record's attribution a coin flip.
                raise ValueError(f"The key id {key.key_id!r} is configured twice.")
            self._by_id[key.key_id] = key

    def __repr__(self) -> str:
        return f"Keyring(signing={self._signing.key_id!r}, holds={sorted(self._by_id)!r})"

    @property
    def key_id(self) -> str:
        return self._signing.key_id

    @property
    def is_signing(self) -> bool:
        return self._signing.is_signing

    @property
    def key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def sign(self, digest: str) -> tuple[str, str]:
        return self._signing.sign(digest)

    def accepts(self, digest: str, signature: str, key_id: str) -> bool | None:
        """What the key of that name says, or ``None`` if there is no such key."""
        key = self._by_id.get(key_id)
        if key is None:
            return None
        return key.accepts(digest, signature, key_id)


def _retired_keys(source: Mapping[str, str]) -> "tuple[Signer, ...]":
    """Every usable retired key in the environment, in name order.

    An unusable one is a warning and nothing more: refusing to start over a
    mistyped variable would make one typo cost every review, which is the rule
    Level 20's contract C-9 settled for the record itself.
    """
    keys = []
    for variable in sorted(source):
        if not variable.startswith(RETIRED_PREFIX):
            continue
        key_id = variable[len(RETIRED_PREFIX) :]
        try:
            keys.append(HmacSigner(source[variable], key_id=key_id))
        except ValueError as error:
            logger.warning(
                "A retired audit key cannot be used; records it signed will be unverifiable: %s",
                error,
                extra={"fields": {"variable": variable}},
            )
    return tuple(keys)


def signer_from_environment(environment: Mapping[str, str] | None = None) -> Signer:
    """The signer this deployment configured, or one that signs nothing.

    Never raises. A missing key is an ordinary state and is logged once; an
    unusable key is a misconfiguration, logged as a warning, and neither costs
    the review a thing.
    """
    import os

    source = environment if environment is not None else os.environ
    key = source.get(KEY_VARIABLE, "")
    retired = _retired_keys(source)

    signing: Signer = NullSigner()
    if not key:
        logger.info(
            "No audit signing key configured; decision records will be chained but unsigned",
            extra={"fields": {"variable": KEY_VARIABLE}},
        )
    else:
        try:
            signing = HmacSigner(key, key_id=source.get(KEY_ID_VARIABLE) or DEFAULT_KEY_ID)
        except ValueError as error:
            logger.warning(
                "The audit signing key cannot be used; records will be unsigned: %s",
                error,
                extra={"fields": {"variable": KEY_VARIABLE}},
            )

    if not retired:
        return signing

    # The most likely mistake in the operation this exists for: retiring the key
    # you are still signing with. `Keyring` refuses two keys under one name, and
    # rightly — a key id is what a record names. But that refusal reaching the
    # composition root would take the review with it, and an accountability
    # feature may not fail the thing it accounts for (Level 20, contract C-9;
    # self-review 30, S-01).
    #
    # The signing key keeps the name, because it is the one about to write
    # records under it. The duplicate retired entry is dropped and said so.
    kept: list[Signer] = []
    for retired_key in retired:
        if signing.is_signing and retired_key.key_id == signing.key_id:
            logger.warning(
                "A retired audit key is configured under the same name as the signing key; "
                "the signing key keeps the name and the retired entry is ignored",
                extra={"fields": {"key_id": retired_key.key_id}},
            )
            continue
        kept.append(retired_key)

    # A deployment that has stopped signing can still read its own history,
    # which is why this is reached even with no current key.
    return Keyring(signing=signing, retired=tuple(kept))
