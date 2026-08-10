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
__all__ = ["DEFAULT_KEY_ID", "MINIMUM_KEY_BYTES", "HmacSigner", "NullSigner", "signer_from_environment"]

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

    def accepts(self, digest: str, signature: str, key_id: str) -> bool:
        """Whether this key produced that signature for that digest.

        Compared in constant time, and the key id has to match too: a validly
        signed record naming another key is somebody else's record, appended
        here (contract, AC-8).
        """
        if key_id != self._key_id:
            return False
        expected, _ = self.sign(digest)
        return hmac.compare_digest(expected, signature)


def signer_from_environment(environment: Mapping[str, str] | None = None) -> Signer:
    """The signer this deployment configured, or one that signs nothing.

    Never raises. A missing key is an ordinary state and is logged once; an
    unusable key is a misconfiguration, logged as a warning, and neither costs
    the review a thing.
    """
    import os

    source = environment if environment is not None else os.environ
    key = source.get(KEY_VARIABLE, "")

    if not key:
        logger.info(
            "No audit signing key configured; decision records will be chained but unsigned",
            extra={"fields": {"variable": KEY_VARIABLE}},
        )
        return NullSigner()

    try:
        return HmacSigner(key, key_id=source.get(KEY_ID_VARIABLE) or DEFAULT_KEY_ID)
    except ValueError as error:
        logger.warning(
            "The audit signing key cannot be used; records will be unsigned: %s",
            error,
            extra={"fields": {"variable": KEY_VARIABLE}},
        )
        return NullSigner()
