"""Removing records on purpose, without making it look like an attack.

Level 24. [Level 20](../../docs/roadmap/level-20/spec.md) left retention out
because *"data lifecycle is an organisation's policy"*, and that is still true
of the **policy**. It was never true of the **mechanism**: a store with no
deletion path makes every policy an organisation might choose unimplementable,
so the honest answer to an erasure request becomes "we would edit the file by
hand" — which is the operation the rest of this level exists to make detectable.

Two properties, and they pull against each other, which is the whole design.

**Erasure must not break verification.** A deletion that leaves a hole is
indistinguishable from an attack, and a verifier that cries tamper every time
somebody honours a legal request is a verifier nobody keeps. So the chain is
**rewritten** and re-signed.

**Rewriting must not launder a tamper.** If the store did not verify before, it
is not touched. Re-sealing somebody else's edit would destroy the only evidence
that the edit happened, using the tool built to detect it.

A removed record leaves a **tombstone**: same position, no content, and the time
and policy it went under. So the store says "something was here and was removed
deliberately" rather than saying nothing at all.

Nothing here runs by itself. Not on a timer, not at the end of a review, not as
a default — a test parses the review path and asserts it does not so much as
import this module.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from code_reviewer.application.ports import AuditStore, NullSigner, Signer

logger = logging.getLogger(__name__)

#: The key a tombstone lives under. A payload with this and nothing else is a
#: position somebody emptied on purpose.
TOMBSTONE = "tombstone"

#: Fields on a record that name a subject. Redaction empties exactly these; the
#: rest of the record is what makes it still a record of a review.
SUBJECT_FIELDS = ("project", "merge_request")


@dataclass(frozen=True)
class ErasureOutcome:
    """What happened, or why nothing did."""

    removed: int = 0
    redacted: int = 0
    kept: int = 0
    #: Why the store was left alone. Empty when it was not.
    refused: str = ""


def erase(
    store: AuditStore,
    *,
    policy: str,
    now: str,
    before: str = "",
    project: str = "",
    merge_request: str = "",
    signer: Signer | None = None,
) -> ErasureOutcome:
    """Replaces matching records with tombstones and re-seals the store.

    Args:
        store: The store.
        policy: What this erasure is being done under. Written into every
            tombstone, because "why is this position empty" is the first
            question anybody asks about one.
        now: When, as an ISO timestamp. Passed in rather than read, so a caller
            records the time it means rather than the time this ran.
        before: Remove records recorded strictly before this timestamp.
        project: Remove records of this project.
        merge_request: Remove records of this merge request.
        signer: What re-signs the rewritten store. A store that was signed and
            cannot be re-signed is refused rather than left unverifiable.

    At least one selector is required. "Erase everything" is a mistake somebody
    makes exactly once, and it is not available by omission.
    """
    selector = _Selector(before=before, project=project, merge_request=merge_request)
    if not selector.names_something:
        return ErasureOutcome(refused="an erasure must name what to remove; nothing was given")

    return _rewrite(
        store,
        signer,
        transform=lambda payload: (
            {TOMBSTONE: {"removed_at": now, "policy": policy}} if selector.matches(payload) else payload
        ),
        counts=lambda before_, after: (
            "removed",
            sum(1 for p in after if TOMBSTONE in p) - sum(1 for p in before_ if TOMBSTONE in p),
        ),
    )


def redact(
    store: AuditStore,
    *,
    policy: str,
    now: str,
    project: str = "",
    merge_request: str = "",
    signer: Signer | None = None,
) -> ErasureOutcome:
    """Empties the fields naming a subject, and keeps everything else.

    The weaker operation, and often the right one: the organisation still needs
    to be able to say a review happened, and only the identifiers have to go.
    The redaction is marked on the record, because an empty field is otherwise
    indistinguishable from one nobody set.
    """
    selector = _Selector(project=project, merge_request=merge_request)
    if not selector.names_something:
        return ErasureOutcome(refused="a redaction must name a subject; nothing was given")

    def transform(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not selector.matches(payload):
            return payload
        redacted = dict(payload)
        for field in SUBJECT_FIELDS:
            if field in redacted:
                redacted[field] = ""
        redacted["redacted_at"] = now
        redacted["redaction_policy"] = policy
        return redacted

    return _rewrite(
        store,
        signer,
        transform=transform,
        counts=lambda before_, after: (
            "redacted",
            sum(1 for p in after if p.get("redacted_at")) - sum(1 for p in before_ if p.get("redacted_at")),
        ),
    )


# -- internals --------------------------------------------------------------


@dataclass(frozen=True)
class _Selector:
    """Which records an operation applies to.

    Extracted because `erase` reached cyclomatic complexity 17 with the
    matching inline, and the dogfooding gate reported it against this
    repository's own source — for the eighth time, and correctly: "which
    records" and "what to do about them" are two questions that were sharing a
    function.
    """

    before: str = ""
    project: str = ""
    merge_request: str = ""

    @property
    def names_something(self) -> bool:
        return bool(self.before or self.project or self.merge_request)

    def matches(self, payload: Mapping[str, Any]) -> bool:
        if TOMBSTONE in payload or not self.names_something:
            return False
        if self.before and str(payload.get("recorded_at", "")) >= self.before:
            return False
        if self.project and str(payload.get("project", "")) != self.project:
            return False
        return not (self.merge_request and str(payload.get("merge_request", "")) != self.merge_request)


def _rewrite(store: AuditStore, signer: Signer | None, transform, counts) -> ErasureOutcome:
    """Transforms, re-seals and replaces — or refuses and touches nothing."""
    if not store.exists():
        return ErasureOutcome(refused="there is no store at that path")

    signer = signer or NullSigner()

    verifiable, why = store.is_verifiable(signer)
    if not verifiable:
        # Not rewritten. Re-sealing somebody else's edit would destroy the only
        # evidence that it happened, using the tool built to detect it.
        return ErasureOutcome(
            refused=f"the store does not verify ({why}); rewriting it would re-seal the alteration"
        )

    if store.is_signed() and not signer.is_signing:
        return ErasureOutcome(
            refused="the store is signed and no key was given to sign the rewrite; "
            "the result would be a store nobody could verify"
        )

    original = store.payloads()
    transformed = [dict(transform(payload)) for payload in original]
    label, changed = counts(original, transformed)

    if changed <= 0:
        return ErasureOutcome(kept=len(original))

    store.replace(transformed, signer)
    logger.info("Rewrote the audit store: %d record(s) %s", changed, label)
    return ErasureOutcome(
        removed=changed if label == "removed" else 0,
        redacted=changed if label == "redacted" else 0,
        kept=len(original) - (changed if label == "removed" else 0),
    )
