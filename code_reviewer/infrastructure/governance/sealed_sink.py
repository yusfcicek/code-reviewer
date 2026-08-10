"""A store whose lines say what came before them.

Level 24, and the one place the integrity claim touches a filesystem.

The read is the part worth reading twice. The previous digest comes from **the
file**, not from an attribute: a sink that remembered it would produce a store
that verifies perfectly inside one process and forks at every restart — and the
fork would look exactly like a tamper to whoever ran the verifier next.

Three refusals inherited from Level 20's contract C-9, which said that recording
a verdict may not cost one. A signer that raises writes the record unsigned. A
tail that cannot be parsed starts a new chain **and says so**, rather than
guessing at a predecessor. A path that cannot be written loses the record and
logs it. None of them reaches the review.

The append itself is guarded by an advisory lock where the platform has one, so
two workers writing to one store do not both read the same predecessor. Where
there is no lock the sink still works and the verifier still detects the fork —
which is the honest arrangement: the guarantee is stated by what verification
reports, not by what the writer hopes.
"""

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from code_reviewer.application.governance import AuditSink
from code_reviewer.application.ports import Signer
from code_reviewer.domain.audit import GENESIS, ChainStatus, ChainVerdict, Seal, sealed, verify
from code_reviewer.domain.provenance import DecisionRecord

from .json_sink import to_json
from .signing import NullSigner

logger = logging.getLogger(__name__)

#: Bytes read from the end of the store to find the last line. Generous for a
#: record of identifiers, and bounded so appending to a large store costs the
#: same as appending to a small one.
TAIL_BYTES = 64 * 1024


class SealedAuditSink(AuditSink):
    """Appends a record with a seal binding it to the record before it.

    Args:
        path: Where the records go.
        signer: What signs each digest. A :class:`NullSigner` writes a chained
            but unsigned store, which is what a deployment with no key gets.
    """

    def __init__(self, path: str | Path, signer: Signer | None = None):
        self._path = Path(path)
        self._signer = signer or NullSigner()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: DecisionRecord) -> None:
        payload = to_json(record)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a+", encoding="utf-8") as handle, _locked(handle):
                seal = sealed(payload, self._previous(), sign=self._sign)
                handle.write(json.dumps({"record": payload, "seal": _seal_json(seal)}, sort_keys=True))
                handle.write("\n")
                handle.flush()
        except OSError as error:
            logger.warning("Could not write the decision record to %s: %s", self._path, error)

    # -- internals ----------------------------------------------------------

    def _sign(self, digest: str) -> tuple[str, str]:
        """Signs, or gives up on the signature rather than on the record."""
        if not self._signer.is_signing:
            return "", ""
        try:
            return self._signer.sign(digest)
        except Exception as error:
            logger.warning(
                "The record could not be signed and is written unsigned: %s: %s",
                type(error).__name__,
                error,
            )
            return "", ""

    def _previous(self) -> str:
        """The digest of the last record in the store, or GENESIS.

        A store whose last line will not parse is not chained onto: continuing
        from a guessed predecessor would produce a link that fails verification
        for a reason nobody could diagnose. Starting a new chain is visible in
        the verifier's output and is logged here.
        """
        line = _last_line(self._path)
        if line is None:
            return GENESIS
        try:
            digest = json.loads(line)["seal"]["digest"]
        except (ValueError, KeyError, TypeError):
            logger.warning(
                "The audit store's last line could not be read; starting a new chain at %s. "
                "Verification will report the discontinuity.",
                self._path,
            )
            return GENESIS
        return str(digest) or GENESIS


def read_store(path: str | Path) -> "list[tuple[Seal, Mapping[str, Any]]]":
    """Every sealed record in a store, in stored order.

    A line that will not parse yields a seal that cannot verify, on purpose:
    silently skipping it would let anybody delete a record by corrupting it.
    """
    target = Path(path)
    if not target.is_file():
        return []

    entries: list[tuple[Seal, Mapping[str, Any]]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entries.append(_entry(line))
    return entries


def verify_store(path: str | Path, signer: Signer | None = None) -> ChainVerdict:
    """Reads a store and checks it.

    ``signer`` is what can attest to the signatures. Without one, a signed store
    is *unverifiable* rather than wrong — the state of anybody holding the file
    and not the key.
    """
    entries = read_store(path)
    accepts = signer.accepts if signer is not None and signer.is_signing else None
    return verify(entries, accepts=accepts)


# -- internals --------------------------------------------------------------

#: What an unreadable line becomes: a seal that cannot match anything, so the
#: verifier reports its position rather than passing over it.
_UNREADABLE = "unreadable"


def _entry(line: str) -> "tuple[Seal, Mapping[str, Any]]":
    try:
        document = json.loads(line)
        raw = document["seal"]
        seal = Seal(
            previous=str(raw["previous"]),
            digest=str(raw["digest"]),
            signature=str(raw.get("signature", "")),
            key_id=str(raw.get("key_id", "")),
        )
        return seal, document["record"]
    except (ValueError, KeyError, TypeError):
        return Seal(previous=_UNREADABLE, digest=_UNREADABLE), {"unreadable": True}


def _seal_json(seal: Seal) -> dict[str, str]:
    return {
        "previous": seal.previous,
        "digest": seal.digest,
        "signature": seal.signature,
        "key_id": seal.key_id,
    }


def _last_line(path: Path) -> str | None:
    """The store's final non-empty line, read from the end.

    Bounded rather than a full read: appending to a store of a hundred thousand
    records should cost what appending to a store of ten costs.
    """
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError as error:
        logger.warning("Could not read the audit store's tail: %s", error)
        return None

    lines = [line for line in tail.splitlines() if line.strip()]
    return lines[-1] if lines else None


class _locked:
    """An advisory exclusive lock, where the platform has one.

    Two workers appending to one store would otherwise read the same
    predecessor and fork the chain. Where `fcntl` is absent the sink still
    works: the fork becomes something the verifier reports rather than
    something the writer prevented, and saying which of the two is happening is
    the whole point of this level.
    """

    def __init__(self, handle):
        self._handle = handle
        self._locked = False

    def __enter__(self):
        try:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
            self._locked = True
        except (ImportError, OSError) as error:
            logger.debug("Appending without a lock: %s", error)
        return self

    def __exit__(self, *exc_info) -> None:
        if not self._locked:
            return
        try:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError) as error:
            # Closing the handle releases it anyway. Logged rather than
            # swallowed: a lock that would not release is worth knowing about
            # even when it costs nothing here.
            logger.debug("Could not release the audit store lock: %s", error)


def status_line(verdict: ChainVerdict) -> str:
    """One line an operator can read, naming positions and never content."""
    if verdict.status is ChainStatus.INTACT:
        return f"intact: {verdict.checked} record(s), {verdict.signed} signed"
    if verdict.status is ChainStatus.UNVERIFIABLE:
        return f"unverifiable: {verdict.reason} ({verdict.checked} record(s))"
    return f"TAMPERED at record {verdict.position}: {verdict.reason}"
